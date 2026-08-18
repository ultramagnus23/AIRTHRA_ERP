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

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import text

from .. import ratelimit, security
from ..db import global_engine
from ..schemas import LoginRequest, LoginResponse

router = APIRouter(tags=["auth"])


@router.post("/auth/login", response_model=LoginResponse)
async def login(body: LoginRequest, request: Request) -> LoginResponse:
    # Brute-force protection (see api/ratelimit.py for the two limits and
    # the proxy-header caveat). Checked before touching the DB so a
    # throttled attempt costs neither a query nor a bcrypt verify.
    client_ip = request.client.host if request.client else "unknown"
    retry_after = ratelimit.check(client_ip, body.email)
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too many login attempts, try again later",
            headers={"Retry-After": str(retry_after)},
        )
    ratelimit.record_attempt(client_ip)

    async with global_engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT user_id, pw_hash, role FROM users WHERE email = :email"),
                {"email": body.email},
            )
        ).mappings().first()

        if row is None or not security.verify_password(body.password, row["pw_hash"]):
            ratelimit.record_failure(body.email)
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

    ratelimit.clear_failures(body.email)
    token = security.create_access_token(
        user_id=str(row["user_id"]), role=jwt_role, plant_ids=plant_ids
    )
    return LoginResponse(access_token=token, role=jwt_role, plant_ids=plant_ids)
