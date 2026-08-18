"""Async DB engines and per-request connection/session helpers.

Two role-specific async engines are used, mirroring the two Postgres
roles created by the P0 migration (migrations/README.md "Row-Level
Security" section):

  - airthra_tenant: subject to RLS. Used for tenant_read requests. As a
    second net (in addition to the explicit 403 check in api/deps.py) we
    also `SELECT set_config('app.current_plant_ids', ..., true)` at the
    start of the request's transaction, so RLS-covered tables (sensors,
    alarms, operator_events, ...) are filtered by Postgres itself too.
    This has no effect on readings/kpis, which do not carry RLS (documented
    TimescaleDB-compression deviation in migrations/README.md) - for those
    two tables the explicit API-layer 403 check is the *only* control,
    which is why that check must never be skipped or replaced by "rely on
    RLS to silently return zero rows".
  - airthra_global: BYPASSRLS. Used for global_read/global_admin requests.
"""
from __future__ import annotations

import os
from typing import AsyncIterator

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from . import config


def _role_url(role: str, password: str):
    url = make_url(config.ASYNC_DATABASE_URL)
    return url.set(username=role, password=password)


# Pool sizing is env-tunable rather than left at SQLAlchemy's defaults
# (5 + 10 overflow). Two engines exist, so the process ceiling is roughly
# 2 x (size + overflow) connections - that has to be reconciled against
# Postgres's own max_connections once the API runs more than one replica,
# at which point PgBouncer belongs in front of it. Documented in
# SHIPPING.md B3.
_POOL_SIZE = int(os.environ.get("DB_POOL_SIZE", "10"))
_POOL_MAX_OVERFLOW = int(os.environ.get("DB_POOL_MAX_OVERFLOW", "20"))
# Recycle below any upstream idle-connection timeout so a pooled
# connection is never handed out already dead.
_POOL_RECYCLE_S = int(os.environ.get("DB_POOL_RECYCLE_S", "1800"))


def _make_engine(role: str, password: str):
    return create_async_engine(
        _role_url(role, password),
        future=True,
        pool_pre_ping=True,
        pool_size=_POOL_SIZE,
        max_overflow=_POOL_MAX_OVERFLOW,
        pool_recycle=_POOL_RECYCLE_S,
    )


tenant_engine = _make_engine(config.PG_TENANT_ROLE, config.PG_TENANT_PASSWORD)
global_engine = _make_engine(config.PG_GLOBAL_ROLE, config.PG_GLOBAL_PASSWORD)


def engine_for_role(jwt_role: str):
    from .security import BYPASS_RLS_JWT_ROLES

    return global_engine if jwt_role in BYPASS_RLS_JWT_ROLES else tenant_engine


async def open_scoped_connection(role: str, plant_ids: list[str]) -> AsyncConnection:
    """Open a connection+transaction on the role-appropriate engine.

    For tenant_read, sets app.current_plant_ids for the duration of the
    transaction (second net for RLS-covered tables). Caller owns
    commit/rollback via the returned connection's transaction and MUST
    close the connection when done (use as an async context manager).
    dept_user is on the BYPASSRLS engine (see security.BYPASS_RLS_JWT_ROLES)
    so the set_config call is skipped for it too - it has no plant_ids to
    scope by, and department access is enforced entirely at the API layer
    (api/dept_deps.py), not by Postgres RLS.
    """
    engine = engine_for_role(role)
    conn = await engine.connect()
    await conn.begin()
    from .security import BYPASS_RLS_JWT_ROLES

    if role not in BYPASS_RLS_JWT_ROLES:
        await conn.execute(
            text("SELECT set_config('app.current_plant_ids', :v, true)"),
            {"v": ",".join(plant_ids)},
        )
    return conn


async def close_ok(conn: AsyncConnection) -> None:
    await conn.commit()
    await conn.close()


async def close_err(conn: AsyncConnection) -> None:
    await conn.rollback()
    await conn.close()
