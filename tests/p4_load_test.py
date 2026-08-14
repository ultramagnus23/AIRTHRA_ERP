#!/usr/bin/env python
"""P4 100-plant mock load test.

Spins up the real edge daemon (edge/daemon.py --mock) for ~100 simulated
plants against the real ingest service and Postgres, and measures p95
"insert lag" -- the gap between a reading's ts (when the edge daemon
generated it) and the moment it's actually visible/committed in Postgres.
Asserts p95 < 5s per the PRD gate.

--------------------------------------------------------------------------
Design choices (documented per the task brief)
--------------------------------------------------------------------------
* 100 REAL OS subprocesses of edge/daemon.py --mock, one per simulated
  plant, not an in-process asyncio simulation. Rationale: edge/daemon.py
  is single-plant-per-process by design (see its own module docstring),
  and editing it to support multi-plant-per-process is out of scope for
  this phase (edge/ is P1's completed, do-not-touch surface). 100 mostly-
  idle asyncio processes (~30-50MB RSS each, one Postgres connection each
  only briefly at startup for the manifest fetch, then MQTT-only) is
  practical on an 8-core/16-thread dev box for a short (~1 minute) test.
  Startup is staggered (STARTUP_STAGGER_S apart) to avoid a Postgres
  connection storm and an MQTT CONNECT storm against mosquitto.

* All 100 simulated daemons reuse the SAME MQTT credentials
  (MQTT_EDGE_USERNAME/PASSWORD from .env, i.e. goa_pilot_01_edge) rather
  than provisioning 100 new mosquitto users. docker/mosquitto/mosquitto.conf
  has no per-topic ACL configured (confirmed by reading it) -- any
  authenticated client may publish to any plants/{plant_id}/readings
  topic -- so this is a faithful load-test of the ingest path without
  needing 100 rounds of scripts/mosquitto_add_user.sh (which itself
  requires either a local mosquitto_passwd binary or a docker exec round
  trip per device -- fine for onboarding one real device via
  scripts/provision_pi.py, impractical for spinning up/tearing down 100
  ad hoc load-test identities on every test run).

* "Insert lag" measurement: the `readings` table (P0 schema) has no
  received_at/inserted_at column, and P4 is explicitly barred from adding
  one via a migration (migrations/ is P1's completed, do-not-touch
  surface). So lag is measured by polling: every POLL_S seconds this
  script queries for readings with ts strictly greater than the newest ts
  it has already seen (across all load-test plants) and records
  `wall_clock_at_poll - reading.ts` as that row's lag sample. This is a
  slight OVERESTIMATE of true insert lag, bounded by at most POLL_S
  (the row could have been committed anywhere in the interval since the
  previous poll) -- a conservative bias that only makes the p95<5s
  assertion harder to pass, not easier. POLL_S is kept small (0.25s)
  relative to the 5s gate to keep that bias small.

Usage:
    .venv/Scripts/python.exe tests/p4_load_test.py [--num-plants 100] [--duration 45]

Cleans up all load-test plants/sensors/readings afterward even if
assertions fail (try/finally).
"""
from __future__ import annotations

import argparse
import shutil
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

import os  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

DATABASE_URL = os.environ.get("DATABASE_URL")

VENV_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
PYTHON = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable

PLANT_PREFIX = "load_test_plant_"
EDGE_DATA_DIR = ROOT / "edge" / "data"
EDGE_CACHE_DIR = ROOT / "edge" / "cache"
LOG_DIR = ROOT / "tests" / "_p4_load_test_logs"

# --- Tunables ---
DEFAULT_NUM_PLANTS = 100
DEFAULT_DURATION_S = 45
STARTUP_STAGGER_S = 0.08
WARMUP_SETTLE_S = 5
POLL_S = 0.25
GRACEFUL_STOP_TIMEOUT_S = 40
P95_GATE_S = 5.0

# Same 7-sensor manifest shape as seed/seed.py, reused for every load-test plant.
SENSORS = [
    ("SO2_in", "SO2_in", "ppm", 0, 5000),
    ("SO2_out", "SO2_out", "ppm", 0, 500),
    ("pH", "pH", "pH", 0, 14),
    ("temp_C", "temperature", "C", -10, 200),
    ("level_KOH_tank", "level", "%", 0, 100),
    ("level_K2SO3_tank", "level", "%", 0, 100),
    ("flow", "flow", "m3/h", 0, 500),
]

results = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, ok))
    status = "PASS" if ok else "FAIL"
    line = f"[{status}] {name}"
    if detail:
        line += f" - {detail}"
    print(line)
    return ok


def plant_ids(n: int) -> list[str]:
    return [f"{PLANT_PREFIX}{i:03d}" for i in range(1, n + 1)]


