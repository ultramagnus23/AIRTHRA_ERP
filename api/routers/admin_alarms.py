"""P7 admin triage - GET /admin/alarms - cross-plant alarm listing for global roles.

Added by the frontend admin-console build (not the original P7 backend
phase): alarms_list.py's `GET /api/v1/{plant_id}/alarms` is plant-scoped
only (it gates on `require_plant_access`, which is meaningless for a
global_admin/global_read JWT - those roles carry no `plant_ids`, per
api/deps.py's CurrentUser/GLOBAL_JWT_ROLES). The admin triage queue (PRD
§5.5 "Admin") needs raised alarms across every plant at once, so this is
a new, minimal, additive endpoint: same query shape/columns as
alarms_list.py's `list_alarms`, just without the `plant_id` path param
or `require_plant_access` gate, gated instead by
`admin_common.require_global` (same gate every other /admin/* router
uses), plus a joined `plant_name` since the triage UI lists alarms across
plants and needs to label them.

Deliberately its own file (not added to alarms_list.py or any existing
admin_*.py router) to avoid touching files owned by other concurrent
phases/agents.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..deps import CurrentUser, db_session, get_current_user
from .admin_common import require_global

router = APIRouter(prefix="/admin", tags=["admin-alarms"])


@router.get("/alarms")
async def list_all_alarms(
    state: str | None = Query(
        default="raised", description="filter: raised|acked|cleared|escalated; pass empty string for all"
    ),
    plant_id: str | None = Query(default=None),
    limit: int = Query(default=200, le=1000),
    user: CurrentUser = Depends(get_current_user),
    conn: AsyncConnection = Depends(db_session),
):
    require_global(user)

    clauses = []
    params: dict = {"limit": limit}
    if state:
        clauses.append("a.state = :state")
        params["state"] = state
    if plant_id:
        clauses.append("a.plant_id = :plant_id")
        params["plant_id"] = plant_id
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    rows = (
        await conn.execute(
            text(
                f"""
                SELECT a.alarm_id, a.plant_id, p.name AS plant_name, a.rule_id, a.severity,
                       a.state, a.raised_at, a.acked_at, a.acked_by, a.cleared_at,
                       a.diagnosis, a.suggested_part
                FROM alarms a
                JOIN plants p ON p.plant_id = a.plant_id
                {where}
                ORDER BY a.raised_at DESC
                LIMIT :limit
                """
            ),
            params,
        )
    ).mappings().all()

    return {"state_filter": state, "alarms": [dict(r) for r in rows]}
