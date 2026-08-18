#!/usr/bin/env python
"""P2 KPI worker.

Standalone scheduled process (every 60s by default) that computes derived
tracks into the `kpis` table from the latest available `readings` rows per
plant:

  - so2_removal_efficiency (%): (SO2_in - SO2_out) / SO2_in * 100, from the
    latest SO2_in/SO2_out readings if both sensors exist in the plant's
    manifest and SO2_in is non-zero. Skipped (no-op) if either sensor is
    missing/has no readings yet - this is expected while P1's ingest path
    is still catching up or hasn't started.

  - mass_balance_closure (%): an intentionally simplified proxy metric
    (no true stoichiometric SO2 -> K2SO3 conversion model is specified for
    P2), computed from the two reagent tank level sensors in the seeded
    manifest: how closely "KOH consumed so far" (100 - level_KOH_tank)
    tracks "K2SO3 accumulated so far" (level_K2SO3_tank), on the
    assumption the two tanks are sized so 1:1 draining/filling roughly
    corresponds to a balanced reaction. This is a placeholder pending a
    real process-engineering model; documented here rather than presented
    as a precise chemistry calculation.

Both KPIs carry quality_flag = worst-of their input readings' flags.
readings.quality_flag's CHECK enum was widened by P1's
migrations/versions/0003_quality_flag_fidelity.py from the original P0
4-value set to the PRD's 5-value vocabulary: good, comm_error,
out_of_range, frozen, imputed (0-4). "Worst of" uses the fixed severity
order comm_error > out_of_range > frozen > imputed > good - PRD doesn't
prescribe a severity ordering between the four non-good flags, so this
picks the most operationally concerning first (no data at all, then
out-of-calibration, then stale-but-present, then a filled-in estimate);
any non-good input flag makes the derived KPI non-good.

Idempotent writes: kpis' PK is (plant_id, kpi_name, ts) - INSERT ... ON
CONFLICT (plant_id, kpi_name, ts) DO UPDATE.

Never crashes on missing/sparse data: each plant's computation is wrapped
so one plant's/metric's failure doesn't take down the loop or skip other
plants.

Usage:
    .venv/Scripts/python.exe workers/kpi_worker.py [--once]

Reads DATABASE_URL from .env (repo root), same as seed/seed.py and
migrations/env.py. Uses the plain superuser DSN (not the RLS-scoped
tenant/global roles) since this is an internal, cross-plant batch job, not
a per-user request - equivalent in trust level to seed/seed.py and
tests/p0_gate.py's admin_engine.
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT, ".env"))

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL is not set (check .env)", file=sys.stderr)
    sys.exit(1)

POLL_INTERVAL_S = int(os.environ.get("KPI_WORKER_INTERVAL_S", "60"))

# Only consider readings fresh enough to be meaningful "current state" -
# stale/no readings simply means the KPI is skipped this cycle.
FRESHNESS_WINDOW_S = int(os.environ.get("KPI_WORKER_FRESHNESS_S", "600"))

_FLAG_RANK = {"good": 0, "imputed": 1, "frozen": 2, "out_of_range": 3, "comm_error": 4}


def _worst_flag(flags: list[str]) -> str:
    return max(flags, key=lambda f: _FLAG_RANK.get(f, 3))


def load_latest_readings(conn: Connection, plant_ids: list[str]) -> dict[tuple[str, str], dict]:
    """Newest reading per (plant, sensor) for the whole fleet, in ONE query.

    Previously this was a per-sensor query inside compute_for_plant, i.e.
    plants x sensors round trips per cycle - ~700 at 100 plants. DISTINCT
    ON is Postgres's native "latest row per group" and lets this stay a
    single query regardless of fleet size. Same change as
    workers/alarm_engine.py's FleetSnapshot, for the same reason.
    """
    if not plant_ids:
        return {}
    rows = conn.execute(
        text(
            """
            SELECT DISTINCT ON (plant_id, sensor_id)
                   plant_id, sensor_id, ts, value, quality_flag
            FROM readings
            WHERE plant_id = ANY(:p)
            ORDER BY plant_id, sensor_id, ts DESC
            """
        ),
        {"p": plant_ids},
    ).mappings()
    return {(r["plant_id"], r["sensor_id"]): dict(r) for r in rows}


def _latest_reading(latest: dict, plant_id: str, sensor_id: str, now: datetime):
    """Freshness gate against the pre-loaded snapshot. A reading older than
    FRESHNESS_WINDOW_S is treated as absent rather than used - a stale
    value must never silently become a current KPI."""
    row = latest.get((plant_id, sensor_id))
    if row is None:
        return None
    if (now - row["ts"]).total_seconds() > FRESHNESS_WINDOW_S:
        return None
    return row


def _upsert_kpi(conn: Connection, ts: datetime, plant_id: str, kpi_name: str, value: float, quality_flag: str) -> None:
    conn.execute(
        text(
            """
            INSERT INTO kpis (ts, plant_id, kpi_name, value, quality_flag)
            VALUES (:ts, :plant_id, :kpi_name, :value, :quality_flag)
            ON CONFLICT (plant_id, kpi_name, ts) DO UPDATE SET
                value = EXCLUDED.value,
                quality_flag = EXCLUDED.quality_flag
            """
        ),
        {"ts": ts, "plant_id": plant_id, "kpi_name": kpi_name, "value": value, "quality_flag": quality_flag},
    )


def compute_for_plant(conn: Connection, plant_id: str, latest: dict) -> list[str]:
    """Returns list of kpi_names actually written this cycle (for logging)."""
    written: list[str] = []
    now = datetime.now(timezone.utc)

    so2_in = _latest_reading(latest, plant_id, "SO2_in", now)
    so2_out = _latest_reading(latest, plant_id, "SO2_out", now)
    if so2_in is not None and so2_out is not None and so2_in["value"] not in (None, 0):
        efficiency = (so2_in["value"] - so2_out["value"]) / so2_in["value"] * 100.0
        flag = _worst_flag([so2_in["quality_flag"], so2_out["quality_flag"]])
        _upsert_kpi(conn, now, plant_id, "so2_removal_efficiency", efficiency, flag)
        written.append("so2_removal_efficiency")

    koh = _latest_reading(latest, plant_id, "level_KOH_tank", now)
    k2so3 = _latest_reading(latest, plant_id, "level_K2SO3_tank", now)
    if koh is not None and k2so3 is not None and koh["value"] is not None and k2so3["value"] is not None:
        consumed_koh_pct = 100.0 - koh["value"]
        produced_k2so3_pct = k2so3["value"]
        closure = 100.0 - abs(consumed_koh_pct - produced_k2so3_pct)
        flag = _worst_flag([koh["quality_flag"], k2so3["quality_flag"]])
        _upsert_kpi(conn, now, plant_id, "mass_balance_closure", closure, flag)
        written.append("mass_balance_closure")

    return written


def run_once(engine) -> None:
    with engine.begin() as conn:
        plant_ids = [r[0] for r in conn.execute(text("SELECT plant_id FROM plants ORDER BY plant_id")).fetchall()]
        # One fleet-wide read per cycle instead of one per (plant, sensor).
        latest = load_latest_readings(conn, plant_ids)

    for plant_id in plant_ids:
        try:
            with engine.begin() as conn:
                written = compute_for_plant(conn, plant_id, latest)
            if written:
                print(f"[kpi_worker] {plant_id}: wrote {', '.join(written)}")
        except Exception as exc:  # never let one plant's failure kill the loop
            print(f"[kpi_worker] ERROR computing KPIs for {plant_id}: {exc}", file=sys.stderr)


def main() -> None:
    once = "--once" in sys.argv
    engine = create_engine(DATABASE_URL, future=True)
    print(f"[kpi_worker] starting (interval={POLL_INTERVAL_S}s, once={once})")
    if once:
        run_once(engine)
        return
    while True:
        run_once(engine)
        time.sleep(POLL_INTERVAL_S)


if __name__ == "__main__":
    main()
