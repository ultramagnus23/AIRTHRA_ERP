"""P7 §5.3 POST /admin/mrv_export/{plant_id}?period=YYYY-MM - MRV export.

Produces a ZIP, uploaded to MinIO (documented choice: streaming a
potentially large multi-day export directly in the HTTP response is more
fragile for a first cut - MinIO already is this project's object store
for exactly this kind of artifact, per workers/archive_worker.py's
`archive/` convention, so `mrv/{plant_id}/{period}.zip` follows the same
pattern; the endpoint returns the object's URL + sha256 rather than the
bytes themselves), containing:

  - `readings/{day}.parquet` for every day in the period. Reuses
    workers/archive_worker.py's `archive_log` rows (parquet_url, sha256)
    when they exist for that (day, plant_id) - downloads the real
    archived object from MinIO and verifies its sha256 against
    archive_log.sha256 before it goes in the ZIP (abort, don't
    silently include unverified bytes, if that check fails). If P4
    hasn't archived a given day yet (archive_log has no row), this
    endpoint generates that day's parquet itself inline (reusing
    workers/archive_worker.export_day_to_parquet's read-only query
    against `readings`, never blocking on P4) and marks it
    "synthesized" in manifest.json rather than pretending it's an
    archive_log-backed artifact.
  - `calibration/manifest.json` - `sensors.calib_doc_url`/`calib_date`
    per sensor for the plant (P0 schema has no field to store fetched
    document bytes are not embedded - the seeded manifest doesn't
    populate calib_doc_url at all in this phase, so this is normally an
    empty/URL-only list; documented rather than silently omitted).
  - `ots/{day}.parquet.ots` for every day that has a real
    archive_log.ots_proof_url - downloaded from MinIO and included
    verbatim. Days with no OTS proof (synthesized days, or archive_log
    rows written before OTS anchoring succeeded) are simply absent, and
    noted as such in manifest.json.
  - `manifest.json` at the ZIP root: per-day source (archive_log|
    synthesized), sha256, and the calibration-doc / OTS-proof info
    above, so a consumer can audit exactly what's real vs. synthesized
    without needing DB access.
"""
from __future__ import annotations

import hashlib
import io
import json
import tempfile
import zipfile
from datetime import date, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..deps import CurrentUser, db_session, get_current_user
from .admin_common import require_global_or_department


def require_global(user: CurrentUser) -> None:
    require_global_or_department(user, "logistics")
from workers.archive_worker import (
    MINIO_BUCKET,
    ensure_bucket,
    public_url,
    s3_client,
    sha256_bytes,
    upload_atomic,
)
from workers.billing_worker import month_bounds

router = APIRouter(prefix="/admin", tags=["admin-mrv"])


def _key_from_url(url: str) -> str:
    marker = f"/{MINIO_BUCKET}/"
    idx = url.find(marker)
    if idx == -1:
        raise ValueError(f"cannot derive object key from url '{url}' (bucket '{MINIO_BUCKET}' not found in it)")
    return url[idx + len(marker):]


def _days_in_period(period: str) -> list[date]:
    start, end = month_bounds(period)
    days = []
    d = start.date()
    while d < end.date():
        days.append(d)
        d += timedelta(days=1)
    return days


