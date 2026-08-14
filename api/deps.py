"""Auth dependency + tenant-scoping gate.

This module is the actual security boundary the P2 gate script
(tests/p2_gate.py) exercises: every plant-scoped endpoint must call
`require_plant_access(user, plant_id)` before touching the database, and
that check must raise an explicit HTTP 403 - never a 404, never a
silently-empty result - when a tenant_read JWT's plant_ids don't include
the requested plant_id.
"""
from __future__ import annotations

import jwt as pyjwt
from fastapi import Depends, Header, HTTPException, status

from . import security
from .db import close_err, close_ok, open_scoped_connection


class CurrentUser:
    __slots__ = ("user_id", "role", "plant_ids")

    def __init__(self, user_id: str, role: str, plant_ids: list[str]):
        self.user_id = user_id
        self.role = role
        self.plant_ids = plant_ids

    @property
    def is_global(self) -> bool:
        return self.role in security.GLOBAL_JWT_ROLES


def decode_user(token: str) -> CurrentUser:
    try:
        payload = security.decode_access_token(token)
    except pyjwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"invalid or expired token: {exc}",
        ) from exc
    return CurrentUser(
        user_id=payload.get("sub", ""),
        role=payload.get("role", ""),
        plant_ids=payload.get("plant_ids", []) or [],
    )


async def get_current_user(authorization: str | None = Header(default=None)) -> CurrentUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token (Authorization: Bearer <jwt>)",
        )
    token = authorization.split(" ", 1)[1].strip()
    return decode_user(token)


def require_plant_access(user: CurrentUser, plant_id: str) -> None:
    """The tenant-scoping gate. Explicit 403, never 404/empty-list."""
    if user.is_global:
        return
    if plant_id not in user.plant_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"user is not authorized for plant '{plant_id}'",
        )


async def db_session(user: CurrentUser = Depends(get_current_user)):
    """Per-request DB connection, opened on the role-appropriate engine
    with app.current_plant_ids set (tenant_read only) as the RLS second
    net. Does NOT itself enforce plant_id scoping for the requested
    plant_id - endpoints must still call require_plant_access first for
    readings/kpis (which have no RLS at all)."""
    conn = await open_scoped_connection(user.role, user.plant_ids)
    try:
        yield conn
    except Exception:
        await close_err(conn)
        raise
    else:
        await close_ok(conn)
