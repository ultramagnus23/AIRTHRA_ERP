#!/usr/bin/env python
"""P4 restore drill.

Simulates "restore an archived day of readings from backup on a clean
machine": looks up an `archive_log` row, downloads its Parquet object back
from MinIO (never trusting anything cached locally from the archive run),
verifies its sha256 against the DB record, and verifies the Parquet file is
actually readable with sane row counts/columns. This is the P4 gate's
restore-drill check.

Usage:
    .venv/Scripts/python.exe scripts/restore_drill.py --plant-id goa_pilot_01 --day 2026-08-13
    .venv/Scripts/python.exe scripts/restore_drill.py --plant-id goa_pilot_01   # latest archived day for that plant
    .venv/Scripts/python.exe scripts/restore_drill.py                          # latest archived (day, plant) row overall

Prints PASS/FAIL per check and exits non-zero on any failure.
Reads DATABASE_URL / MINIO_* from .env (repo root), same as
workers/archive_worker.py.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, text  # noqa: E402

from workers.archive_worker import (  # noqa: E402
    DATABASE_URL,
    MINIO_BUCKET,
    s3_client,
    sha256_bytes,
)

import pyarrow.parquet as pq  # noqa: E402

EXPECTED_COLUMNS = {"ts", "plant_id", "sensor_id", "value", "quality_flag"}

results = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, ok))
    status = "PASS" if ok else "FAIL"
    line = f"[{status}] {name}"
    if detail:
        line += f" - {detail}"
    print(line)
    return ok


def key_from_url(url: str) -> str:
    """archive_worker.public_url() builds {endpoint}/{bucket}/{key}; strip
    the endpoint+bucket prefix back off to get the raw object key."""
    marker = f"/{MINIO_BUCKET}/"
    idx = url.find(marker)
    if idx == -1:
        raise ValueError(f"could not extract object key from URL: {url}")
    return url[idx + len(marker):]


def find_archive_row(engine, plant_id: str | None, day: str | None):
    where = []
    params = {}
    if plant_id:
        where.append("plant_id = :plant_id")
        params["plant_id"] = plant_id
    if day:
        where.append("day = :day")
        params["day"] = day
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    with engine.connect() as conn:
        row = conn.execute(
            text(
                f"""
                SELECT day, plant_id, parquet_url, sha256, ots_proof_url, verified
                FROM archive_log
                {where_sql}
                ORDER BY day DESC
                LIMIT 1
                """
            ),
            params,
        ).mappings().first()
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description="Airthra P4 restore drill")
    parser.add_argument("--plant-id", help="Restrict to this plant (default: any)")
    parser.add_argument("--day", help="Restrict to this UTC day, YYYY-MM-DD (default: most recent)")
    args = parser.parse_args()

    if not DATABASE_URL:
        print("ERROR: DATABASE_URL is not set (check .env)", file=sys.stderr)
        return 2

    engine = create_engine(DATABASE_URL, future=True)
    client = s3_client()

    print("=" * 70)
    print("P4 RESTORE DRILL")
    print("=" * 70)

    row = find_archive_row(engine, args.plant_id, args.day)
    found = check("archive_log row found", row is not None,
                   f"plant_id={args.plant_id!r} day={args.day!r}")
    if not found:
        print("\nRESTORE DRILL: FAIL (no matching archive_log row)")
        return 1

    print(f"  archived row: day={row['day']} plant_id={row['plant_id']} "
          f"sha256={row['sha256'][:16]}... verified_at_archive_time={row['verified']}")

    check("archive_log.verified flag is true (set only after archive-time checksum verify)",
          bool(row["verified"]))

    try:
        key = key_from_url(row["parquet_url"])
        obj = client.get_object(Bucket=MINIO_BUCKET, Key=key)
        data = obj["Body"].read()
        download_ok = True
    except Exception as exc:  # noqa: BLE001
        print(f"  ERROR downloading object: {exc}", file=sys.stderr)
        data = b""
        download_ok = False
    check("Parquet object downloaded from MinIO (fresh, not locally cached)", download_ok,
          f"key={key if download_ok else '?'}")
    if not download_ok:
        print("\nRESTORE DRILL: FAIL (download failed)")
        return 1

    actual_sha256 = sha256_bytes(data)
    check("downloaded object's sha256 matches archive_log.sha256", actual_sha256 == row["sha256"],
          f"downloaded={actual_sha256[:16]}... recorded={row['sha256'][:16]}...")

    with tempfile.TemporaryDirectory(prefix="airthra_restore_drill_") as tmpdir:
        local_path = Path(tmpdir) / "restored.parquet"
        local_path.write_bytes(data)

        try:
            table = pq.read_table(local_path)
            readable = True
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR reading Parquet: {exc}", file=sys.stderr)
            table = None
            readable = False
        check("Parquet file is readable (well-formed)", readable)

        if readable:
            columns = set(table.column_names)
            check("Parquet columns match expected schema", columns == EXPECTED_COLUMNS,
                  f"got={sorted(columns)} expected={sorted(EXPECTED_COLUMNS)}")
            row_count = table.num_rows
            check("Parquet row count is sane (> 0)", row_count > 0, f"row_count={row_count}")

            if row_count > 0:
                plant_ids_in_file = set(table.column("plant_id").to_pylist())
                check("all rows belong to the archived plant_id",
                      plant_ids_in_file == {row["plant_id"]},
                      f"found plant_ids={plant_ids_in_file}")

    # Best-effort: also confirm the OTS proof object exists (not gating the
    # restore-drill PASS/FAIL, since a missing/stub OTS proof doesn't affect
    # whether the raw data itself is restorable -- but worth surfacing).
    if row["ots_proof_url"]:
        try:
            ots_key = key_from_url(row["ots_proof_url"])
            ots_obj = client.get_object(Bucket=MINIO_BUCKET, Key=ots_key)
            ots_bytes = ots_obj["Body"].read()
            is_stub = ots_bytes.startswith(b"AIRTHRA-OTS-STUB-PROOF")
            print(f"  [info] OTS proof object present ({len(ots_bytes)} bytes, "
                  f"{'STUB fallback' if is_stub else 'real calendar submission'})")
        except Exception as exc:  # noqa: BLE001
            print(f"  [info] OTS proof object could not be fetched (non-gating): {exc}")

    print()
    print("=" * 70)
    failed = [n for n, ok in results if not ok]
    if failed:
        print(f"RESTORE DRILL: FAIL ({len(failed)}/{len(results)} checks failed)")
        for n in failed:
            print(f"  - {n}")
        return 1
    print(f"RESTORE DRILL: PASS ({len(results)}/{len(results)} checks passed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
