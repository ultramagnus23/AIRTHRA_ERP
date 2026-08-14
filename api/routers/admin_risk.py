"""P7 §5.3 GET /admin/risk_scores - transparent weighted per-plant risk score.

The PRD requires the weights themselves be "published in the UI" - for
this backend phase that means the weights (and every raw component that
fed the formula) MUST be present in the API response payload itself, not
just hardcoded invisibly server-side. See WEIGHTS below and the
"weights"/"components" keys in the response.

--------------------------------------------------------------------------
Components (all normalized to a 0-100 "badness" scale, higher = worse)
--------------------------------------------------------------------------
  data_quality   : 100 - (good `readings` rows / total rows) * 100, over
                    the period. Straightforward reliability signal.
  ack_latency    : avg(alarms.acked_at - alarms.raised_at) in minutes for
                    acked alarms raised in the period, linearly capped at
                    ACK_LATENCY_CAP_MIN = 60min -> 100 badness (an alarm
                    sitting unacked for an hour-plus is treated as
                    maximally bad; anything at/above the cap clamps to
                    100 rather than growing unbounded).
  maintenance    : adherence proxy, since the PRD has no fixed maintenance
                    schedule in the P0 schema to compare against: we
                    expect at least one `operator_events` row with
                    kind='maintenance' every MAINTENANCE_EXPECTED_DAYS = 30
                    days. badness = 100 * max(0, 1 - actual_count/expected_count).
                    Documented as a simple proxy, not a real CMMS cadence
                    model.
  flag_pct       : 100 * (non-good `readings` rows / total rows) over the
                    period. This is deliberately the same underlying ratio
                    as data_quality's complement (not an error - the PRD
                    lists "data-quality %" and "flag %" as two distinct
                    weighted factors; we honor that literally rather than
                    silently merging them, and document the redundancy
                    here rather than hiding it).
  spike_freq     : 100 * (readings rows with quality_flag = 'out_of_range'
                    / total rows) over the period - "current-spike
                    frequency" proxy, since electrical/process spikes in
                    this data model show up as out-of-range flagged values.

risk_score = sum(weight[c] * badness[c] for c in components), weights sum
to 1.0, so risk_score is itself 0-100 (higher = riskier plant).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..deps import CurrentUser, db_session, get_current_user
from .admin_common import require_global

router = APIRouter(prefix="/admin", tags=["admin-risk"])

WEIGHTS = {
    "data_quality": 0.30,
    "ack_latency": 0.20,
    "maintenance": 0.20,
    "flag_pct": 0.15,
    "spike_freq": 0.15,
}
assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9

ACK_LATENCY_CAP_MIN = 60.0
MAINTENANCE_EXPECTED_DAYS = 30


@router.get("/risk_scores")
async def get_risk_scores(
    period_days: int = Query(default=30, ge=1, le=365),
    user: CurrentUser = Depends(get_current_user),
    conn: AsyncConnection = Depends(db_session),
):
    require_global(user)
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=period_days)

    plants = (
        await conn.execute(text("SELECT plant_id, name FROM plants ORDER BY plant_id"))
    ).mappings().all()

    quality = {
        r["plant_id"]: r
        for r in (
            await conn.execute(
                text(
                    """
                    SELECT plant_id,
                           count(*) AS total,
                           count(*) FILTER (WHERE quality_flag <> 'good') AS non_good,
                           count(*) FILTER (WHERE quality_flag = 'out_of_range') AS spikes
                    FROM readings
                    WHERE ts >= :start
                    GROUP BY plant_id
                    """
                ),
                {"start": start},
            )
        ).mappings().all()
    }

    ack_latency = {
        r["plant_id"]: r["avg_minutes"]
        for r in (
            await conn.execute(
                text(
                    """
                    SELECT plant_id, avg(extract(epoch FROM (acked_at - raised_at)) / 60.0) AS avg_minutes
                    FROM alarms
                    WHERE raised_at >= :start AND acked_at IS NOT NULL
                    GROUP BY plant_id
                    """
                ),
                {"start": start},
            )
        ).mappings().all()
    }

    maintenance_counts = {
        r["plant_id"]: r["n"]
        for r in (
            await conn.execute(
                text(
                    """
                    SELECT plant_id, count(*) AS n
                    FROM operator_events
                    WHERE kind = 'maintenance' AND ts >= :start
                    GROUP BY plant_id
                    """
                ),
                {"start": start},
            )
        ).mappings().all()
    }
    expected_maintenance = max(period_days / MAINTENANCE_EXPECTED_DAYS, 1e-9)

    results = []
    for p in plants:
        pid = p["plant_id"]
        q = quality.get(pid)
        total = q["total"] if q else 0

        data_quality_badness = 100.0 * q["non_good"] / total if total else 0.0
        flag_pct_badness = data_quality_badness  # documented as intentionally the same ratio, see module docstring
        spike_badness = 100.0 * q["spikes"] / total if total else 0.0

        avg_ack_min = ack_latency.get(pid)
        ack_badness = (
            min(100.0, 100.0 * avg_ack_min / ACK_LATENCY_CAP_MIN) if avg_ack_min is not None else 0.0
        )

        actual_maintenance = maintenance_counts.get(pid, 0)
        adherence_pct = min(100.0, 100.0 * actual_maintenance / expected_maintenance)
        maintenance_badness = 100.0 - adherence_pct

        components = {
            "data_quality": round(data_quality_badness, 2),
            "ack_latency": round(ack_badness, 2),
            "maintenance": round(maintenance_badness, 2),
            "flag_pct": round(flag_pct_badness, 2),
            "spike_freq": round(spike_badness, 2),
        }
        risk_score = round(sum(WEIGHTS[k] * components[k] for k in WEIGHTS), 2)

        results.append(
            {
                "plant_id": pid,
                "name": p["name"],
                "risk_score": risk_score,
                "components": components,
                "raw": {
                    "readings_total": total,
                    "readings_non_good": q["non_good"] if q else 0,
                    "avg_ack_latency_min": round(avg_ack_min, 2) if avg_ack_min is not None else None,
                    "maintenance_events": actual_maintenance,
                    "maintenance_expected": round(expected_maintenance, 2),
                },
            }
        )

    return {
        "generated_at": now,
        "period_days": period_days,
        "weights": WEIGHTS,
        "notes": (
            "risk_score is 0-100, higher = riskier. Each component is a 0-100 "
            "'badness' score (higher = worse); risk_score = sum(weight * badness). "
            "flag_pct is intentionally the same underlying ratio as data_quality's "
            "complement - see module docstring."
        ),
        "plants": results,
    }