def seed_load_test_plants(engine, ids: list[str]) -> None:
    with engine.begin() as conn:
        for pid in ids:
            conn.execute(
                text(
                    """
                    INSERT INTO plants (plant_id, name, ambient_climate, boiler_capacity_tpd,
                                         fuel_type_primary, timezone_display)
                    VALUES (:pid, :name, 'tropical_coastal', 25.0, 'coal', 'Asia/Kolkata')
                    ON CONFLICT (plant_id) DO NOTHING
                    """
                ),
                {"pid": pid, "name": f"P4 Load Test Plant {pid}"},
            )
            for tag, kind, unit, min_valid, max_valid in SENSORS:
                conn.execute(
                    text(
                        """
                        INSERT INTO sensors (plant_id, sensor_id, tag, kind, unit, min_valid, max_valid)
                        VALUES (:pid, :sid, :tag, :kind, :unit, :minv, :maxv)
                        ON CONFLICT (plant_id, sensor_id) DO NOTHING
                        """
                    ),
                    {"pid": pid, "sid": tag, "tag": tag, "kind": kind, "unit": unit,
                     "minv": min_valid, "maxv": max_valid},
                )


def cleanup_load_test_data(engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM readings WHERE plant_id LIKE :p"), {"p": f"{PLANT_PREFIX}%"})
        conn.execute(text("DELETE FROM setpoint_changes WHERE plant_id LIKE :p"), {"p": f"{PLANT_PREFIX}%"})
        conn.execute(text("DELETE FROM dead_letter_readings WHERE plant_id LIKE :p"), {"p": f"{PLANT_PREFIX}%"})
        conn.execute(text("DELETE FROM kpis WHERE plant_id LIKE :p"), {"p": f"{PLANT_PREFIX}%"})
        conn.execute(text("DELETE FROM archive_log WHERE plant_id LIKE :p"), {"p": f"{PLANT_PREFIX}%"})
        conn.execute(text("DELETE FROM sensors WHERE plant_id LIKE :p"), {"p": f"{PLANT_PREFIX}%"})
        conn.execute(text("DELETE FROM plants WHERE plant_id LIKE :p"), {"p": f"{PLANT_PREFIX}%"})


def find_docker() -> str:
    for c in ("docker", r"C:\Program Files\Docker\Docker\resources\bin\docker.exe"):
        try:
            r = subprocess.run([c, "version", "--format", "{{.Server.Version}}"],
                                capture_output=True, text=True, timeout=15)
            if r.returncode == 0:
                return c
        except (FileNotFoundError, OSError):
            continue
    return ""


def start_process(args: list, log_name: str) -> subprocess.Popen:
    out_path = LOG_DIR / f"{log_name}.out.log"
    err_path = LOG_DIR / f"{log_name}.err.log"
    out_f = open(out_path, "w", encoding="utf-8")
    err_f = open(err_path, "w", encoding="utf-8")
    proc = subprocess.Popen(args, cwd=str(ROOT), stdout=out_f, stderr=err_f, text=True)
    proc._out_f = out_f
    proc._err_f = err_f
    return proc


def stop_process(proc: subprocess.Popen, timeout: float = 10.0) -> None:
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)
    finally:
        for f in (getattr(proc, "_out_f", None), getattr(proc, "_err_f", None)):
            if f:
                f.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Airthra P4 100-plant mock load test")
    parser.add_argument("--num-plants", type=int, default=DEFAULT_NUM_PLANTS)
    parser.add_argument("--duration", type=int, default=DEFAULT_DURATION_S,
                         help="seconds of steady-state measurement after warmup")
    args = parser.parse_args()

    if not DATABASE_URL:
        print("ERROR: DATABASE_URL not set (check .env)", file=sys.stderr)
        return 2

    docker_exe = find_docker()
    engine = create_engine(DATABASE_URL, future=True)

    try:
        with engine.connect():
            pass
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: Postgres unreachable: {exc}", file=sys.stderr)
        return 2
    check("Postgres reachable", True)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ids = plant_ids(args.num_plants)

    # Always clean any stale load-test rows from a previous interrupted run first.
    cleanup_load_test_data(engine)
    seed_load_test_plants(engine, ids)
    check(f"seeded {len(ids)} load-test plants + {len(SENSORS)} sensors each", True)

    for d in (EDGE_DATA_DIR, EDGE_CACHE_DIR):
        d.mkdir(parents=True, exist_ok=True)

    ingest_proc = None
    edge_procs: dict[str, subprocess.Popen] = {}
    all_ok = True

    try:
        print()
        print("=" * 70)
        print(f"P4 LOAD TEST: starting ingest service + {len(ids)} mock edge daemons")
        print("=" * 70)

        ingest_proc = start_process([PYTHON, "ingest/service.py"], "ingest")
        time.sleep(2)
        check("ingest process alive after startup", ingest_proc.poll() is None)

        for pid in ids:
            edge_procs[pid] = start_process(
                [PYTHON, "edge/daemon.py", "--mock", "--plant-id", pid, "--poll-interval", "1.0"],
                f"edge_{pid}",
            )
            time.sleep(STARTUP_STAGGER_S)

        print(f"  launched {len(edge_procs)} edge daemon processes "
              f"(staggered {STARTUP_STAGGER_S}s apart)")

        print(f"  warmup settle: {WARMUP_SETTLE_S}s")
        time.sleep(WARMUP_SETTLE_S)

        dead = [pid for pid, p in edge_procs.items() if p.poll() is not None]
        check("all edge daemon processes still alive after warmup",
              len(dead) == 0, f"{len(dead)}/{len(edge_procs)} dead: {dead[:5]}")
        check("ingest process still alive after warmup", ingest_proc.poll() is None)

        # --- measurement window ---
        print()
        print("=" * 70)
        print(f"P4 LOAD TEST: measuring insert lag for {args.duration}s "
              f"(poll every {POLL_S}s)")
        print("=" * 70)

        lag_samples: list[float] = []
        last_max_ts = datetime.now(timezone.utc)
        measure_deadline = time.time() + args.duration
        poll_count = 0
        while time.time() < measure_deadline:
            now_wall = time.time()
            with engine.connect() as conn:
                rows = conn.execute(
                    text(
                        """
                        SELECT ts FROM readings
                        WHERE plant_id LIKE :p AND ts > :last_max_ts
                        ORDER BY ts
                        """
                    ),
                    {"p": f"{PLANT_PREFIX}%", "last_max_ts": last_max_ts},
                ).all()
            if rows:
                for (ts,) in rows:
                    lag_samples.append(now_wall - ts.timestamp())
                last_max_ts = rows[-1][0]
            poll_count += 1
            if poll_count % 20 == 0:
                print(f"  t-{int(measure_deadline - time.time())}s samples={len(lag_samples)}")
            time.sleep(POLL_S)

        check("collected at least one insert-lag sample", len(lag_samples) > 0,
              f"samples={len(lag_samples)}")

        if lag_samples:
            lag_samples.sort()
            p50 = lag_samples[int(0.50 * (len(lag_samples) - 1))]
            p95 = lag_samples[int(0.95 * (len(lag_samples) - 1))]
            p99 = lag_samples[int(0.99 * (len(lag_samples) - 1))]
            mean = statistics.mean(lag_samples)
            print(f"  insert lag over {len(lag_samples)} samples: "
                  f"mean={mean:.3f}s p50={p50:.3f}s p95={p95:.3f}s p99={p99:.3f}s "
                  f"max={lag_samples[-1]:.3f}s")
            check(f"p95 insert lag < {P95_GATE_S}s (PRD gate)", p95 < P95_GATE_S,
                  f"p95={p95:.3f}s")
        else:
            check(f"p95 insert lag < {P95_GATE_S}s (PRD gate)", False, "no samples collected")

        # --- graceful stop of all daemons ---
        print()
        print("=" * 70)
        print("P4 LOAD TEST: graceful stop of all edge daemons")
        print("=" * 70)
        for pid in ids:
            stop_path = EDGE_DATA_DIR / f"stop_{pid}.request"
            stop_path.write_text("stop", encoding="utf-8")

        stop_deadline = time.time() + GRACEFUL_STOP_TIMEOUT_S
        while time.time() < stop_deadline:
            still_running = [pid for pid, p in edge_procs.items() if p.poll() is None]
            if not still_running:
                break
            time.sleep(1)
        still_running = [pid for pid, p in edge_procs.items() if p.poll() is None]
        check(f"all edge daemons exited on their own after graceful-stop request "
              f"within {GRACEFUL_STOP_TIMEOUT_S}s", len(still_running) == 0,
              f"{len(still_running)} still running: {still_running[:5]}")

    finally:
        print()
        print("Cleanup: stopping any remaining processes...")
        for pid, p in edge_procs.items():
            stop_process(p)
        if ingest_proc is not None:
            stop_process(ingest_proc)

        print("Cleanup: deleting load-test plants/sensors/readings from Postgres...")
        try:
            cleanup_load_test_data(engine)
            print("  done")
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR during DB cleanup (may need manual cleanup!): {exc}", file=sys.stderr)
            all_ok = False

        print("Cleanup: removing edge daemon state files for load-test plants...")
        removed = 0
        for pid in ids:
            for pattern in (f"stats_{pid}.json", f"stop_{pid}.request", f"buffer_{pid}.db",
                            f"watchdog_{pid}.heartbeat"):
                fp = EDGE_DATA_DIR / pattern
                if fp.exists():
                    fp.unlink()
                    removed += 1
            cache_fp = EDGE_CACHE_DIR / f"manifest_{pid}.json"
            if cache_fp.exists():
                cache_fp.unlink()
                removed += 1
        print(f"  removed {removed} state files")

    print()
    print("=" * 70)
    failed = [n for n, ok in results if not ok]
    if failed or not all_ok:
        print(f"P4 LOAD TEST: FAIL ({len(failed)}/{len(results)} checks failed)")
        for n in failed:
            print(f"  - {n}")
        print(f"\nLogs: {LOG_DIR}")
        return 1
    print(f"P4 LOAD TEST: PASS ({len(results)}/{len(results)} checks passed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
