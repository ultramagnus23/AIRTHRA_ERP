"""Password hashing and JWT issuing/verification.

JWT role taxonomy (deliberately simplified from the DB's `users.role`
CHECK constraint, which is `global_admin | global_read | plant_admin |
plant_operator | plant_viewer | dept_user` - see
migrations/versions/0001_initial_schema.py and
migrations/versions/0013_department_users.py): the P2 client API only
cares about three access levels, so the three plant-scoped DB roles all
collapse to a single JWT role `tenant_read`, the two global DB roles map
1:1, and `dept_user` also maps 1:1 (see api/dept_deps.py for how it's
gated - one specific business function, never a plant, never everything).
"""
from __future__ import annotations

import time
from typing import Any

import jwt
from passlib.context import CryptContext

from . import config

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# users.role (DB) -> JWT role (API)
DB_ROLE_TO_JWT_ROLE = {
    "global_admin": "global_admin",
    "global_read": "global_read",
    "plant_admin": "tenant_read",
    "plant_operator": "tenant_read",
    "plant_viewer": "tenant_read",
    "dept_user": "dept_user",
}

GLOBAL_JWT_ROLES = {"global_admin", "global_read"}

# dept_user is not "global" (api/deps.py's is_global gates plant access,
# which a department user never gets - finance staff don't get to see
# live sensor readings for every plant just because they're not
# plant-scoped). It still needs the BYPASSRLS connection though: ERP
# tables carry no plant_id/RLS at all (see migrations/versions/
# 0001_initial_schema.py "NOTE ON TABLES WITHOUT RLS"), and the one
# ERP-adjacent table that DOES carry RLS - invoices - is exactly what the
# finance department needs to see across every plant, not filtered down
# to an empty plant_ids list. So: separate set, used only for DB engine
# selection in api/db.py, never for the plant-access gate in api/deps.py.
BYPASS_RLS_JWT_ROLES = GLOBAL_JWT_ROLES | {"dept_user"}

# The five business functions a dept_user can be scoped to. Kept here
# (not just in the migration's CHECK constraint) so api/dept_deps.py and
# seed/seed.py both import one source of truth instead of re-typing the
# list and risking drift.
DEPARTMENTS = frozenset({"finance", "procurement", "engineering", "sales", "logistics"})


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(plain, hashed)
    except ValueError:
        return False


def create_access_token(
    *, user_id: str, role: str, plant_ids: list[str], department: str | None = None
) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": user_id,
        "role": role,
        "plant_ids": plant_ids,
        "iat": now,
        "exp": now + config.JWT_EXPIRE_MINUTES * 60,
    }
    if department is not None:
        payload["department"] = department
    return jwt.encode(payload, config.JWT_SECRET, algorithm=config.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    # Raises jwt.PyJWTError (ExpiredSignatureError, InvalidTokenError, ...)
    # on any problem - caller is responsible for turning that into a 401.
    return jwt.decode(token, config.JWT_SECRET, algorithms=[config.JWT_ALGORITHM])
