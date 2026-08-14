#!/usr/bin/env python
"""P0 gate verification.

Proves two things the P0 spec requires before P0 is considered done:

  1. Migrations are idempotent: `alembic upgrade head` run twice in a row
     succeeds cleanly both times (no errors, second run is a no-op).
  2. Row-Level Security actually isolates tenants:
       - airthra_tenant, scoped to plant A via `app.current_plant_ids`,
         selecting a row that belongs to plant B -> zero rows.
       - airthra_global (BYPASSRLS) issuing the same query -> succeeds /
         sees the row.

Prints a clear PASS/FAIL per check and exits non-zero if anything fails.
Run from the repo root: `python tests/p0_gate.py`
(tests/p0_gate.ps1 is a thin wrapper for PowerShell users).
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
except ImportError:
    pass

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

DATABASE_URL = os.environ.get("DATABASE_URL")
PG_TENANT_ROLE = os.environ.get("PG_TENANT_ROLE", "airthra_tenant")
PG_TENANT_PASSWORD = os.environ.get("PG_TENANT_PASSWORD", "change_me_dev_only_tenant")
PG_GLOBAL_ROLE = os.environ.get("PG_GLOBAL_ROLE", "airthra_global")
PG_GLOBAL_PASSWORD = os.environ.get("PG_GLOBAL_PASSWORD", "change_me_dev_only_global")

results = []  # (name, bool)


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok))
    status = "PASS" if ok else "FAIL"
    line = f"[{status}] {name}"
    if detail:
        line += f" - {detail}"
    print(line)


def role_url(role: str, password: str):
    url = make_url(DATABASE_URL)
    return url.set(username=role, password=password)


def main() -> int:
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL not set (check .env)", file=sys.stderr)
        return 2

    print("=" * 70)
    print("P0 GATE: migration idempotency")
    print("=" * 70)

    env = os.environ.copy()
    env["DATABASE_URL"] = DATABASE_URL
    for i in (1, 2):
        proc = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=ROOT, env=env, capture_output=True, text=True,
        )
        ok = proc.returncode == 0
        check(f"alembic upgrade head (run {i}/2)", ok,
              detail="" if ok else proc.stderr.strip().splitlines()[-1] if proc.stderr else "non-zero exit")
        if not ok:
            print(proc.stdout)
            print(proc.stderr)

    print()
    print("=" * 70)
    print("P0 GATE: row-level security")
    print("=" * 70)

    admin_engine = create_engine(DATABASE_URL, future=True)
    plant_a = "gate_plant_a"
    plant_b = "gate_plant_b"
    sensor_id = "gate_sensor"

    with admin_engine.begin() as conn:
        for pid in (plant_a, plant_b):
            conn.execute(
                text("INSERT INTO plants (plant_id, name) VALUES (:p, :p) ON CONFLICT (plant_id) DO NOTHING"),
                {"p": pid},
            )
        conn.execute(
            text(
                """
                INSERT INTO sensors (plant_id, sensor_id, tag, kind, unit)
                VALUES (:p, :s, 'gate_tag', 'flow', 'm3/h')
                ON CONFLICT (plant_id, sensor_id) DO NOTHING
                """
            ),
            {"p": plant_b, "s": sensor_id},
        )

    tenant_engine = create_engine(role_url(PG_TENANT_ROLE, PG_TENANT_PASSWORD), future=True)
    global_engine = create_engine(role_url(PG_GLOBAL_ROLE, PG_GLOBAL_PASSWORD), future=True)

    # airthra_tenant scoped to plant_a must NOT see plant_b's sensor row.
    with tenant_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_plant_ids', :p, false)"), {"p": plant_a})
        rows = conn.execute(
            text("SELECT * FROM sensors WHERE plant_id = :p AND sensor_id = :s"),
            {"p": plant_b, "s": sensor_id},
        ).fetchall()
    check(
        "airthra_tenant (scoped to plant A) cannot see plant B's row",
        len(rows) == 0,
        f"got {len(rows)} row(s), expected 0",
    )

    # airthra_tenant scoped to plant_a MUST see plant_a's own rows (sanity -
    # proves the policy isn't just denying everything).
    with tenant_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_plant_ids', :p, false)"), {"p": plant_a})
        rows = conn.execute(
            text("SELECT * FROM plants WHERE plant_id = :p"), {"p": plant_a}
        ).fetchall()
    check(
        "airthra_tenant (scoped to plant A) CAN see plant A's own row",
        len(rows) == 1,
        f"got {len(rows)} row(s), expected 1",
    )

    # airthra_global (BYPASSRLS) must see plant_b's row regardless of scope.
    with global_engine.begin() as conn:
        rows = conn.execute(
            text("SELECT * FROM sensors WHERE plant_id = :p AND sensor_id = :s"),
            {"p": plant_b, "s": sensor_id},
        ).fetchall()
    check(
        "airthra_global (BYPASSRLS) can see plant B's row",
        len(rows) == 1,
        f"got {len(rows)} row(s), expected 1",
    )

    with admin_engine.begin() as conn:
        conn.execute(text("DELETE FROM sensors WHERE plant_id IN (:a, :b)"), {"a": plant_a, "b": plant_b})
        conn.execute(text("DELETE FROM plants WHERE plant_id IN (:a, :b)"), {"a": plant_a, "b": plant_b})

    print()
    print("=" * 70)
    failed = [n for n, ok in results if not ok]
    if failed:
        print(f"P0 GATE: FAIL ({len(failed)}/{len(results)} checks failed)")
        for n in failed:
            print(f"  - {n}")
        return 1
    print(f"P0 GATE: PASS ({len(results)}/{len(results)} checks passed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
