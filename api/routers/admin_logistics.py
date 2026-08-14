"""P7 §5.3 logistics admin endpoints.

  GET  /admin/logistics/burn_rates  - KOH days-remaining + K2SO3 fill %,
                                       per plant.
  POST /admin/logistics/task        - Grafana unified-alerting webhook
                                       target; creates a `tasks` row.

--------------------------------------------------------------------------
Burn-rate method (documented per the task)
--------------------------------------------------------------------------
For each plant, pull `level_KOH_tank` readings (tag from seed/seed.py's
SENSORS manifest - sensor_id == tag for the seeded plants) over the
trailing BURN_RATE_WINDOW_DAYS = 7 days and fit a simple ordinary-least-
-squares line level(t) = a + b*t, t in days since the window start.
`b` (kg or %/day, here %/day since the sensor unit is '%' - see
seed/seed.py) is the drain rate. If b < 0 (tank actually draining),
days_remaining = current_level / -b. If b >= 0 (flat or refilling) we
report days_remaining = null with reason "not_draining" rather than a
meaningless negative/infinite number. Fewer than
MIN_POINTS_FOR_TREND = 3 readings in the window -> days_remaining = null,
reason "insufficient_data". This is intentionally a plain linear
regression, not a Kalman filter or anything fancier - the PRD explicitly
allows "simple linear regression or even a simple rate-of-change".

K2SO3 fill % is just the latest `level_K2SO3_tank` reading value (no
trend needed per the task).

--------------------------------------------------------------------------
Webhook mapping (documented interpretation - see task docstring)
--------------------------------------------------------------------------
The P0 schema has no dedicated "logistics task" table. `tasks` (PRD
§4.3) is the closest fit: `id, project_id, title, assignee, due, status,
blocked_by_po_id`. `project_id` is nullable (checked
migrations/versions/0001_initial_schema.py - `project_id uuid REFERENCES
projects(id) ON DELETE CASCADE`, no NOT NULL), so no placeholder project
row is needed. Each firing Grafana alert becomes one `tasks` row:
  - title: f"KOH refill needed - {plant_id}" (or the alert's
    annotations.summary if present, for a more specific message)
  - project_id: NULL
  - assignee: NULL (no logistics-role user to auto-assign to in this phase)
  - due: today + TASK_DUE_DAYS (2 - matches the "days_remaining < 2"
    trigger condition, i.e. "handle this before the tank actually runs out")
  - status: 'open'
Only alerts with status == "firing" create a task; "resolved" alerts are
acknowledged in the response but do not create anything (no task-closing
behaviour is implemented in this phase - out of scope).

Auth: Grafana contact points can't easily mint this app's user JWTs, so
this endpoint is protected by a shared secret header instead of
get_current_user/require_global - documented deviation from the rest of
/admin/*. Configure via GRAFANA_WEBHOOK_SECRET in .env; a dev default is
used if unset (same convention as the DB role dev passwords in .env.example).
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from typing import Any

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..deps import CurrentUser, db_session, get_current_user
from .admin_common import require_global

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(_ROOT, ".env"))

GRAFANA_WEBHOOK_SECRET = os.environ.get("GRAFANA_WEBHOOK_SECRET", "change_me_dev_only_grafana_webhook")

router = APIRouter(prefix="/admin", tags=["admin-logistics"])

BURN_RATE_WINDOW_DAYS = 7
MIN_POINTS_FOR_TREND = 3
TASK_DUE_DAYS = 2


def _linreg_slope(points: list[tuple[float, float]]) -> float | None:
    """OLS slope of y over x. Returns None if x has zero variance."""
    n = len(points)
    if n < 2:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    xmean = sum(xs) / n
    ymean = sum(ys) / n
    num = sum((x - xmean) * (y - ymean) for x, y in points)
    den = sum((x - xmean) ** 2 for x in xs)
    if den == 0:
        return None
    return num / den


@router.get("/logistics/burn_rates")
async def get_burn_rates(
    user: CurrentUser = Depends(get_current_user),
    conn: AsyncConnection = Depends(db_session),
):
    require_global(user)
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=BURN_RATE_WINDOW_DAYS)

    plants = (
        await conn.execute(text("SELECT plant_id, name FROM plants ORDER BY plant_id"))
    ).mappings().all()

    results = []
    for p in plants:
        pid = p["plant_id"]

        koh_rows = (
            await conn.execute(
                text(
                    """
                    SELECT ts, value FROM readings
                    WHERE plant_id = :pid AND sensor_id = 'level_KOH_tank'
                      AND ts >= :start AND value IS NOT NULL
                    ORDER BY ts
                    """
                ),
                {"pid": pid, "start": window_start},
            )
        ).mappings().all()

        k2so3_row = (
            await conn.execute(
                text(
                    """
                    SELECT ts, value FROM readings
                    WHERE plant_id = :pid AND sensor_id = 'level_K2SO3_tank' AND value IS NOT NULL
                    ORDER BY ts DESC LIMIT 1
                    """
                ),
                {"pid": pid},
            )
        ).mappings().first()

        koh_days_remaining = None
        koh_reason = None
        current_koh_level = None
        slope_pct_per_day = None

        if len(koh_rows) < MIN_POINTS_FOR_TREND:
            koh_reason = "insufficient_data"
        else:
            current_koh_level = koh_rows[-1]["value"]
            points = [
                ((r["ts"] - window_start).total_seconds() / 86400.0, r["value"])
                for r in koh_rows
            ]
            slope_pct_per_day = _linreg_slope(points)
            if slope_pct_per_day is None:
                koh_reason = "insufficient_data"
            elif slope_pct_per_day >= 0:
                koh_reason = "not_draining"
            else:
                koh_days_remaining = round(current_koh_level / -slope_pct_per_day, 2)

        results.append(
            {
                "plant_id": pid,
                "name": p["name"],
                "koh": {
                    "current_level_pct": current_koh_level,
                    "trend_pct_per_day": round(slope_pct_per_day, 4) if slope_pct_per_day is not None else None,
                    "days_remaining": koh_days_remaining,
                    "reason": koh_reason,
                    "sample_count": len(koh_rows),
                },
                "k2so3": {
                    "fill_pct": k2so3_row["value"] if k2so3_row else None,
                    "as_of": k2so3_row["ts"] if k2so3_row else None,
                },
            }
        )

    return {
        "generated_at": now,
        "window_days": BURN_RATE_WINDOW_DAYS,
        "method": "ordinary least squares linear regression of level_KOH_tank (%) vs time over the trailing window",
        "plants": results,
    }


class _GrafanaAlert(BaseModel):
    status: str | None = None
    labels: dict[str, Any] = {}
    annotations: dict[str, Any] = {}
    startsAt: str | None = None


class _GrafanaWebhookPayload(BaseModel):
    status: str | None = None
    alerts: list[_GrafanaAlert] = []


@router.post("/logistics/task", status_code=status.HTTP_201_CREATED)
async def logistics_task_webhook(
    body: _GrafanaWebhookPayload,
    x_webhook_secret: str | None = Header(default=None),
):
    if x_webhook_secret != GRAFANA_WEBHOOK_SECRET:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing or invalid X-Webhook-Secret",
        )

    from ..db import global_engine

    created = []
    skipped = []
    async with global_engine.connect() as conn:
        for alert in body.alerts:
            if alert.status != "firing":
                skipped.append({"labels": alert.labels, "status": alert.status})
                continue

            plant_id = alert.labels.get("plant_id") or alert.labels.get("plant") or "unknown"
            summary = alert.annotations.get("summary") or alert.annotations.get("description")
            title = summary or f"KOH refill needed - {plant_id}"
            due = date.today() + timedelta(days=TASK_DUE_DAYS)  # asyncpg wants a date object, not an isoformat str

            row = (
                await conn.execute(
                    text(
                        """
                        INSERT INTO tasks (id, project_id, title, assignee, due, status, blocked_by_po_id)
                        VALUES (gen_random_uuid(), NULL, :title, NULL, :due, 'open', NULL)
                        RETURNING id, title, due, status
                        """
                    ),
                    {"title": title, "due": due},
                )
            ).mappings().first()
            created.append(dict(row))
        await conn.commit()

    return {"created": created, "skipped": skipped}
