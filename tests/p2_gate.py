#!/usr/bin/env python
"""P2 gate verification.

Proves the literal P2 acceptance gate from the PRD: "tenant_read JWT for
plant A receives 403 on plant B on every endpoint" - and, as the
necessary sanity check that the gate isn't just failing everything, that
the same JWT succeeds (200/201, never 403) against its own plant on every
endpoint.

What this script does:
  1. Runs seed/seed.py (idempotent) to make sure the tenant_read user
     (operator@goa-pilot.airthra.dev, scoped to goa_pilot_01) exists.
  2. Directly creates a temporary second plant `plant_b_test` with its own
     sensor and a temporary alarm row (via the plain superuser DB
     connection, same pattern as tests/p0_gate.py's admin_engine) - NOT
     accessible to the tenant user. Also creates a temporary alarm for
     goa_pilot_01 so the ack endpoint has something real to ack.
  3. Starts the FastAPI app (api.main) as a background uvicorn process and
     waits for /health.
  4. Logs in as the tenant user, gets a JWT.
  5. Hits every plant-scoped endpoint (current, history, kpis, event,
     alarm ack, and the /ws websocket) against plant_b_test - asserts 403
     on every single one - and against goa_pilot_01 - asserts success
     (2xx) on every single one.
  6. Cleans up plant_b_test (and its sensor/alarm) and the temporary
     goa_pilot_01 alarm, stops the API process.

Prints PASS/FAIL per check, exits non-zero on any failure.

Run from repo root: `python tests/p2_gate.py`
(the API is started automatically; nothing else needs to be running
except Postgres on 5433).
"""
from __future__ import annotations

import asyncio
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
import websockets  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

DATABASE_URL = os.environ.get("DATABASE_URL")
API_HOST = os.environ.get("API_HOST", "127.0.0.1")
API_PORT = int(os.environ.get("API_PORT", "8000"))
BASE_URL = f"http://{API_HOST}:{API_PORT}"
WS_BASE = f"ws://{API_HOST}:{API_PORT}"

TENANT_EMAIL = "operator@goa-pilot.airthra.dev"
TENANT_PASSWORD = "Airthra_Dev_2026!"
OWN_PLANT = "goa_pilot_01"
OTHER_PLANT = "plant_b_test"

results: list[tuple[str, bool]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok))
    status = "PASS" if ok else "FAIL"
    line = f"[{status}] {name}"
    if detail:
        line += f" - {detail}"
    print(line)


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


def setup_db() -> dict:
    """Create plant_b_test + sensor + temp alarms for both plants."""
    engine = create_engine(DATABASE_URL, future=True)
    alarm_ids = {}
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO plants (plant_id, name) VALUES (:p, :p) ON CONFLICT (plant_id) DO NOTHING"),
            {"p": OTHER_PLANT},
        )
        conn.execute(
            text(
                """
                INSERT INTO sensors (plant_id, sensor_id, tag, kind, unit)
                VALUES (:p, 'gate_sensor', 'gate_tag', 'flow', 'm3/h')
                ON CONFLICT (plant_id, sensor_id) DO NOTHING
                """
            ),
            {"p": OTHER_PLANT},
        )
        conn.execute(
            text(
                """
                INSERT INTO readings (ts, plant_id, sensor_id, value, quality_flag)
                VALUES (now(), :p, 'gate_sensor', 42.0, 'good')
                ON CONFLICT DO NOTHING
                """
            ),
            {"p": OTHER_PLANT},
        )
        for plant_id, key in ((OWN_PLANT, "own"), (OTHER_PLANT, "other")):
            alarm_id = str(uuid.uuid4())
            conn.execute(
                text(
                    """
                    INSERT INTO alarms (alarm_id, plant_id, severity, state, raised_at)
                    VALUES (:id, :p, 'warning', 'raised', now())
                    """
                ),
                {"id": alarm_id, "p": plant_id},
            )
            alarm_ids[key] = alarm_id
    return alarm_ids


def teardown_db(alarm_ids: dict) -> None:
    engine = create_engine(DATABASE_URL, future=True)
    with engine.begin() as conn:
        for alarm_id in alarm_ids.values():
            conn.execute(text("DELETE FROM alarms WHERE alarm_id = :id"), {"id": alarm_id})
        conn.execute(text("DELETE FROM operator_events WHERE plant_id = :p"), {"p": OTHER_PLANT})
        conn.execute(text("DELETE FROM readings WHERE plant_id = :p"), {"p": OTHER_PLANT})
        conn.execute(text("DELETE FROM sensors WHERE plant_id = :p"), {"p": OTHER_PLANT})
        conn.execute(text("DELETE FROM plants WHERE plant_id = :p"), {"p": OTHER_PLANT})


def login() -> dict:
    r = httpx.post(
        f"{BASE_URL}/auth/login",
        json={"email": TENANT_EMAIL, "password": TENANT_PASSWORD},
        timeout=5.0,
    )
    r.raise_for_status()
    body = r.json()
    assert body["role"] == "tenant_read", f"expected tenant_read role, got {body['role']}"
    assert body["plant_ids"] == [OWN_PLANT], f"expected plant_ids == [{OWN_PLANT}], got {body['plant_ids']}"
    return body


