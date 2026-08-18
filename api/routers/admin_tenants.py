"""Tenant onboarding: create plants, create users, invite-based password
setup, and the audit trail behind all of it.

Closes SHIPPING.md item 0.2. Before this router, the only way to add a
plant or a user was running seed/seed.py by hand against the database -
no admin surface existed at all. That script also resets the
global_admin's password on every run (see its production guard). This is
the real onboarding path; seed.py remains what it always was, a
dev-fixture script, not a customer-onboarding tool.

Invite flow, not admin-picks-a-password: creating a user here never sets
a real, usable password. It generates a one-time invite token (returned
once, in the response body - never stored raw, see migration
0007_tenant_onboarding's docstring for why) and the new user sets their
own password by visiting /invite/{token}. No credential is ever
transmitted by a human over Slack/email/WhatsApp.

Every mutation here writes an audit_log row. This is a global_admin
surface that can create accounts with real access - "who added this user,
when, with what role" must never depend on someone remembering to check
git blame on a seed script.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from .. import ratelimit, security
from ..db import global_engine
from ..deps import CurrentUser, db_session, get_current_user
from .admin_common import require_global, require_global_admin

router = APIRouter(tags=["admin-tenants"])

INVITE_EXPIRY_HOURS = 72
_DB_ROLES = (
    "global_admin", "global_read", "plant_admin", "plant_operator", "plant_viewer", "dept_user",
)


def _hash_token(token: str) -> str:
    # sha256, not bcrypt: this is a high-entropy random token (32 bytes,
    # secrets.token_urlsafe), not a human-chosen password - there is no
    # brute-force-by-guessing risk bcrypt's deliberate slowness defends
    # against, and hashing thousands of these (bulk onboarding) should
    # stay fast.
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def _write_audit(
    conn: AsyncConnection, actor_user_id: str, action: str, target_type: str, target_id: str, detail: dict
) -> None:
    await conn.execute(
        text(
            """
            INSERT INTO audit_log (actor_user_id, action, target_type, target_id, detail)
            VALUES (:actor, :action, :target_type, :target_id, CAST(:detail AS jsonb))
            """
        ),
        {
            "actor": actor_user_id,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "detail": json.dumps(detail),
        },
    )


# ---------------------------------------------------------------------------
# Plants
# ---------------------------------------------------------------------------


class SensorIn(BaseModel):
    sensor_id: str = Field(min_length=1, max_length=64)
    tag: str = Field(min_length=1, max_length=64)
    kind: str = Field(min_length=1, max_length=64)
    unit: str = Field(min_length=1, max_length=32)
    min_valid: float | None = None
    max_valid: float | None = None


class PlantIn(BaseModel):
    plant_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")
    name: str = Field(min_length=1, max_length=200)
    lat: float | None = None
    lon: float | None = None
    ambient_climate: str | None = Field(default=None, max_length=100)
    boiler_capacity_tpd: float | None = None
    fuel_type_primary: str | None = Field(default=None, max_length=100)
    commissioning_date: str | None = None
    timezone_display: str = "Asia/Kolkata"
    # Optional so a plant record can exist before its hardware ships, but
    # this is the atomic path: a plant AND its sensor manifest in one
    # transaction, not two separate admin actions that can drift apart.
    sensors: list[SensorIn] = Field(default_factory=list)


@router.get("/admin/plants")
async def list_plants(
    user: CurrentUser = Depends(get_current_user),
    conn: AsyncConnection = Depends(db_session),
):
    require_global(user)
    rows = (
        await conn.execute(
            text(
                """
                SELECT p.plant_id, p.name, p.commissioning_date,
                       COUNT(DISTINCT s.sensor_id) AS sensor_count,
                       COUNT(DISTINCT up.user_id) AS user_count
                FROM plants p
                LEFT JOIN sensors s ON s.plant_id = p.plant_id
                LEFT JOIN user_plants up ON up.plant_id = p.plant_id
                GROUP BY p.plant_id, p.name, p.commissioning_date
                ORDER BY p.plant_id
                """
            )
        )
    ).mappings().all()
    return {"plants": [dict(r) for r in rows]}


@router.post("/admin/plants", status_code=status.HTTP_201_CREATED)
async def create_plant(
    body: PlantIn,
    user: CurrentUser = Depends(get_current_user),
    conn: AsyncConnection = Depends(db_session),
):
    require_global_admin(user)

    exists = (
        await conn.execute(text("SELECT 1 FROM plants WHERE plant_id = :p"), {"p": body.plant_id})
    ).first()
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"plant_id '{body.plant_id}' already exists")

    sensor_ids = [s.sensor_id for s in body.sensors]
    if len(sensor_ids) != len(set(sensor_ids)):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="duplicate sensor_id in manifest")

    await conn.execute(
        text(
            """
            INSERT INTO plants (plant_id, name, lat, lon, ambient_climate,
                                 boiler_capacity_tpd, fuel_type_primary,
                                 commissioning_date, timezone_display)
            VALUES (:plant_id, :name, :lat, :lon, :ambient_climate,
                    :boiler_capacity_tpd, :fuel_type_primary,
                    :commissioning_date, :timezone_display)
            """
        ),
        body.model_dump(exclude={"sensors"}),
    )
    for s in body.sensors:
        await conn.execute(
            text(
                """
                INSERT INTO sensors (plant_id, sensor_id, tag, kind, unit, min_valid, max_valid)
                VALUES (:plant_id, :sensor_id, :tag, :kind, :unit, :min_valid, :max_valid)
                """
            ),
            {"plant_id": body.plant_id, **s.model_dump()},
        )

    await _write_audit(
        conn, user.user_id, "plant.created", "plant", body.plant_id,
        {"name": body.name, "sensor_count": len(body.sensors)},
    )
    return {"plant_id": body.plant_id, "sensors_created": len(body.sensors)}


# ---------------------------------------------------------------------------
# Users + invites
# ---------------------------------------------------------------------------


class UserIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    role: str
    # Required for the three plant_* roles, ignored (must be empty) for
    # global_admin/global_read - a global role scoped to specific plants
    # is a contradiction the API should reject, not silently accept.
    plant_ids: list[str] = Field(default_factory=list)
    # Required for role='dept_user' (one of security.DEPARTMENTS), must be
    # None for every other role - same "no contradictory scoping" rule as
    # plant_ids above, just on the department axis instead of the plant one.
    department: str | None = None


class UserPatch(BaseModel):
    role: str | None = None
    department: str | None = None
    plant_ids: list[str] | None = None
    is_active: bool | None = None


@router.get("/admin/users")
async def list_users(
    user: CurrentUser = Depends(get_current_user),
    conn: AsyncConnection = Depends(db_session),
):
    require_global(user)
    rows = (
        await conn.execute(
            text(
                """
                SELECT u.user_id, u.email, u.role, u.department, u.is_active, u.created_at,
                       COALESCE(array_agg(up.plant_id) FILTER (WHERE up.plant_id IS NOT NULL), '{}') AS plant_ids,
                       EXISTS (
                           SELECT 1 FROM user_invites i
                           WHERE i.user_id = u.user_id AND i.used_at IS NULL AND i.expires_at > now()
                       ) AS invite_pending
                FROM users u
                LEFT JOIN user_plants up ON up.user_id = u.user_id
                GROUP BY u.user_id, u.email, u.role, u.department, u.is_active, u.created_at
                ORDER BY u.created_at DESC
                """
            )
        )
    ).mappings().all()
    return {"users": [dict(r) for r in rows]}


def _issue_invite_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    return token, _hash_token(token)


@router.post("/admin/users", status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserIn,
    user: CurrentUser = Depends(get_current_user),
    conn: AsyncConnection = Depends(db_session),
):
    require_global_admin(user)

    if body.role not in _DB_ROLES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"role must be one of {_DB_ROLES}")
    is_plant_role = body.role.startswith("plant_")
    is_dept_role = body.role == "dept_user"
    if is_plant_role and not body.plant_ids:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"role '{body.role}' requires at least one plant_id")
    if not is_plant_role and body.plant_ids:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"role '{body.role}' must not carry plant_ids")
    if is_dept_role and body.department not in security.DEPARTMENTS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"role 'dept_user' requires department to be one of {sorted(security.DEPARTMENTS)}",
        )
    if not is_dept_role and body.department is not None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"role '{body.role}' must not carry a department")

    exists = (await conn.execute(text("SELECT 1 FROM users WHERE email = :e"), {"e": body.email})).first()
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="a user with this email already exists")

    if is_plant_role:
        found = (
            await conn.execute(text("SELECT plant_id FROM plants WHERE plant_id = ANY(:p)"), {"p": body.plant_ids})
        ).scalars().all()
        missing = set(body.plant_ids) - set(found)
        if missing:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"unknown plant_id(s): {sorted(missing)}")

    # Placeholder pw_hash: a hash of a random, never-transmitted, never-
    # logged secret. Satisfies the NOT NULL/bcrypt-shaped column and is
    # cryptographically impossible to guess, so this account cannot be
    # logged into until the invite is accepted and overwrites it for real.
    placeholder_hash = security.hash_password(secrets.token_urlsafe(32))

    row = (
        await conn.execute(
            text(
                """
                INSERT INTO users (email, pw_hash, role, department)
                VALUES (:email, :pw_hash, :role, :department)
                RETURNING user_id
                """
            ),
            {"email": body.email, "pw_hash": placeholder_hash, "role": body.role, "department": body.department},
        )
    ).first()
    new_user_id = str(row[0])

    for plant_id in body.plant_ids:
        await conn.execute(
            text("INSERT INTO user_plants (user_id, plant_id) VALUES (:u, :p)"),
            {"u": new_user_id, "p": plant_id},
        )

    token, token_hash = _issue_invite_token()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=INVITE_EXPIRY_HOURS)
    await conn.execute(
        text(
            """
            INSERT INTO user_invites (user_id, token_hash, expires_at)
            VALUES (:u, :h, :exp)
            """
        ),
        {"u": new_user_id, "h": token_hash, "exp": expires_at},
    )

    await _write_audit(
        conn, user.user_id, "user.created", "user", new_user_id,
        {"email": body.email, "role": body.role, "plant_ids": body.plant_ids, "department": body.department},
    )

    return {
        "user_id": new_user_id,
        "email": body.email,
        "role": body.role,
        "plant_ids": body.plant_ids,
        "department": body.department,
        # Returned exactly once. The DB only ever stores its hash - if
        # this response is lost, use POST /admin/users/{id}/reinvite.
        "invite_token": token,
        "invite_expires_at": expires_at.isoformat(),
    }


@router.patch("/admin/users/{user_id}")
async def patch_user(
    user_id: str,
    body: UserPatch,
    user: CurrentUser = Depends(get_current_user),
    conn: AsyncConnection = Depends(db_session),
):
    """Edits an existing account's role/department/plant scoping, or
    flips is_active - the piece POST /admin/users alone can't do (that
    endpoint only ever creates a brand new invite-pending user). Every
    field is optional; only what's provided is changed."""
    require_global_admin(user)

    existing = (
        await conn.execute(text("SELECT role, department FROM users WHERE user_id = :u"), {"u": user_id})
    ).mappings().first()
    if existing is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="user not found")

    if body.is_active is False and user_id == user.user_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="cannot deactivate your own account")

    new_role = body.role if body.role is not None else existing["role"]
    new_department = body.department if "department" in body.model_fields_set else existing["department"]
    if new_role not in _DB_ROLES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"role must be one of {_DB_ROLES}")
    is_plant_role = new_role.startswith("plant_")
    is_dept_role = new_role == "dept_user"
    if is_dept_role and new_department not in security.DEPARTMENTS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"role 'dept_user' requires department to be one of {sorted(security.DEPARTMENTS)}",
        )
    if not is_dept_role and new_department is not None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"role '{new_role}' must not carry a department")

    if body.plant_ids is not None:
        if not is_plant_role and body.plant_ids:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"role '{new_role}' must not carry plant_ids")
        if is_plant_role and not body.plant_ids:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"role '{new_role}' requires at least one plant_id")
        if body.plant_ids:
            found = (
                await conn.execute(text("SELECT plant_id FROM plants WHERE plant_id = ANY(:p)"), {"p": body.plant_ids})
            ).scalars().all()
            missing = set(body.plant_ids) - set(found)
            if missing:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"unknown plant_id(s): {sorted(missing)}")
    elif is_plant_role != existing["role"].startswith("plant_"):
        # Role is changing across the plant-scoped/not-plant-scoped line
        # but plant_ids wasn't supplied - refuse rather than silently
        # leaving stale user_plants rows (an old plant grant surviving a
        # role change to dept_user would be a real privilege leak).
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="changing to/from a plant-scoped role requires plant_ids in the same request",
        )

    await conn.execute(
        text(
            """
            UPDATE users SET
                role = :role,
                department = :department,
                is_active = COALESCE(:is_active, is_active)
            WHERE user_id = :u
            """
        ),
        {"role": new_role, "department": new_department, "is_active": body.is_active, "u": user_id},
    )

    if body.plant_ids is not None:
        await conn.execute(text("DELETE FROM user_plants WHERE user_id = :u"), {"u": user_id})
        for plant_id in body.plant_ids:
            await conn.execute(
                text("INSERT INTO user_plants (user_id, plant_id) VALUES (:u, :p)"),
                {"u": user_id, "p": plant_id},
            )

    await _write_audit(
        conn, user.user_id, "user.updated", "user", user_id,
        {"role": new_role, "department": new_department, "plant_ids": body.plant_ids, "is_active": body.is_active},
    )
    return {"user_id": user_id, "role": new_role, "department": new_department, "is_active": body.is_active}


