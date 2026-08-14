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

from typing import AsyncIterator

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from . import config


def _role_url(role: str, password: str):
    url = make_url(config.ASYNC_DATABASE_URL)
    return url.set(username=role, password=password)


tenant_engine = create_async_engine(
    _role_url(config.PG_TENANT_ROLE, config.PG_TENANT_PASSWORD),
    future=True,
    pool_pre_ping=True,
)
global_engine = create_async_engine(
    _role_url(config.PG_GLOBAL_ROLE, config.PG_GLOBAL_PASSWORD),
    future=True,
    pool_pre_ping=True,
)


def engine_for_role(jwt_role: str):
    from .security import GLOBAL_JWT_ROLES

    return global_engine if jwt_role in GLOBAL_JWT_ROLES else tenant_engine


async def open_scoped_connection(role: str, plant_ids: list[str]) -> AsyncConnection:
    """Open a connection+transaction on the role-appropriate engine.

    For tenant_read, sets app.current_plant_ids for the duration of the
    transaction (second net for RLS-covered tables). Caller owns
    commit/rollback via the returned connection's transaction and MUST
    close the connection when done (use as an async context manager).
    """
    engine = engine_for_role(role)
    conn = await engine.connect()
    await conn.begin()
    from .security import GLOBAL_JWT_ROLES

    if role not in GLOBAL_JWT_ROLES:
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
