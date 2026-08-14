#!/usr/bin/env python
"""P3 gate verification.

Proves the alarm engine (workers/alarm_engine.py) actually raises a
correctly-diagnosed alarm from a frozen-sensor fault, and separately
re-confirms P2's history-resolution auto-selection at its documented
boundaries (raw <6h, readings_1m <3d, readings_15m <30d, else
readings_1h).

What this script does:
  1. Runs workers/seed_alarm_rules.py (idempotent) to make sure the
     global frozen-sensor rule exists.
  2. Deterministically injects the fault: directly INSERTs a run of
     `readings` rows for goa_pilot_01 / SO2_in with quality_flag='frozen'
     and an identical value, spanning >= the rule's min_duration_s
     (120s), ending at "now" - bypassing the edge daemon entirely for a
     fast, reliable, exact-timing test (the alternative sanctioned by the
     task: running edge/daemon.py --mock and waiting for a randomly-timed
     mock fault window is not deterministic enough for a fast gate).
  3. Calls workers.alarm_engine.run_once(engine) in-process (not a
     subprocess - the task explicitly allows either) and asserts a new
     `alarms` row was raised for goa_pilot_01 with the frozen-sensor
     rule's diagnosis text (not a generic message).
  4. Also asserts the state machine's other two edges on the same fixture:
     clearing (fault readings stop -> next run_once clears the alarm) and
     cooldown (clearing again immediately after re-injecting the same
     fault within cooldown_s must NOT re-raise).
  5. Starts the P2 FastAPI app (api.main) as a background process (same
     pattern as tests/p2_gate.py), logs in as the seeded operator user,
     and hits GET .../history at pairs of ranges straddling each
     documented resolution boundary (6h, 3d, 30d), asserting the
     `resolution` field lands on the correct tier just under and just
     over each boundary.
  6. Cleans up every test-only alarms/readings row it inserted and stops
     the API process.

Prints PASS/FAIL per check, exits non-zero on any failure.

Run from repo root: `python tests/p3_gate.py`
(the API is started automatically; nothing else needs to be running
except Postgres on 5433 via `docker compose up -d postgres`).
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
except ImportError:
    pass

import httpx  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from workers import alarm_engine  # noqa: E402

DATABASE_URL = os.environ.get("DATABASE_URL")
API_HOST = os.environ.get("API_HOST", "127.0.0.1")
API_PORT = int(os.environ.get("API_PORT", "8000"))
BASE_URL = f"http://{API_HOST}:{API_PORT}"

PLANT_ID = "goa_pilot_01"
SENSOR_ID = "SO2_in"
FROZEN_VALUE = 123.45
MIN_DURATION_S = 120  # must match workers/seed_alarm_rules.py's FROZEN_SENSOR_RULE

TENANT_EMAIL = "operator@goa-pilot.airthra.dev"
TENANT_PASSWORD = "Airthra_Dev_2026!"

VENV_PYTHON = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
PYTHON = VENV_PYTHON if os.path.exists(VENV_PYTHON) else sys.executable

results: list[tuple[str, bool]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, ok))
    status = "PASS" if ok else "FAIL"
    line = f"[{status}] {name}"
    if detail:
        line += f" - {detail}"
    print(line)
    return ok


def run_seed_rules() -> bool:
    r = subprocess.run([PYTHON, "workers/seed_alarm_rules.py"], cwd=ROOT,
                        capture_output=True, text=True, timeout=30)
    print(r.stdout.strip())
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
    return r.returncode == 0


def insert_frozen_run(conn, sensor_id: str, value: float, now: datetime, span_s: int) -> int:
    """Inserts readings every 15s from (now - span_s) through now, all with
    quality_flag='frozen' and the same value. Returns rows inserted."""
    n = 0
    t = now - timedelta(seconds=span_s)
    step = timedelta(seconds=15)
    while t <= now:
        conn.execute(
            text(
                """
                INSERT INTO readings (ts, plant_id, sensor_id, value, quality_flag)
                VALUES (:ts, :plant_id, :sensor_id, :value, 'frozen')
                ON CONFLICT (plant_id, sensor_id, ts) DO UPDATE SET
                    value = EXCLUDED.value, quality_flag = EXCLUDED.quality_flag
                """
            ),
            {"ts": t, "plant_id": PLANT_ID, "sensor_id": sensor_id, "value": value},
        )
        n += 1
        t += step
    return n


def cleanup_readings(conn, sensor_id: str) -> None:
    # Sweeps everything in a generous trailing window, not just rows
    # matching FROZEN_VALUE - a prior interrupted/failed run of this same
    # gate script can leave behind stray marker rows (e.g. the 'good'
    # clear-fixture reading) at other values that would otherwise silently
    # pollute the next run's contiguous-run scan and make it flaky.
    conn.execute(
        text(
            """
            DELETE FROM readings
            WHERE plant_id = :p AND sensor_id = :s
              AND ts >= now() - interval '1 hour'
            """
        ),
        {"p": PLANT_ID, "s": sensor_id},
    )


def cleanup_test_alarms(conn, alarm_ids: list[str]) -> None:
    if not alarm_ids:
        return
    conn.execute(
        text("DELETE FROM alarms WHERE alarm_id = ANY(:ids)"),
        {"ids": alarm_ids},
    )


def wait_for_health(timeout_s: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            r = httpx.get(f"{BASE_URL}/health", timeout=2.0)
            if r.status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    return False


def login() -> str:
    r = httpx.post(f"{BASE_URL}/auth/login", json={"email": TENANT_EMAIL, "password": TENANT_PASSWORD}, timeout=10)
    r.raise_for_status()
    return r.json()["access_token"]


def history_resolution(token: str, start: datetime, end: datetime) -> str:
    r = httpx.get(
        f"{BASE_URL}/api/v1/{PLANT_ID}/history",
        params={"start": start.isoformat(), "end": end.isoformat()},
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["resolution"]


def main() -> int:
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL not set (check .env)", file=sys.stderr)
        return 2

    engine = create_engine(DATABASE_URL, future=True)
    try:
        with engine.connect():
            pass
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: Postgres unreachable at {DATABASE_URL}: {exc}", file=sys.stderr)
        return 2
    check("Postgres reachable", True)

    print()
    print("=" * 70)
    print("P3 GATE: seeding frozen-sensor alarm rule")
    print("=" * 70)
    check("workers/seed_alarm_rules.py ran successfully (idempotent)", run_seed_rules())

    frozen_alarm_ids: list[str] = []

    print()
    print("=" * 70)
    print("P3 GATE: injecting deterministic frozen-sensor fault + running alarm engine")
    print("=" * 70)
    try:
        now = datetime.now(timezone.utc)
        with engine.begin() as conn:
            # Clean slate for this sensor's test rows.
            cleanup_readings(conn, SENSOR_ID)
            n = insert_frozen_run(conn, SENSOR_ID, FROZEN_VALUE, now, MIN_DURATION_S + 15)
        check(f"injected {n} identical-value quality_flag='frozen' readings for {SENSOR_ID}", n > 0, f"span={MIN_DURATION_S + 15}s")

        alarm_engine.run_once(engine)

        with engine.begin() as conn:
            raised = conn.execute(
                text(
                    """
                    SELECT alarm_id, state, severity, diagnosis, suggested_part
                    FROM alarms
                    WHERE plant_id = :p AND state = 'raised'
                      AND diagnosis ILIKE '%frozen%'
                    ORDER BY raised_at DESC LIMIT 1
                    """
                ),
                {"p": PLANT_ID},
            ).mappings().first()

        raised_ok = check(
            "alarm engine raised an alarm with a frozen-sensor diagnosis (not generic)",
            raised is not None,
            dict(raised) if raised else "no matching alarms row found",
        )
        if raised_ok:
            frozen_alarm_ids.append(str(raised["alarm_id"]))
            check(
                "raised alarm's diagnosis references the frozen-sensor cause specifically",
                "frozen" in raised["diagnosis"].lower() and "sensor" in raised["diagnosis"].lower(),
                raised["diagnosis"],
            )
            check("raised alarm carries a suggested_part (not null)", bool(raised["suggested_part"]), raised["suggested_part"])
            check("raised alarm severity copied from rule ('critical')", raised["severity"] == "critical", raised["severity"])

        # --- Clearing edge: stop the fault, re-run, alarm should clear ---
        print()
        print("=" * 70)
        print("P3 GATE: fault clears -> alarm engine should clear the alarm")
        print("=" * 70)
        with engine.begin() as conn:
            cleanup_readings(conn, SENSOR_ID)
            # A single fresh 'good' reading so the sensor has *some* recent
            # non-frozen data (not strictly required by the persistence
            # check, but keeps the fixture realistic).
            conn.execute(
                text(
                    """
                    INSERT INTO readings (ts, plant_id, sensor_id, value, quality_flag)
                    VALUES (:ts, :p, :s, 999.0, 'good')
                    ON CONFLICT (plant_id, sensor_id, ts) DO NOTHING
                    """
                ),
                {"ts": datetime.now(timezone.utc), "p": PLANT_ID, "s": SENSOR_ID},
            )

        alarm_engine.run_once(engine)

        with engine.begin() as conn:
            cleared = conn.execute(
                text("SELECT state, cleared_at FROM alarms WHERE alarm_id = :id"),
                {"id": frozen_alarm_ids[0] if frozen_alarm_ids else None},
            ).mappings().first() if frozen_alarm_ids else None

        check(
            "alarm transitioned to 'cleared' once the fault stopped",
            cleared is not None and cleared["state"] == "cleared" and cleared["cleared_at"] is not None,
            dict(cleared) if cleared else "no alarm row to check (previous step failed)",
        )

        # --- Cooldown edge: re-inject the same fault immediately; must NOT re-raise ---
        print()
        print("=" * 70)
        print("P3 GATE: cooldown - re-injecting the same fault immediately after clear")
        print("=" * 70)
        now2 = datetime.now(timezone.utc)
        with engine.begin() as conn:
            cleanup_readings(conn, SENSOR_ID)
            insert_frozen_run(conn, SENSOR_ID, FROZEN_VALUE, now2, MIN_DURATION_S + 15)

        alarm_engine.run_once(engine)

        with engine.begin() as conn:
            active_count = conn.execute(
                text(
                    """
                    SELECT count(*) FROM alarms
                    WHERE plant_id = :p AND state IN ('raised','acked','escalated')
                      AND diagnosis ILIKE '%frozen%'
                    """
                ),
                {"p": PLANT_ID},
            ).scalar()

        check(
            "cooldown respected: rule did NOT re-raise immediately after clearing",
            active_count == 0,
            f"active frozen alarms={active_count}",
        )

    finally:
        with engine.begin() as conn:
            cleanup_readings(conn, SENSOR_ID)
            # Sweep up any alarms this run created (raised/cleared/escalated),
            # not just the first one tracked above.
            extra_ids = [
                str(r[0]) for r in conn.execute(
                    text(
                        """
                        SELECT alarm_id FROM alarms
                        WHERE plant_id = :p AND diagnosis ILIKE '%frozen - likely wiring fault or transducer failure%'
                        """
                    ),
                    {"p": PLANT_ID},
                ).fetchall()
            ]
            cleanup_test_alarms(conn, list(set(frozen_alarm_ids) | set(extra_ids)))
        print("cleaned up test readings + alarms rows")

    print()
    print("=" * 70)
    print("P3 GATE: starting P2 API to verify history resolution auto-selection boundaries")
    print("=" * 70)

    env = os.environ.copy()
    log_path = os.path.join(ROOT, "tests", "_p3_gate_api.log")
    log_file = open(log_path, "w", encoding="utf-8")
    api_proc = subprocess.Popen(
        [sys.executable, "-m", "api.main"],
        cwd=ROOT, env=env,
        stdout=log_file, stderr=subprocess.STDOUT, text=True,
    )

    try:
        if not wait_for_health():
            print(f"ERROR: API did not become healthy in time - see {log_path}", file=sys.stderr)
            check("P2 API became healthy", False)
        else:
            check("P2 API became healthy", True)
            token = login()
            check("login as seeded operator user succeeded", bool(token))

            end = datetime.now(timezone.utc)

            boundary_cases = [
                # (label, span, expected resolution)
                ("just under 6h -> raw", timedelta(hours=6) - timedelta(minutes=1), "raw"),
                ("just over 6h -> 1m", timedelta(hours=6) + timedelta(minutes=1), "1m"),
                ("just under 3d -> 1m", timedelta(days=3) - timedelta(minutes=1), "1m"),
                ("just over 3d -> 15m", timedelta(days=3) + timedelta(minutes=1), "15m"),
                ("just under 30d -> 15m", timedelta(days=30) - timedelta(minutes=1), "15m"),
                ("just over 30d -> 1h", timedelta(days=30) + timedelta(minutes=1), "1h"),
            ]
            for label, span, expected in boundary_cases:
                start = end - span
                got = history_resolution(token, start, end)
                check(f"history resolution boundary: {label}", got == expected, f"got='{got}' expected='{expected}'")

    finally:
        api_proc.terminate()
        try:
            api_proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            api_proc.kill()
            api_proc.wait(timeout=10)
        log_file.close()

    print()
    print("=" * 70)
    failed = [n for n, ok in results if not ok]
    if failed:
        print(f"P3 GATE: FAIL ({len(failed)}/{len(results)} checks failed)")
        for n in failed:
            print(f"  - {n}")
        print(f"\nAPI log: {log_path}")
        return 1
    print(f"P3 GATE: PASS ({len(results)}/{len(results)} checks passed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
