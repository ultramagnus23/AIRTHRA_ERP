"""P6: logistics trip tracking.

Trip creation ("start") is a normal JWT-authenticated dispatcher action.
Pings and stop are field-device actions: the vehicle/driver's device has no
user JWT, so they're authenticated by a random per-trip token generated at
creation time (migrations/versions/0004_trip_token.py added `trips.token`
for this - see that file for the coordination note on chaining after
0003). The token is returned exactly once, in the create-trip response.

Token-authenticated endpoints intentionally bypass the JWT/db_session
dependency chain (there is no user to scope RLS by) and instead go straight
to the BYPASSRLS global engine after verifying the token server-side -
equivalent in spirit to how an edge device authenticates to MQTT with its
own credential rather than a user JWT (see docker/mosquitto).
"""
from __future__ import annotations

import secrets
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from .. import db
from ..deps import CurrentUser, db_session, get_current_user, require_plant_access


def _require_dispatch_access(user: CurrentUser, plant_id: str) -> None:
    """Trips aren't scoped to one plant's tenant the way readings/alarms
    are - a logistics dept_user needs to dispatch to any plant, same as a
    global user. api/deps.py's require_plant_access itself stays
    untouched (it's the P2 gate's own security boundary, shared with
    other phases); this just adds one more allowed path in front of it."""
    if user.role == "dept_user" and user.department == "logistics":
        return
    require_plant_access(user, plant_id)

router = APIRouter(prefix="/logistics", tags=["logistics"])


class TripCreate(BaseModel):
    vehicle_no: str
    driver: str | None = None
    phone: str | None = None
    purpose: Literal["koh_delivery", "k2so3_pickup", "dispatch"]
    origin: str | None = None
    dest_plant_id: str | None = None
    eway_bill_no: str | None = None


@router.post("/trips", status_code=status.HTTP_201_CREATED)
async def start_trip(
    body: TripCreate,
    user: CurrentUser = Depends(get_current_user),
    conn: AsyncConnection = Depends(db_session),
):
    if body.dest_plant_id is not None:
        _require_dispatch_access(user, body.dest_plant_id)

    trip_id = str(uuid.uuid4())
    token = secrets.token_urlsafe(32)
    row = (
        await conn.execute(
            text(
                """
                INSERT INTO trips (id, vehicle_no, driver, phone, purpose, origin,
                                    dest_plant_id, eway_bill_no, status, started, token)
                VALUES (:id, :vehicle_no, :driver, :phone, :purpose, :origin,
                        :dest_plant_id, :eway_bill_no, 'in_transit', now(), :token)
                RETURNING id, vehicle_no, driver, phone, purpose, origin, dest_plant_id,
                          eway_bill_no, status, started, completed
                """
            ),
            {
                "id": trip_id,
                "vehicle_no": body.vehicle_no,
                "driver": body.driver,
                "phone": body.phone,
                "purpose": body.purpose,
                "origin": body.origin,
                "dest_plant_id": body.dest_plant_id,
                "eway_bill_no": body.eway_bill_no,
                "token": token,
            },
        )
    ).mappings().first()
    result = dict(row)
    # token is returned exactly once - not retrievable via any GET endpoint.
    result["token"] = token
    return result


@router.get("/trips")
async def list_trips(
    status_filter: str | None = Query(default=None, alias="status"),
    dest_plant_id: str | None = Query(default=None),
    user: CurrentUser = Depends(get_current_user),
    conn: AsyncConnection = Depends(db_session),
):
    if dest_plant_id is not None:
        _require_dispatch_access(user, dest_plant_id)
    rows = (
        await conn.execute(
            text(
                """
                SELECT id, vehicle_no, driver, phone, purpose, origin, dest_plant_id,
                       eway_bill_no, status, started, completed
                FROM trips
                WHERE (CAST(:status AS text) IS NULL OR status = :status)
                  AND (CAST(:dest_plant_id AS text) IS NULL OR dest_plant_id = :dest_plant_id)
                ORDER BY started DESC NULLS LAST
                """
            ),
            {"status": status_filter, "dest_plant_id": dest_plant_id},
        )
    ).mappings().all()
    return {"trips": [dict(r) for r in rows]}


class PingIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    speed: float | None = None


async def _verify_trip_token(trip_id: str, token: str | None) -> None:
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing X-Trip-Token header",
        )
    async with db.global_engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT token, status FROM trips WHERE id = :id"),
                {"id": trip_id},
            )
        ).first()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"trip '{trip_id}' not found")
        if not secrets.compare_digest(row[0] or "", token):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid trip token")


@router.post("/trips/{trip_id}/ping", status_code=status.HTTP_201_CREATED)
async def ping_trip(
    trip_id: str,
    body: PingIn,
    x_trip_token: str | None = Header(default=None),
):
    await _verify_trip_token(trip_id, x_trip_token)
    async with db.global_engine.begin() as conn:
        row = (
            await conn.execute(
                text(
                    """
                    INSERT INTO trip_pings (trip_id, ts, lat, lon, speed)
                    VALUES (:trip_id, now(), :lat, :lon, :speed)
                    RETURNING trip_id, ts, lat, lon, speed
                    """
                ),
                {"trip_id": trip_id, "lat": body.lat, "lon": body.lon, "speed": body.speed},
            )
        ).mappings().first()
    return dict(row)


@router.post("/trips/{trip_id}/stop")
async def stop_trip(
    trip_id: str,
    x_trip_token: str | None = Header(default=None),
):
    await _verify_trip_token(trip_id, x_trip_token)
    async with db.global_engine.begin() as conn:
        row = (
            await conn.execute(
                text(
                    """
                    UPDATE trips SET status = 'completed', completed = now()
                    WHERE id = :id
                    RETURNING id, vehicle_no, status, started, completed
                    """
                ),
                {"id": trip_id},
            )
        ).mappings().first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"trip '{trip_id}' not found")
    return dict(row)


@router.get("/trips/{trip_id}/pings")
async def get_trip_pings(
    trip_id: str,
    user: CurrentUser = Depends(get_current_user),
    conn: AsyncConnection = Depends(db_session),
):
    trip = (
        await conn.execute(text("SELECT dest_plant_id FROM trips WHERE id = :id"), {"id": trip_id})
    ).first()
    if trip is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"trip '{trip_id}' not found")
    if trip[0] is not None:
        _require_dispatch_access(user, trip[0])
    rows = (
        await conn.execute(
            text("SELECT trip_id, ts, lat, lon, speed FROM trip_pings WHERE trip_id = :id ORDER BY ts"),
            {"id": trip_id},
        )
    ).mappings().all()
    return {"trip_id": trip_id, "pings": [dict(r) for r in rows]}
