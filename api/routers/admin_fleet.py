"""P7 §5.3 GET /admin/fleet - cross-tenant fleet health.

Global-role only (never tenant_read - see admin_common.require_global).
Reads `alarms`/`alarm_rules` (owned by the concurrent P3 alarm-engine
phase) but never writes to them, and must not crash if those tables are
still empty (alarm engine not landed / not yet fired anything for a
plant) - in that case the plant simply can't be red-via-alarm, it falls
back to the reading-freshness/data-quality checks below.

--------------------------------------------------------------------------
Health color definition (documented thresholds - our call per the task)
--------------------------------------------------------------------------
For each plant, in order of precedence:

  1. "gray" (unknown / no data yet): the plant has never received a single
     `readings` row. Not a fault - could just be pre-commissioning. Shown
     explicitly rather than defaulting to green (which would falsely imply
     "healthy") or red (which would falsely imply "broken").
  2. "red" if EITHER:
       a) there is at least one row in `alarms` with state = 'raised' AND
          severity = 'critical' for the plant, OR
       b) the plant's most recent `readings` row (any sensor) is older
          than OFFLINE_THRESHOLD_S = 600 seconds (10 minutes) - i.e. the
          plant has stopped reporting ("offline").
  3. "yellow" if EITHER:
       a) there is at least one row in `alarms` with state = 'raised' AND
          severity IN ('warning', 'info') ("predicted issue"), OR
       b) over the trailing DEGRADED_WINDOW_S = 3600 seconds (1 hour) of
          readings, the share of rows with quality_flag != 'good' exceeds
          DEGRADED_FLAG_PCT = 20% ("degraded data quality").
  4. "green" otherwise.

These thresholds are deliberately simple/conservative and configurable
via the module-level constants below (not exposed as query params in this
phase - PRD just asks for "clear, documented thresholds").
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..deps import CurrentUser, db_session, get_current_user
from .admin_common import require_global

router = APIRouter(prefix="/admin", tags=["admin-fleet"])

OFFLINE_THRESHOLD_S = 600
DEGRADED_WINDOW_S = 3600
DEGRADED_FLAG_PCT = 20.0


@router.get("/fleet")
async def get_fleet(
    user: CurrentUser = Depends(get_current_user),
    conn: AsyncConnection = Depends(db_session),
):
    require_global(user)
    now = datetime.now(timezone.utc)
    degraded_since = now - timedelta(seconds=DEGRADED_WINDOW_S)

    plants = (
        await conn.execute(text("SELECT plant_id, name FROM plants ORDER BY plant_id"))
    ).mappings().all()

    latest_readings = {
        r["plant_id"]: r["last_ts"]
        for r in (
            await conn.execute(
                text("SELECT plant_id, max(ts) AS last_ts FROM readings GROUP BY plant_id")
            )
        ).mappings().all()
    }

    quality = {
        r["plant_id"]: r
        for r in (
            await conn.execute(
                text(
                    """
                    SELECT plant_id,
                           count(*) AS total,
                           count(*) FILTER (WHERE quality_flag <> 'good') AS non_good
                    FROM readings
                    WHERE ts >= :since
                    GROUP BY plant_id
                    """
                ),
                {"since": degraded_since},
            )
        ).mappings().all()
    }

    alarm_rows = (
        await conn.execute(
            text(
                """
                SELECT plant_id, severity, count(*) AS n
                FROM alarms
                WHERE state = 'raised'
                GROUP BY plant_id, severity
                """
            )
        )
    ).mappings().all()
    critical_alarm_plants: set[str] = set()
    warning_alarm_plants: set[str] = set()
    for r in alarm_rows:
        if r["severity"] == "critical":
            critical_alarm_plants.add(r["plant_id"])
        elif r["severity"] in ("warning", "info"):
            warning_alarm_plants.add(r["plant_id"])

    fleet = []
    for p in plants:
        pid = p["plant_id"]
        last_ts = latest_readings.get(pid)

        if last_ts is None:
            color, reasons = "gray", ["no readings received yet"]
        else:
            reasons = []
            offline = (now - last_ts).total_seconds() > OFFLINE_THRESHOLD_S
            q = quality.get(pid)
            flagged_pct = 0.0
            if q and q["total"]:
                flagged_pct = 100.0 * q["non_good"] / q["total"]

            if pid in critical_alarm_plants:
                reasons.append("active critical alarm")
            if offline:
                reasons.append(
                    f"offline (last reading {int((now - last_ts).total_seconds())}s ago, "
                    f"threshold {OFFLINE_THRESHOLD_S}s)"
                )

            if reasons:
                color = "red"
            else:
                if pid in warning_alarm_plants:
                    reasons.append("active warning/info alarm (predicted issue)")
                if flagged_pct > DEGRADED_FLAG_PCT:
                    reasons.append(
                        f"degraded data quality ({flagged_pct:.1f}% non-good readings "
                        f"in last {DEGRADED_WINDOW_S // 60}min, threshold {DEGRADED_FLAG_PCT}%)"
                    )
                color = "yellow" if reasons else "green"

        fleet.append(
            {
                "plant_id": pid,
                "name": p["name"],
                "color": color,
                "reasons": reasons,
                "last_reading_ts": last_ts,
                "flagged_pct_last_hour": round(
                    100.0 * quality[pid]["non_good"] / quality[pid]["total"], 2
                )
                if quality.get(pid) and quality[pid]["total"]
                else None,
            }
        )

    return {
        "generated_at": now,
        "thresholds": {
            "offline_threshold_s": OFFLINE_THRESHOLD_S,
            "degraded_window_s": DEGRADED_WINDOW_S,
            "degraded_flag_pct": DEGRADED_FLAG_PCT,
        },
        "fleet": fleet,
    }
