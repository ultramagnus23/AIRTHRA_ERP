#!/usr/bin/env python
"""P4 nightly archive worker.

For each plant, exports the *prior* UTC day's `readings` rows to a Parquet
file, uploads it to MinIO (S3-compatible object storage), anchors its
sha256 with an OpenTimestamps proof, and records one row in `archive_log`
-- but only after the upload has been re-downloaded and checksum-verified,
so a partial/failed upload can never be recorded as "done".

Raw-data immutability: this worker only ever SELECTs from `readings`. It
never UPDATEs or DELETEs a single row there.

--------------------------------------------------------------------------
Atomicity against S3-style storage (no true atomic rename exists in S3)
--------------------------------------------------------------------------
The upload sequence is:

  1. Write the Parquet file to a local temp file, compute its sha256.
  2. PUT it to a *staging* key: archive/{plant_id}/{day}.parquet.uploading
  3. Server-side COPY that staging object onto the *final* key:
     archive/{plant_id}/{day}.parquet
     S3's CopyObject is a single atomic operation from the reader's point
     of view -- a GET of the final key either 404s (nothing there yet) or
     returns the complete object; there is no way to observe a partially
     written final object. This is the closest available equivalent to a
     POSIX `rename()` on S3-style storage (which has no rename primitive
     at all).
  4. Delete the staging object.
  5. Re-download the *final* object and recompute its sha256; only if it
     matches the sha256 computed in step 1 do we proceed to write the
     archive_log row, with verified=true.

If the process dies or the upload fails at any point before step 5's
checksum match, no archive_log row is ever written for that (day,
plant_id) -- the next run will simply redo the export and overwrite
whatever partial staging object might be left behind (ON CONFLICT DO
UPDATE on the natural key, and stray *.uploading keys are harmless/inert
until cleaned up by a future run touching the same key).

--------------------------------------------------------------------------
OpenTimestamps anchoring -- what's real here and what isn't
--------------------------------------------------------------------------
This submits the archive's sha256 digest to a REAL public OpenTimestamps
calendar server (https://a.pool.opentimestamps.org/digest) over plain
HTTP, using the `opentimestamps` pure-Python library's low-level
`calendar.RemoteCalendar` + `core.timestamp` primitives directly (NOT the
`otsclient`/`ots` CLI -- that CLI eagerly imports `python-bitcoinlib`'s
`bitcoin.rpc`, which in turn does a ctypes `LoadLibrary` for OpenSSL that
is not resolvable on this Windows dev box -- confirmed by actually running
`.venv/Scripts/ots.exe stamp` here, which throws
`TypeError: argument of type 'NoneType' is not iterable` inside
`ctypes.util.find_library`). The lower-level `opentimestamps` package has
no such dependency for *submission*, so calendar submission is genuinely
real, not mocked.

What's NOT done: a submitted digest only gets a "pending" attestation --
the calendar server commits to including it in its next Bitcoin
transaction, but that transaction typically takes hours to confirm and
requires a later `ots upgrade` (which walks the Merkle path, then needs a
Bitcoin block header) to become a complete, independently-verifiable
proof. That upgrade step is NOT run here (it needs Bitcoin block data,
i.e. either a full node or a block explorer call, neither of which this
worker depends on to stay deterministic/fast). The `.ots` proof file this
worker writes is therefore a genuine, real pending-calendar attestation --
verifiable as "yes, this digest was submitted to this calendar at
approximately this time" -- but not yet a chain-anchored complete proof.
If a real calendar submission fails (network/calendar outage), this
worker falls back to writing a clearly-labeled stub proof file instead of
silently pretending success -- see `_build_ots_proof()` below.

Usage:
    .venv/Scripts/python.exe workers/archive_worker.py [--plant-id ID] [--day YYYY-MM-DD]

    --plant-id  Archive only this plant. Default: all plants in `plants`.
    --day       UTC calendar day to archive (readings with ts in
                [day 00:00, day+1 00:00) UTC). Default: yesterday (UTC).

Reads DATABASE_URL and MINIO_* from .env (repo root), same convention as
workers/kpi_worker.py and seed/seed.py. Uses the plain superuser DSN
(bypasses RLS) since this is an internal cross-plant batch job.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import os
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import boto3
from botocore.client import Config as BotoConfig
from dotenv import load_dotenv
import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL is not set (check .env)", file=sys.stderr)
    sys.exit(1)

MINIO_HOST = os.environ.get("MINIO_HOST", "localhost")
MINIO_PORT = os.environ.get("MINIO_PORT", "9000")
MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", f"http://{MINIO_HOST}:{MINIO_PORT}")
MINIO_ROOT_USER = os.environ.get("MINIO_ROOT_USER", "")
MINIO_ROOT_PASSWORD = os.environ.get("MINIO_ROOT_PASSWORD", "")
MINIO_BUCKET = os.environ.get("MINIO_BUCKET", "airthra")

OTS_CALENDAR_URL = os.environ.get("OTS_CALENDAR_URL", "https://a.pool.opentimestamps.org")
OTS_TIMEOUT_S = float(os.environ.get("OTS_TIMEOUT_S", "20"))


def s3_client():
    return boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ROOT_USER,
        aws_secret_access_key=MINIO_ROOT_PASSWORD,
        config=BotoConfig(signature_version="s3v4", s3={"addressing_style": "path"}),
        region_name="us-east-1",
    )


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_day_to_parquet(engine, plant_id: str, day: date, out_path: Path) -> int:
    """Reads readings for [day 00:00, day+1 00:00) UTC for plant_id and
    writes them to a local Parquet file at out_path. Returns row count.
    Read-only against `readings` -- never mutates it."""
    day_start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT ts, plant_id, sensor_id, value, quality_flag
                FROM readings
                WHERE plant_id = :plant_id AND ts >= :day_start AND ts < :day_end
                ORDER BY sensor_id, ts
                """
            ),
            {"plant_id": plant_id, "day_start": day_start, "day_end": day_end},
        ).all()

    ts_col = [r.ts for r in rows]
    plant_col = [r.plant_id for r in rows]
    sensor_col = [r.sensor_id for r in rows]
    value_col = [r.value for r in rows]
    flag_col = [r.quality_flag for r in rows]

    table = pa.table(
        {
            "ts": pa.array(ts_col, type=pa.timestamp("us", tz="UTC")),
            "plant_id": pa.array(plant_col, type=pa.string()),
            "sensor_id": pa.array(sensor_col, type=pa.string()),
            "value": pa.array(value_col, type=pa.float64()),
            "quality_flag": pa.array(flag_col, type=pa.string()),
        }
    )
    pq.write_table(table, out_path)
    return len(rows)