async def _export_day_synth(conn: AsyncConnection, plant_id: str, day: date) -> bytes:
    """Inline read-only parquet export for a day with no archive_log row
    yet, mirroring workers/archive_worker.export_day_to_parquet's query
    shape but async (this endpoint already runs on an async DB
    connection) and returning bytes instead of writing to a fixed path."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    from datetime import datetime, timezone

    day_start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)
    rows = (
        await conn.execute(
            text(
                """
                SELECT ts, plant_id, sensor_id, value, quality_flag
                FROM readings
                WHERE plant_id = :plant_id AND ts >= :day_start AND ts < :day_end
                ORDER BY sensor_id, ts
                """
            ),
            {"plant_id": plant_id, "day_start": day_start, "day_end": day_end},
        )
    ).mappings().all()

    table = pa.table(
        {
            "ts": pa.array([r["ts"] for r in rows], type=pa.timestamp("us", tz="UTC")),
            "plant_id": pa.array([r["plant_id"] for r in rows], type=pa.string()),
            "sensor_id": pa.array([r["sensor_id"] for r in rows], type=pa.string()),
            "value": pa.array([r["value"] for r in rows], type=pa.float64()),
            "quality_flag": pa.array([r["quality_flag"] for r in rows], type=pa.string()),
        }
    )
    buf = io.BytesIO()
    pq.write_table(table, buf)
    return buf.getvalue(), len(rows)


@router.post("/mrv_export/{plant_id}")
async def mrv_export(
    plant_id: str,
    period: str = Query(..., description="YYYY-MM"),
    user: CurrentUser = Depends(get_current_user),
    conn: AsyncConnection = Depends(db_session),
):
    require_global(user)

    plant = (
        await conn.execute(text("SELECT plant_id, name FROM plants WHERE plant_id = :p"), {"p": plant_id})
    ).mappings().first()
    if plant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"plant '{plant_id}' not found")

    try:
        days = _days_in_period(period)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="period must look like 'YYYY-MM'")

    client = s3_client()
    ensure_bucket(client)

    manifest: dict = {"plant_id": plant_id, "period": period, "days": {}, "calibration": [], "ots": {}}
    day_files: dict[str, bytes] = {}
    ots_files: dict[str, bytes] = {}

    for day in days:
        day_iso = day.isoformat()
        archived = (
            await conn.execute(
                text(
                    """
                    SELECT parquet_url, sha256, ots_proof_url, verified
                    FROM archive_log WHERE day = :day AND plant_id = :plant_id
                    """
                ),
                {"day": day, "plant_id": plant_id},
            )
        ).mappings().first()

        if archived is not None:
            key = _key_from_url(archived["parquet_url"])
            obj = client.get_object(Bucket=MINIO_BUCKET, Key=key)
            data = obj["Body"].read()
            actual_sha = sha256_bytes(data)
            if actual_sha != archived["sha256"]:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=(
                        f"archive_log sha256 mismatch for {plant_id} {day_iso}: "
                        f"recorded={archived['sha256']} actual={actual_sha} - MRV export aborted, "
                        f"nothing uploaded"
                    ),
                )
            day_files[day_iso] = data
            manifest["days"][day_iso] = {"source": "archive_log", "sha256": actual_sha, "row_count": None}

            if archived["ots_proof_url"]:
                try:
                    ots_key = _key_from_url(archived["ots_proof_url"])
                    ots_obj = client.get_object(Bucket=MINIO_BUCKET, Key=ots_key)
                    ots_files[day_iso] = ots_obj["Body"].read()
                    manifest["ots"][day_iso] = "included"
                except Exception as exc:  # noqa: BLE001 - degrade, don't fail the whole export over one OTS fetch
                    manifest["ots"][day_iso] = f"unavailable ({exc})"
            else:
                manifest["ots"][day_iso] = "not_anchored"
        else:
            data, row_count = await _export_day_synth(conn, plant_id, day)
            actual_sha = sha256_bytes(data)
            day_files[day_iso] = data
            manifest["days"][day_iso] = {"source": "synthesized", "sha256": actual_sha, "row_count": row_count}
            manifest["ots"][day_iso] = "not_available_synthesized"

    sensors = (
        await conn.execute(
            text(
                "SELECT sensor_id, tag, calib_date, calib_doc_url FROM sensors WHERE plant_id = :p ORDER BY sensor_id"
            ),
            {"p": plant_id},
        )
    ).mappings().all()
    manifest["calibration"] = [
        {
            "sensor_id": s["sensor_id"],
            "tag": s["tag"],
            "calib_date": s["calib_date"].isoformat() if s["calib_date"] else None,
            "calib_doc_url": s["calib_doc_url"],
        }
        for s in sensors
    ]

    with tempfile.TemporaryDirectory(prefix="airthra_mrv_") as tmpdir:
        zip_path = Path(tmpdir) / f"{plant_id}_{period}_mrv.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for day_iso, data in day_files.items():
                zf.writestr(f"readings/{day_iso}.parquet", data)
            for day_iso, data in ots_files.items():
                zf.writestr(f"ots/{day_iso}.parquet.ots", data)
            zf.writestr("calibration/manifest.json", json.dumps(manifest["calibration"], indent=2))
            zf.writestr("manifest.json", json.dumps(manifest, indent=2, default=str))

        digest_hex = hashlib.sha256(zip_path.read_bytes()).hexdigest()
        final_key = f"mrv/{plant_id}/{period}.zip"
        verified = upload_atomic(client, zip_path, final_key, digest_hex)
        if not verified:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="MRV ZIP upload verification failed - re-downloaded object's sha256 did not match, nothing recorded",
            )
        zip_url = public_url(final_key)

    return {
        "plant_id": plant_id,
        "plant_name": plant["name"],
        "period": period,
        "zip_url": zip_url,
        "zip_sha256": digest_hex,
        "day_count": len(days),
        "manifest": manifest,
    }
