"""Plant-scoped client-facing endpoints (PRD section 5.3, client subset).

Every endpoint here takes plant_id as a path param and MUST call
require_plant_access(user, plant_id) before running any query. That is
the literal thing tests/p2_gate.py asserts on every single endpoint.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..deps import CurrentUser, db_session, get_current_user, require_plant_access
from ..schemas import EventCreate

router = APIRouter(prefix="/api/v1/{plant_id}", tags=["plant"])

# Auto-select raw vs continuous-aggregate table by requested range, per PRD:
#   <6h    -> raw readings
#   <3d    -> readings_1m
#   <30d   -> readings_15m
#   else   -> readings_1h
_RESOLUTION_TABLES = {
    "raw": "readings",
    "1m": "readings_1m",
    "15m": "readings_15m",
    "1h": "readings_1h",
}


def _auto_resolution(start: datetime, end: datetime) -> str:
    span = end - start
    if span <= timedelta(hours=6):
        return "raw"
    if span <= timedelta(days=3):
        return "1m"
    if span <= timedelta(days=30):
        return "15m"
    return "1h"


@router.get("/current")
async def get_current_readings(
    plant_id: str,
    user: CurrentUser = Depends(get_current_user),
    conn: AsyncConnection = Depends(db_session),
):
    require_plant_access(user, plant_id)
    rows = (
        await conn.execute(
            text(
                """
                SELECT DISTINCT ON (sensor_id) sensor_id, ts, value, quality_flag
                FROM readings
                WHERE plant_id = :plant_id
                ORDER BY sensor_id, ts DESC
                """
            ),
            {"plant_id": plant_id},
        )
    ).mappings().all()
    return {
        "plant_id": plant_id,
        "readings": [dict(r) for r in rows],
    }


@router.get("/history")
async def get_history(
    plant_id: str,
    start: datetime,
    end: datetime,
    sensors: str | None = Query(default=None, description="comma-separated sensor_id list"),
    resolution: str | None = Query(default=None, description="raw|1m|15m|1h, auto-selected if omitted"),
    user: CurrentUser = Depends(get_current_user),
    conn: AsyncConnection = Depends(db_session),
):
    require_plant_access(user, plant_id)

    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    if end <= start:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="end must be after start")

    res = resolution if resolution in _RESOLUTION_TABLES else _auto_resolution(start, end)
    table = _RESOLUTION_TABLES[res]  # fixed whitelist - never interpolate user input directly
    sensor_filter = {s.strip() for s in sensors.split(",") if s.strip()} if sensors else None

    if res == "raw":
        rows = (
            await conn.execute(
                text(
                    f"""
                    SELECT sensor_id, ts, value, quality_flag
                    FROM {table}
                    WHERE plant_id = :plant_id AND ts >= :start AND ts < :end
                    ORDER BY sensor_id, ts
                    """
                ),
                {"plant_id": plant_id, "start": start, "end": end},
            )
        ).mappings().all()
    else:
        rows = (
            await conn.execute(
                text(
                    f"""
                    SELECT sensor_id, bucket, avg_value, min_value, max_value, sample_count, flagged_count
                    FROM {table}
                    WHERE plant_id = :plant_id AND bucket >= :start AND bucket < :end
                    ORDER BY sensor_id, bucket
                    """
                ),
                {"plant_id": plant_id, "start": start, "end": end},
            )
        ).mappings().all()

    points = [dict(r) for r in rows]
    # Sensor filter applied in Python rather than pushed into SQL as an
    # array bind param: intentional simplification given the seeded
    # manifest is small (7 sensors/plant) - fine for P2, worth revisiting
    # with a proper ANY(:sensors) bind if manifests grow much larger.
    if sensor_filter:
        points = [p for p in points if p["sensor_id"] in sensor_filter]

    return {
        "plant_id": plant_id,
        "resolution": res,
        "start": start,
        "end": end,
        "points": points,
    }


@router.get("/kpis")
async def get_kpis(
    plant_id: str,
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    user: CurrentUser = Depends(get_current_user),
    conn: AsyncConnection = Depends(db_session),
):
    require_plant_access(user, plant_id)
    if end is None:
        end = datetime.now(timezone.utc)
    if start is None:
        start = end - timedelta(hours=24)

    rows = (
        await conn.execute(
            text(
                """
                SELECT ts, kpi_name, value, quality_flag
                FROM kpis
                WHERE plant_id = :plant_id AND ts >= :start AND ts < :end
                ORDER BY ts
                """
            ),
            {"plant_id": plant_id, "start": start, "end": end},
        )
    ).mappings().all()
    return {"plant_id": plant_id, "kpis": [dict(r) for r in rows]}


@router.post("/event", status_code=status.HTTP_201_CREATED)
async def create_event(
    plant_id: str,
    body: EventCreate,
    user: CurrentUser = Depends(get_current_user),
    conn: AsyncConnection = Depends(db_session),
):
    require_plant_access(user, plant_id)
    event_id = str(uuid.uuid4())
    row = (
        await conn.execute(
            text(
                """
                INSERT INTO operator_events (event_id, plant_id, user_id, kind, payload)
                VALUES (:event_id, :plant_id, :user_id, :kind, CAST(:payload AS jsonb))
                RETURNING event_id, plant_id, user_id, ts, kind, payload
                """
            ),
            {
                "event_id": event_id,
                "plant_id": plant_id,
                "user_id": user.user_id or None,
                "kind": body.kind,
                "payload": _to_json(body.payload),
            },
        )
    ).mappings().first()
    return dict(row)


@router.post("/alarms/{alarm_id}/ack")
async def ack_alarm(
    plant_id: str,
    alarm_id: str,
    user: CurrentUser = Depends(get_current_user),
    conn: AsyncConnection = Depends(db_session),
):
    require_plant_access(user, plant_id)

    existing = (
        await conn.execute(
            text("SELECT alarm_id FROM alarms WHERE alarm_id = :id AND plant_id = :plant_id"),
            {"id": alarm_id, "plant_id": plant_id},
        )
    ).first()
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"alarm '{alarm_id}' not found for plant '{plant_id}'",
        )

    row = (
        await conn.execute(
            text(
                """
                UPDATE alarms
                SET state = 'acked', acked_at = now(), acked_by = :user_id
                WHERE alarm_id = :id AND plant_id = :plant_id
                RETURNING alarm_id, plant_id, state, acked_at, acked_by
                """
            ),
            {"id": alarm_id, "plant_id": plant_id, "user_id": user.user_id or None},
        )
    ).mappings().first()
    return dict(row)


def _to_json(payload: dict) -> str:
    import json

    return json.dumps(payload)