# ---------------------------------------------------------------------------
# OpenTimestamps anchoring (see module docstring)
# ---------------------------------------------------------------------------

def _build_ots_proof(digest_hex: str) -> tuple[bytes, bool]:
    """Returns (proof_bytes, is_real). Tries a real OTS calendar submission
    first; falls back to a clearly-labeled stub only if that genuinely
    fails (network/calendar outage), so a stub is never silently mistaken
    for a real proof."""
    digest = bytes.fromhex(digest_hex)
    try:
        from opentimestamps.calendar import RemoteCalendar
        from opentimestamps.core.timestamp import DetachedTimestampFile, Timestamp
        from opentimestamps.core.op import OpSHA256
        from opentimestamps.core.serialize import BytesSerializationContext

        cal = RemoteCalendar(OTS_CALENDAR_URL, user_agent="airthra-archive-worker")
        calendar_timestamp = cal.submit(digest, timeout=OTS_TIMEOUT_S)

        # Merge the calendar's pending-attestation timestamp into a fresh
        # Timestamp rooted at our digest (mirrors what `ots stamp` does
        # internally before serializing a .ots file).
        root_timestamp = Timestamp(digest)
        root_timestamp.merge(calendar_timestamp)
        dtf = DetachedTimestampFile(OpSHA256(), root_timestamp)

        ctx = BytesSerializationContext()
        dtf.serialize(ctx)
        return ctx.getbytes(), True
    except Exception as exc:  # noqa: BLE001 - network/calendar failure -> documented stub fallback
        stub = (
            b"AIRTHRA-OTS-STUB-PROOF v1\n"
            b"# REAL OpenTimestamps calendar submission failed for this run and\n"
            b"# this is a STUB placeholder, not a cryptographic timestamp proof.\n"
            b"# Reason: " + str(exc).encode("utf-8", "replace") + b"\n"
            b"sha256=" + digest_hex.encode("ascii") + b"\n"
            b"generated_at=" + datetime.now(timezone.utc).isoformat().encode("ascii") + b"\n"
        )
        print(f"[archive_worker] WARNING: OTS calendar submission failed, writing stub proof: {exc}",
              file=sys.stderr)
        return stub, False


# ---------------------------------------------------------------------------
# S3 atomic-upload sequence (see module docstring)
# ---------------------------------------------------------------------------

def upload_atomic(client, local_path: Path, final_key: str, expected_sha256: str) -> bool:
    """Uploads local_path to a staging key, copies it to final_key, deletes
    the staging key, then re-downloads final_key and verifies its sha256.
    Returns True only if the final object's sha256 matches expected_sha256."""
    staging_key = final_key + ".uploading"

    client.upload_file(str(local_path), MINIO_BUCKET, staging_key)

    client.copy_object(
        Bucket=MINIO_BUCKET,
        CopySource={"Bucket": MINIO_BUCKET, "Key": staging_key},
        Key=final_key,
    )
    client.delete_object(Bucket=MINIO_BUCKET, Key=staging_key)

    obj = client.get_object(Bucket=MINIO_BUCKET, Key=final_key)
    downloaded = obj["Body"].read()
    actual_sha256 = sha256_bytes(downloaded)
    return actual_sha256 == expected_sha256


def upload_plain(client, data: bytes, key: str) -> None:
    """Simple (non-atomic-verified) upload for small side-artifacts like the
    .ots proof file, where a partial-write concern doesn't gate a DB row."""
    client.put_object(Bucket=MINIO_BUCKET, Key=key, Body=data)