def rest_checks(token: str, alarm_ids: dict) -> None:
    headers = {"Authorization": f"Bearer {token}"}
    now = datetime.now(timezone.utc)
    start = (now - timedelta(hours=1)).isoformat()
    end = now.isoformat()

    endpoints = [
        ("GET current", lambda p: httpx.get(f"{BASE_URL}/api/v1/{p}/current", headers=headers, timeout=5.0)),
        ("GET history", lambda p: httpx.get(
            f"{BASE_URL}/api/v1/{p}/history", headers=headers, timeout=5.0,
            params={"start": start, "end": end},
        )),
        ("GET kpis", lambda p: httpx.get(f"{BASE_URL}/api/v1/{p}/kpis", headers=headers, timeout=5.0)),
        ("POST event", lambda p: httpx.post(
            f"{BASE_URL}/api/v1/{p}/event", headers=headers, timeout=5.0,
            json={"kind": "note", "payload": {"note": "p2 gate check"}},
        )),
    ]

    for name, call in endpoints:
        r_other = call(OTHER_PLANT)
        check(f"{name}: plant B -> 403", r_other.status_code == 403,
              f"got {r_other.status_code}")

        r_own = call(OWN_PLANT)
        check(f"{name}: own plant -> success (not 403)", 200 <= r_own.status_code < 300,
              f"got {r_own.status_code}")

    # alarm ack: separate alarm ids per plant (created in setup_db)
    r_other = httpx.post(
        f"{BASE_URL}/api/v1/{OTHER_PLANT}/alarms/{alarm_ids['other']}/ack",
        headers=headers, timeout=5.0,
    )
    check("POST alarms/ack: plant B -> 403", r_other.status_code == 403, f"got {r_other.status_code}")

    r_own = httpx.post(
        f"{BASE_URL}/api/v1/{OWN_PLANT}/alarms/{alarm_ids['own']}/ack",
        headers=headers, timeout=5.0,
    )
    check("POST alarms/ack: own plant -> success (not 403)", 200 <= r_own.status_code < 300,
          f"got {r_own.status_code}")


async def _ws_check(plant_id: str, token: str) -> tuple[bool, str]:
    """Returns (connected_ok, detail)."""
    try:
        async with websockets.connect(
            f"{WS_BASE}/ws/{plant_id}",
            additional_headers={"Authorization": f"Bearer {token}"},
            open_timeout=5.0,
        ) as ws:
            await ws.close()
            return True, "connected"
    except websockets.exceptions.InvalidStatus as exc:
        return False, f"status {exc.response.status_code}"
    except Exception as exc:  # pragma: no cover
        return False, f"{type(exc).__name__}: {exc}"


def ws_checks(token: str) -> None:
    ok_other, detail_other = asyncio.run(_ws_check(OTHER_PLANT, token))
    check("WS /ws: plant B -> 403", (not ok_other) and detail_other == "status 403", detail_other)

    ok_own, detail_own = asyncio.run(_ws_check(OWN_PLANT, token))
    check("WS /ws: own plant -> connects (not 403)", ok_own, detail_own)


def main() -> int:
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL not set (check .env)", file=sys.stderr)
        return 2

    print("=" * 70)
    print("P2 GATE: setup (seed + temp plant_b_test)")
    print("=" * 70)

    seed_proc = subprocess.run(
        [sys.executable, os.path.join(ROOT, "seed", "seed.py")],
        cwd=ROOT, capture_output=True, text=True,
    )
    if seed_proc.returncode != 0:
        print(seed_proc.stdout)
        print(seed_proc.stderr, file=sys.stderr)
        print("ERROR: seed/seed.py failed", file=sys.stderr)
        return 2
    print(seed_proc.stdout.strip())

    alarm_ids = setup_db()
    print(f"created temp plant '{OTHER_PLANT}' + sensor + temp alarms {alarm_ids}")

    print()
    print("=" * 70)
    print("P2 GATE: starting API")
    print("=" * 70)

    env = os.environ.copy()
    log_path = os.path.join(ROOT, "tests", "_p2_gate_api.log")
    log_file = open(log_path, "w", encoding="utf-8")
    api_proc = subprocess.Popen(
        [sys.executable, "-m", "api.main"],
        cwd=ROOT, env=env,
        stdout=log_file, stderr=subprocess.STDOUT, text=True,
    )

    exit_code = 1
    try:
        if not wait_for_health():
            print(f"ERROR: API did not become healthy in time - see {log_path}", file=sys.stderr)
            log_file.flush()
            return 2
        print(f"API healthy at {BASE_URL}")

        print()
        print("=" * 70)
        print("P2 GATE: login as tenant_read user")
        print("=" * 70)
        login_body = login()
        token = login_body["access_token"]
        check("login: tenant_read JWT issued, scoped to own plant only", True,
              f"plant_ids={login_body['plant_ids']}")

        print()
        print("=" * 70)
        print("P2 GATE: REST endpoint tenant scoping")
        print("=" * 70)
        rest_checks(token, alarm_ids)

        print()
        print("=" * 70)
        print("P2 GATE: WS endpoint tenant scoping")
        print("=" * 70)
        ws_checks(token)

        print()
        print("=" * 70)
        failed = [n for n, ok in results if not ok]
        if failed:
            print(f"P2 GATE: FAIL ({len(failed)}/{len(results)} checks failed)")
            for n in failed:
                print(f"  - {n}")
            exit_code = 1
        else:
            print(f"P2 GATE: PASS ({len(results)}/{len(results)} checks passed)")
            exit_code = 0
    finally:
        print()
        print("=" * 70)
        print("P2 GATE: teardown")
        print("=" * 70)
        api_proc.terminate()
        try:
            api_proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            api_proc.kill()
        log_file.close()
        teardown_db(alarm_ids)
        print(f"removed temp plant '{OTHER_PLANT}' + sensor + temp alarms, stopped API")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
