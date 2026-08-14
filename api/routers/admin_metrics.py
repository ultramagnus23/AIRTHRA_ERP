"""P7 §5.3 GET /admin/metrics - cross-tenant metric aggregation.

Intentionally NOT plant-scoped (no require_plant_access anywhere in this
file) - that is the whole point of it being a global/admin endpoint: a
global_admin/global_read user can compare a named metric across every
plant at once, which a tenant_read user could never do even in
principle (they only have plant_ids for their own plant(s)).

`metric` may be either:
  - a `kpis.kpi_name` (e.g. so2_removal_efficiency, mass_balance_closure)
  - a `readings.sensor_id`/tag (e.g. SO2_in, level_KOH_tank)

`source` picks which table to read from; default "auto" tries kpis first
and falls back to readings if the metric name isn't a known kpi_name for
any plant in the period.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..deps import CurrentUser, db_session, get_current_user
from .admin_common import require_global

router = APIRouter(prefix="/admin", tags=["admin-metrics"])

_PERIOD_RE = re.compile(r"^(\d+)([hd])$")


def _parse_period(period: str) -> timedelta:
    m = _PERIOD_RE.match(period.strip())
    if not m:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="period must look like '24h', '7d', '30d' (integer + h|d)",
        )
    n, unit = int(m.group(1)), m.group(2)
    return timedelta(hours=n) if unit == "h" else timedelta(days=n)


@router.get("/metrics")
async def get_metrics(
    metric: str = Query(..., description="kpis.kpi_name or readings.sensor_id"),
    group_by: str = Query(default="plant_id", description="only 'plant_id' is supported"),
    period: str = Query(default="24h", description="e.g. 24h, 7d, 30d"),
    source: str = Query(default="auto", description="auto|kpi|reading"),
    user: CurrentUser = Depends(get_current_user),
    conn: AsyncConnection = Depends(db_session),
):
    require_global(user)
    if group_by != "plant_id":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="group_by='plant_id' is the only supported grouping in this phase",
        )
    span = _parse_period(period)
    end = datetime.now(timezone.utc)
    start = end - span

    async def _from_kpis():
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT plant_id,
                           avg(value) AS avg_value,
                           min(value) AS min_value,
                           max(value) AS max_value,
                           count(*) AS sample_count,
                           count(*) FILTER (WHERE quality_flag <> 'good') AS non_good_count
                    FROM kpis
                    WHERE kpi_name = :metric AND ts >= :start AND ts < :end
                    GROUP BY plant_id
                    ORDER BY plant_id
                    """
                ),
                {"metric": metric, "start": start, "end": end},
            )
        ).mappings().all()
        return rows

    async def _from_readings():
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT plant_id,
                           avg(value) AS avg_value,
                           min(value) AS min_value,
                           max(value) AS max_value,
                           count(*) AS sample_count,
                           count(*) FILTER (WHERE quality_flag <> 'good') AS non_good_count
                    FROM readings
                    WHERE sensor_id = :metric AND ts >= :start AND ts < :end
                    GROUP BY plant_id
                    ORDER BY plant_id
                    """
                ),
                {"metric": metric, "start": start, "end": end},
            )
        ).mappings().all()
        return rows

    used_source = source
    if source == "kpi":
        rows = await _from_kpis()
    elif source == "reading":
        rows = await _from_readings()
    else:  # auto
        rows = await _from_kpis()
        used_source = "kpi"
        if not rows:
            rows = await _from_readings()
            used_source = "reading"

    return {
        "metric": metric,
        "source": used_source,
        "group_by": group_by,
        "period": period,
        "start": start,
        "end": end,
        "results": [
            {
                "plant_id": r["plant_id"],
                "avg": r["avg_value"],
                "min": r["min_value"],
                "max": r["max_value"],
                "sample_count": r["sample_count"],
                "non_good_pct": round(100.0 * r["non_good_count"] / r["sample_count"], 2)
                if r["sample_count"]
                else None,
            }
            for r in rows
        ],
    }