@router.post("/admin/users/{user_id}/reinvite", status_code=status.HTTP_201_CREATED)
async def reinvite_user(
    user_id: str,
    user: CurrentUser = Depends(get_current_user),
    conn: AsyncConnection = Depends(db_session),
):
    """Issues a fresh invite without touching the old one - the stale row
    stays as an honest record that a link was issued and went unused."""
    require_global_admin(user)
    row = (await conn.execute(text("SELECT email FROM users WHERE user_id = :u"), {"u": user_id})).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="user not found")

    token, token_hash = _issue_invite_token()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=INVITE_EXPIRY_HOURS)
    await conn.execute(
        text("INSERT INTO user_invites (user_id, token_hash, expires_at) VALUES (:u, :h, :exp)"),
        {"u": user_id, "h": token_hash, "exp": expires_at},
    )
    await _write_audit(conn, user.user_id, "user.reinvited", "user", user_id, {"email": row[0]})
    return {"invite_token": token, "invite_expires_at": expires_at.isoformat()}


@router.get("/admin/audit-log")
async def list_audit_log(
    limit: int = Query(default=100, le=500),
    user: CurrentUser = Depends(get_current_user),
    conn: AsyncConnection = Depends(db_session),
):
    require_global(user)
    rows = (
        await conn.execute(
            text(
                """
                SELECT a.log_id, a.action, a.target_type, a.target_id, a.detail,
                       a.created_at, u.email AS actor_email
                FROM audit_log a
                LEFT JOIN users u ON u.user_id = a.actor_user_id
                ORDER BY a.created_at DESC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        )
    ).mappings().all()
    return {"entries": [dict(r) for r in rows]}


# ---------------------------------------------------------------------------
# Public invite-accept endpoints - no session exists yet by definition.
# ---------------------------------------------------------------------------

_INVITE_GENERIC_ERROR = "this invite link is invalid, expired, or already used"


class AcceptInviteIn(BaseModel):
    password: str = Field(min_length=8, max_length=1024)


@router.get("/invites/{token}")
async def get_invite(token: str, request: Request):
    """Unauthenticated by necessity - no session exists until the invite is
    accepted, so this cannot go through deps.db_session (which requires a
    bearer token). Uses the BYPASSRLS global engine directly, the same
    pattern api/routers/auth.py's login endpoint uses for the same reason:
    reading a token/credential row to establish identity isn't a
    tenant-scoping violation, there is no tenant context yet.

    Rate-limited per IP (reusing the login limiter's generic two-key
    shape) against token-guessing - low real risk given 256 bits of
    entropy per token, but cheap insurance."""
    client_ip = request.client.host if request.client else "unknown"
    retry_after = ratelimit.check(client_ip, f"invite:{token[:12]}")
    if retry_after is not None:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too many attempts, try again later",
            headers={"Retry-After": str(retry_after)},
        )
    ratelimit.record_attempt(client_ip)

    async with global_engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    """
                    SELECT i.user_id, i.expires_at, i.used_at, u.email, u.role
                    FROM user_invites i
                    JOIN users u ON u.user_id = i.user_id
                    WHERE i.token_hash = :h
                    """
                ),
                {"h": _hash_token(token)},
            )
        ).mappings().first()

    if row is None or row["used_at"] is not None or row["expires_at"] < datetime.now(timezone.utc):
        ratelimit.record_failure(f"invite:{token[:12]}")
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=_INVITE_GENERIC_ERROR)

    return {"email": row["email"], "role": row["role"]}


@router.post("/invites/{token}/accept")
async def accept_invite(token: str, body: AcceptInviteIn, request: Request):
    client_ip = request.client.host if request.client else "unknown"
    retry_after = ratelimit.check(client_ip, f"invite:{token[:12]}")
    if retry_after is not None:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too many attempts, try again later",
            headers={"Retry-After": str(retry_after)},
        )
    ratelimit.record_attempt(client_ip)

    async with global_engine.begin() as conn:
        row = (
            await conn.execute(
                text(
                    """
                    SELECT invite_id, user_id, expires_at, used_at
                    FROM user_invites
                    WHERE token_hash = :h
                    """
                ),
                {"h": _hash_token(token)},
            )
        ).mappings().first()

        if row is None or row["used_at"] is not None or row["expires_at"] < datetime.now(timezone.utc):
            ratelimit.record_failure(f"invite:{token[:12]}")
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=_INVITE_GENERIC_ERROR)

        new_hash = security.hash_password(body.password)
        await conn.execute(
            text("UPDATE users SET pw_hash = :h WHERE user_id = :u"),
            {"h": new_hash, "u": row["user_id"]},
        )
        await conn.execute(
            text("UPDATE user_invites SET used_at = now() WHERE invite_id = :i"),
            {"i": row["invite_id"]},
        )
        await _write_audit(conn, str(row["user_id"]), "invite.accepted", "user", str(row["user_id"]), {})

    return {"status": "ok"}