def public_url(key: str) -> str:
    return f"{MINIO_ENDPOINT}/{MINIO_BUCKET}/{key}"


# ---------------------------------------------------------------------------
# archive_log
# ---------------------------------------------------------------------------

def upsert_archive_log(engine, day: date, plant_id: str, parquet_url: str,
                        sha256_hex: str, ots_proof_url: str, verified: bool) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO archive_log (day, plant_id, parquet_url, sha256, ots_proof_url, verified)
                VALUES (:day, :plant_id, :parquet_url, :sha256, :ots_proof_url, :verified)
                ON CONFLICT (day, plant_id) DO UPDATE SET
                    parquet_url = EXCLUDED.parquet_url,
                    sha256 = EXCLUDED.sha256,
                    ots_proof_url = EXCLUDED.ots_proof_url,
                    verified = EXCLUDED.verified
                """
            ),
            {
                "day": day,
                "plant_id": plant_id,
                "parquet_url": parquet_url,
                "sha256": sha256_hex,
                "ots_proof_url": ots_proof_url,
                "verified": verified,
            },
        )


def archive_plant_day(engine, client, plant_id: str, day: date) -> dict:
    """Runs the full export -> upload -> verify -> ots -> archive_log
    sequence for one (plant_id, day). Returns a summary dict. Raises on
    unrecoverable failure (caller decides whether to continue with other
    plants)."""
    with tempfile.TemporaryDirectory(prefix="airthra_archive_") as tmpdir:
        local_parquet = Path(tmpdir) / f"{plant_id}_{day.isoformat()}.parquet"
        row_count = export_day_to_parquet(engine, plant_id, day, local_parquet)

        if row_count == 0:
            print(f"[archive_worker] {plant_id} {day}: 0 readings rows, skipping upload "
                  f"(nothing to archive)")
            return {"plant_id": plant_id, "day": day.isoformat(), "row_count": 0, "skipped": True}

        digest_hex = sha256_file(local_parquet)
        final_key = f"archive/{plant_id}/{day.isoformat()}.parquet"

        verified = upload_atomic(client, local_parquet, final_key, digest_hex)
        if not verified:
            raise RuntimeError(
                f"upload verification FAILED for {plant_id} {day}: re-downloaded object's "
                f"sha256 did not match the local file's sha256 -- archive_log row NOT written"
            )

        ots_bytes, ots_is_real = _build_ots_proof(digest_hex)
        ots_key = final_key + ".ots"
        upload_plain(client, ots_bytes, ots_key)

        parquet_url = public_url(final_key)
        ots_proof_url = public_url(ots_key)

        upsert_archive_log(engine, day, plant_id, parquet_url, digest_hex, ots_proof_url, verified=True)

        print(f"[archive_worker] {plant_id} {day}: {row_count} rows, sha256={digest_hex[:16]}..., "
              f"uploaded+verified, ots_real={ots_is_real} -> {parquet_url}")
        return {
            "plant_id": plant_id,
            "day": day.isoformat(),
            "row_count": row_count,
            "sha256": digest_hex,
            "parquet_url": parquet_url,
            "ots_proof_url": ots_proof_url,
            "ots_is_real": ots_is_real,
            "verified": True,
            "skipped": False,
        }


def ensure_bucket(client) -> None:
    try:
        client.head_bucket(Bucket=MINIO_BUCKET)
    except Exception:
        client.create_bucket(Bucket=MINIO_BUCKET)


def main() -> int:
    parser = argparse.ArgumentParser(description="Airthra P4 nightly archive worker")
    parser.add_argument("--plant-id", help="Archive only this plant (default: all plants)")
    parser.add_argument("--day", help="UTC day to archive, YYYY-MM-DD (default: yesterday UTC)")
    args = parser.parse_args()

    if args.day:
        day = date.fromisoformat(args.day)
    else:
        day = (datetime.now(timezone.utc) - timedelta(days=1)).date()

    engine = create_engine(DATABASE_URL, future=True)
    client = s3_client()
    ensure_bucket(client)

    if args.plant_id:
        plant_ids = [args.plant_id]
    else:
        with engine.connect() as conn:
            plant_ids = [r[0] for r in conn.execute(text("SELECT plant_id FROM plants ORDER BY plant_id")).fetchall()]

    print(f"[archive_worker] archiving day={day.isoformat()} for {len(plant_ids)} plant(s)")

    failures = []
    results = []
    for plant_id in plant_ids:
        try:
            results.append(archive_plant_day(engine, client, plant_id, day))
        except Exception as exc:  # noqa: BLE001 - one plant's failure must not silently vanish or kill the rest
            print(f"[archive_worker] ERROR archiving {plant_id} {day}: {exc}", file=sys.stderr)
            failures.append((plant_id, str(exc)))

    print()
    print(f"[archive_worker] done: {len(results)} plant-days processed, {len(failures)} failed")
    if failures:
        for plant_id, err in failures:
            print(f"  - {plant_id}: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
