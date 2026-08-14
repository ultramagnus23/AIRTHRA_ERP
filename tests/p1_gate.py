#!/usr/bin/env python
"""P1 gate verification.

Proves the "data spine" (edge daemon + ingest service) actually survives a
broker outage without losing or duplicating data:

  1. Starts the ingest service and the edge daemon (--mock --plant-id
     goa_pilot_01) against the live Docker stack and confirms readings are
     flowing into Postgres.
  2. Stops the mosquitto container to simulate a broker/network outage.
     TIMING NOTE: the spec's "10-minute outage" is compressed to
     OUTAGE_SECONDS below (a few tens of seconds) purely for test runtime -
     the SQLite-buffer-then-backfill-drain code path is genuinely exercised
     either way; only the wall-clock duration is scaled down.
  3. While mosquitto is down, confirms the edge daemon keeps running and is
     buffering readings to its local SQLite WAL file (not dropping them,
     not crashing).
  4. Restarts mosquitto and confirms the Sync task drains the buffer back
     down to zero.
  5. Requests a graceful stop (filesystem trigger, see
     edge/config.py:stop_request_path) so the daemon stops generating new
     readings but flushes everything already generated (outbox + SQLite
     buffer) before exiting - this is what makes an exact-equality "zero
     gaps" assertion meaningful instead of an artifact of exactly when the
     test happened to kill the process.
  6. Asserts: Postgres `readings` row count for the run == the daemon's own
     count of readings generated (zero gaps, and zero duplicates - the
     table's composite PK makes over-counting structurally impossible), and
     `dead_letter_readings` is empty (nothing genuinely invalid was
     generated in this test).

Prints PASS/FAIL per check and exits non-zero on any failure.
Run from the repo root: `python tests/p1_gate.py`
(tests/p1_gate.ps1 is a thin PowerShell wrapper.)
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from sqlalchemy import create_engine, text  # noqa: E402

DATABASE_URL = os.environ.get("DATABASE_URL")
PLANT_ID = "goa_pilot_01"

VENV_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
PYTHON = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable

EDGE_DATA_DIR = ROOT / "edge" / "data"
EDGE_CACHE_DIR = ROOT / "edge" / "cache"
STATS_PATH = EDGE_DATA_DIR / f"stats_{PLANT_ID}.json"
STOP_REQUEST_PATH = EDGE_DATA_DIR / f"stop_{PLANT_ID}.request"
BUFFER_DB_PATH = EDGE_DATA_DIR / f"buffer_{PLANT_ID}.db"

LOG_DIR = ROOT / "tests" / "_p1_gate_logs"

# --- Timing (see module docstring re: the outage-length deviation) ---
WARMUP_SECONDS = 6
OUTAGE_SECONDS = 25
DRAIN_TIMEOUT_SECONDS = 60
POST_RECOVERY_SETTLE_SECONDS = 5
GRACEFUL_STOP_TIMEOUT_SECONDS = 40
FINAL_INGEST_SETTLE_SECONDS = 5

results = []  # (name, bool)


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, ok))
    status = "PASS" if ok else "FAIL"
    line = f"[{status}] {name}"
    if detail:
        line += f" - {detail}"
    print(line)
    return ok


def find_docker() -> str:
    candidates = ["docker", r"C:\Program Files\Docker\Docker\resources\bin\docker.exe"]
    for c in candidates:
        try:
            r = subprocess.run([c, "version", "--format", "{{.Server.Version}}"],
                                capture_output=True, text=True, timeout=15)
            if r.returncode == 0:
                return c
        except (FileNotFoundError, OSError):
            continue
    return ""


def docker_compose(docker_exe: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([docker_exe, "compose", *args], cwd=str(ROOT),
                           capture_output=True, text=True, timeout=60)


def service_running(docker_exe: str, service: str) -> bool:
    r = docker_compose(docker_exe, "ps", "--status", "running", "--format", "{{.Service}}")
    return service in r.stdout.split()


def read_stats() -> dict:
    if not STATS_PATH.exists():
        return {}
    try:
        return json.loads(STATS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def buffer_row_count() -> int:
    if not BUFFER_DB_PATH.exists():
        return 0
    try:
        conn = sqlite3.connect(f"file:{BUFFER_DB_PATH}?mode=ro", uri=True, timeout=5)
        try:
            cur = conn.execute("SELECT COUNT(*) FROM buffer")
            return int(cur.fetchone()[0])
        finally:
            conn.close()
    except sqlite3.Error:
        return 0


def reset_gate_state(engine) -> None:
    """Clean slate for a repeatable run: previous gate rows in Postgres for
    this plant, and any leftover edge daemon state files on disk."""
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM readings WHERE plant_id = :p"), {"p": PLANT_ID})
        conn.execute(text("DELETE FROM setpoint_changes WHERE plant_id = :p"), {"p": PLANT_ID})
        conn.execute(text("DELETE FROM dead_letter_readings WHERE plant_id = :p OR plant_id IS NULL"), {"p": PLANT_ID})
    for d in (EDGE_DATA_DIR, EDGE_CACHE_DIR):
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def start_process(args: list, log_name: str) -> subprocess.Popen:
    out_path = LOG_DIR / f"{log_name}.out.log"
    err_path = LOG_DIR / f"{log_name}.err.log"
    out_f = open(out_path, "w", encoding="utf-8")
    err_f = open(err_path, "w", encoding="utf-8")
    proc = subprocess.Popen(args, cwd=str(ROOT), stdout=out_f, stderr=err_f, text=True)
    proc._out_f = out_f  # keep refs so they don't get gc'd/closed early
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
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL not set (check .env)", file=sys.stderr)
        return 2

    print("=" * 70)
    print("P1 GATE: pre-flight checks")
    print("=" * 70)

    docker_exe = find_docker()
    if not docker_exe:
        print("ERROR: docker CLI not found/reachable. Cannot run the outage "
              "simulation against the live stack. Stopping rather than "
              "falling back to a weaker (non-Docker) substitute.", file=sys.stderr)
        return 2
    check("docker CLI reachable", True, docker_exe)

    try:
        engine = create_engine(DATABASE_URL, future=True)
        with engine.connect():
            pass
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: Postgres unreachable at {DATABASE_URL}: {exc}", file=sys.stderr)
        return 2
    check("Postgres reachable", True)

    if not service_running(docker_exe, "postgres"):
        print("ERROR: docker compose service 'postgres' is not running.", file=sys.stderr)
        return 2
    if not service_running(docker_exe, "mosquitto"):
        print("ERROR: docker compose service 'mosquitto' is not running. "
              "Bring up the stack first: docker compose up -d postgres mosquitto", file=sys.stderr)
        return 2
    check("postgres + mosquitto containers running", True)

    reset_gate_state(engine)
    check("gate state reset (old rows/files cleared)", True)

    print()
    print("=" * 70)
    print("P1 GATE: starting ingest service + edge daemon (--mock)")
    print("=" * 70)

    ingest_proc = start_process([PYTHON, "ingest/service.py"], "ingest")
    time.sleep(2)  # give ingest a head start to connect + subscribe
    edge_proc = start_process(
        [PYTHON, "edge/daemon.py", "--mock", "--plant-id", PLANT_ID, "--poll-interval", "0.5"],
        "edge",
    )

    all_ok = True
    try:
        time.sleep(WARMUP_SECONDS)

        check("ingest process alive after warmup", ingest_proc.poll() is None)
        edge_alive = check("edge daemon process alive after warmup", edge_proc.poll() is None)
        if not edge_alive:
            print((LOG_DIR / "edge.err.log").read_text(encoding="utf-8", errors="replace")[-3000:])

        with engine.connect() as conn:
            warmup_count = conn.execute(
                text("SELECT count(*) FROM readings WHERE plant_id = :p"), {"p": PLANT_ID}
            ).scalar()
        check("readings flowing into Postgres before outage", warmup_count and warmup_count > 0,
              f"count={warmup_count}")

        print()
        print("=" * 70)
        print(f"P1 GATE: simulating broker outage ({OUTAGE_SECONDS}s, stopping mosquitto)")
        print("=" * 70)

        docker_compose(docker_exe, "stop", "mosquitto")

        saw_buffer_growth = False
        outage_deadline = time.time() + OUTAGE_SECONDS
        edge_survived_outage = True
        while time.time() < outage_deadline:
            time.sleep(2)
            if edge_proc.poll() is not None:
                edge_survived_outage = False
                break
            bcount = buffer_row_count()
            if bcount > 0:
                saw_buffer_growth = True
            print(f"  outage: t-{int(outage_deadline - time.time())}s buffer_rows={bcount}")

        check("edge daemon survived the outage without crashing", edge_survived_outage)
        check("edge daemon buffered readings to SQLite during outage (not dropped)", saw_buffer_growth)
        check("ingest process still alive after outage", ingest_proc.poll() is None)

        print()
        print("=" * 70)
        print("P1 GATE: restarting mosquitto, waiting for Sync to drain the buffer")
        print("=" * 70)

        docker_compose(docker_exe, "start", "mosquitto")

        drained = False
        drain_deadline = time.time() + DRAIN_TIMEOUT_SECONDS
        while time.time() < drain_deadline:
            bcount = buffer_row_count()
            print(f"  drain: buffer_rows={bcount}")
            if bcount == 0:
                drained = True
                break
            time.sleep(2)
        check(f"SQLite buffer drained to zero within {DRAIN_TIMEOUT_SECONDS}s of mosquitto restart", drained,
              f"final buffer_rows={buffer_row_count()}")

        time.sleep(POST_RECOVERY_SETTLE_SECONDS)

        print()
        print("=" * 70)
        print("P1 GATE: graceful stop + final consistency checks")
        print("=" * 70)

        STOP_REQUEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        STOP_REQUEST_PATH.write_text("stop", encoding="utf-8")

        exited_cleanly = False
        stop_deadline = time.time() + GRACEFUL_STOP_TIMEOUT_SECONDS
        while time.time() < stop_deadline:
            if edge_proc.poll() is not None:
                exited_cleanly = True
                break
            time.sleep(1)
        check("edge daemon exited on its own after graceful-stop request (fully flushed)", exited_cleanly)
        if not exited_cleanly:
            stop_process(edge_proc)

        stats = read_stats()
        generated_total = stats.get("generated_total")
        check("edge daemon stats file present with generated_total", generated_total is not None, str(stats))

        time.sleep(FINAL_INGEST_SETTLE_SECONDS)
        stop_process(ingest_proc)

        with engine.connect() as conn:
            final_readings_count = conn.execute(
                text("SELECT count(*) FROM readings WHERE plant_id = :p"), {"p": PLANT_ID}
            ).scalar()
            dead_letter_count = conn.execute(
                text("SELECT count(*) FROM dead_letter_readings")
            ).scalar()
            distinct_pk_count = conn.execute(
                text("SELECT count(DISTINCT (plant_id, sensor_id, ts)) FROM readings WHERE plant_id = :p"),
                {"p": PLANT_ID},
            ).scalar()

        if generated_total is not None:
            check("zero gaps: Postgres readings count == daemon's generated_total",
                  final_readings_count == generated_total,
                  f"postgres={final_readings_count} generated={generated_total}")
        else:
            check("zero gaps: Postgres readings count == daemon's generated_total", False,
                  "no stats file to compare against")

        check("zero duplicates: distinct (plant_id,sensor_id,ts) count == row count",
              distinct_pk_count == final_readings_count,
              f"distinct={distinct_pk_count} rows={final_readings_count}")

        check("dead_letter_readings is empty", dead_letter_count == 0, f"count={dead_letter_count}")

    finally:
        stop_process(edge_proc)
        stop_process(ingest_proc)
        # Best-effort: make sure mosquitto is back up for anything after this.
        if not service_running(docker_exe, "mosquitto"):
            docker_compose(docker_exe, "start", "mosquitto")

    print()
    print("=" * 70)
    failed = [n for n, ok in results if not ok]
    if failed:
        print(f"P1 GATE: FAIL ({len(failed)}/{len(results)} checks failed)")
        for n in failed:
            print(f"  - {n}")
        print(f"\nLogs: {LOG_DIR}")
        return 1
    print(f"P1 GATE: PASS ({len(results)}/{len(results)} checks passed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
