"""Password hashing and JWT issuing/verification.

JWT role taxonomy (deliberately simplified from the DB's `users.role`
CHECK constraint, which is `global_admin | global_read | plant_admin |
plant_operator | plant_viewer` - see migrations/versions/0001_initial_schema.py):
the P2 client API only cares about three access levels, so the three
plant-scoped DB roles all collapse to a single JWT role `tenant_read`,
and the two global DB roles map 1:1.
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
}

GLOBAL_JWT_ROLES = {"global_admin", "global_read"}


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(plain, hashed)
    except ValueError:
        return False


def create_access_token(*, user_id: str, role: str, plant_ids: list[str]) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": user_id,
        "role": role,
        "plant_ids": plant_ids,
        "iat": now,
        "exp": now + config.JWT_EXPIRE_MINUTES * 60,
    }
    return jwt.encode(payload, config.JWT_SECRET, algorithm=config.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    # Raises jwt.PyJWTError (ExpiredSignatureError, InvalidTokenError, ...)
    # on any problem - caller is responsible for turning that into a 401.
    return jwt.decode(token, config.JWT_SECRET, algorithms=[config.JWT_ALGORITHM])
