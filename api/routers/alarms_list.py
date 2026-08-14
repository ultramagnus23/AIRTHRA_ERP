"""GET /api/v1/{plant_id}/alarms - read-only alarm list for the client dashboard.

Added alongside the frontend build: the API only shipped
POST /api/v1/{plant_id}/alarms/{alarm_id}/ack (see plant.py) - there was no
way for a client to see what alarms exist in the first place. This is a
small, additive read endpoint using the exact same auth pattern as every
other endpoint in plant.py (require_plant_access gate first, then query).
Deliberately kept in its own file rather than added to plant.py per the
instruction that produced it - avoids touching a file the P2 gate script
(tests/p2_gate.py) already exercises endpoint-by-endpoint.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..deps import CurrentUser, db_session, get_current_user, require_plant_access

router = APIRouter(prefix="/api/v1/{plant_id}", tags=["plant"])


@router.get("/alarms")
async def list_alarms(
    plant_id: str,
    state: str | None = Query(default=None, description="filter: raised|acked|cleared|escalated"),
    limit: int = Query(default=100, le=500),
    user: CurrentUser = Depends(get_current_user),
    conn: AsyncConnection = Depends(db_session),
):
    require_plant_access(user, plant_id)

    if state:
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT alarm_id, plant_id, rule_id, severity, state, raised_at,
                           acked_at, acked_by, cleared_at, diagnosis, suggested_part
                    FROM alarms
                    WHERE plant_id = :plant_id AND state = :state
                    ORDER BY raised_at DESC
                    LIMIT :limit
                    """
                ),
                {"plant_id": plant_id, "state": state, "limit": limit},
            )
        ).mappings().all()
    else:
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT alarm_id, plant_id, rule_id, severity, state, raised_at,
                           acked_at, acked_by, cleared_at, diagnosis, suggested_part
                    FROM alarms
                    WHERE plant_id = :plant_id
                    ORDER BY raised_at DESC
                    LIMIT :limit
                    """
                ),
                {"plant_id": plant_id, "limit": limit},
            )
        ).mappings().all()

    return {"plant_id": plant_id, "alarms": [dict(r) for r in rows]}
