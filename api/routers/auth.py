"""POST /auth/login.

Looks up the user + their plant scoping (user_plants) using the
BYPASSRLS global engine deliberately: at login time we don't yet know
the plant_ids to scope a tenant connection to (that's exactly what
we're computing), and `user_plants` itself carries RLS, so a tenant-role
connection couldn't read it without already knowing the answer. Reading
users/user_plants for authentication purposes is not a tenant-scoping
violation - the row being read *is* the caller's own account.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text

from .. import security
from ..db import global_engine
from ..schemas import LoginRequest, LoginResponse

router = APIRouter(tags=["auth"])


@router.post("/auth/login", response_model=LoginResponse)
async def login(body: LoginRequest) -> LoginResponse:
    async with global_engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT user_id, pw_hash, role FROM users WHERE email = :email"),
                {"email": body.email},
            )
        ).mappings().first()

        if row is None or not security.verify_password(body.password, row["pw_hash"]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid email or password",
            )

        jwt_role = security.DB_ROLE_TO_JWT_ROLE.get(row["role"])
        if jwt_role is None:
            # Defensive: should be unreachable given the DB CHECK constraint.
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"user has unmapped DB role '{row['role']}'",
            )

        plant_ids: list[str] = []
        if jwt_role not in security.GLOBAL_JWT_ROLES:
            plant_ids = list(
                (
                    await conn.execute(
                        text("SELECT plant_id FROM user_plants WHERE user_id = :uid ORDER BY plant_id"),
                        {"uid": row["user_id"]},
                    )
                ).scalars()
            )

    token = security.create_access_token(
        user_id=str(row["user_id"]), role=jwt_role, plant_ids=plant_ids
    )
    return LoginResponse(access_token=token, role=jwt_role, plant_ids=plant_ids)
