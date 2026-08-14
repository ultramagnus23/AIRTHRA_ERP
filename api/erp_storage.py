"""P5 object storage: MinIO (S3-compatible), reusing the platform-wide
"store url + sha256 + metadata only, never blobs in Postgres" convention
(see archive_log, drawings.file_url/sha256, quotations.file_url/sha256 etc
in migrations/versions/0001_initial_schema.py).

New module, independent of api/config.py (deliberately - avoids touching a
file other phases may also be editing). Reads MINIO_* straight from the
repo-root .env, same load_dotenv pattern api/config.py uses.
"""
from __future__ import annotations

import hashlib
import os

import boto3
from botocore.client import Config as BotoConfig
from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT, ".env"))

MINIO_HOST = os.environ.get("MINIO_HOST", "localhost")
MINIO_PORT = os.environ.get("MINIO_PORT", "9000")
MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", f"http://{MINIO_HOST}:{MINIO_PORT}")
MINIO_ROOT_USER = os.environ.get("MINIO_ROOT_USER", "airthra_minio")
MINIO_ROOT_PASSWORD = os.environ.get("MINIO_ROOT_PASSWORD", "change_me_dev_only")
MINIO_BUCKET = os.environ.get("MINIO_BUCKET", "airthra")


def _client():
    return boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ROOT_USER,
        aws_secret_access_key=MINIO_ROOT_PASSWORD,
        config=BotoConfig(signature_version="s3v4"),
        region_name="us-east-1",
    )


class UploadFailed(RuntimeError):
    pass


def upload_bytes(key: str, data: bytes, content_type: str) -> dict:
    """Write-then-verify atomic upload: PUT the object, then HEAD it back
    and compare ETag-derived / recomputed sha256 against what we intended
    to store, so a truncated/corrupted upload is never silently reported
    as success. Returns {"url", "sha256", "bytes"}.
    """
    sha256 = hashlib.sha256(data).hexdigest()
    client = _client()

    try:
        client.put_object(
            Bucket=MINIO_BUCKET,
            Key=key,
            Body=data,
            ContentType=content_type,
            Metadata={"sha256": sha256},
        )
    except Exception as exc:  # noqa: BLE001 - surfaced as a clear 502 by the caller
        raise UploadFailed(f"MinIO PUT failed for key '{key}': {exc}") from exc

    # Verify: re-download and hash. Small PDFs (POs) - the extra round trip
    # is cheap and is exactly the "verify upload" the P5 spec asks for.
    try:
        got = client.get_object(Bucket=MINIO_BUCKET, Key=key)
        body = got["Body"].read()
    except Exception as exc:  # noqa: BLE001
        raise UploadFailed(f"MinIO verify-read failed for key '{key}': {exc}") from exc

    if hashlib.sha256(body).hexdigest() != sha256 or len(body) != len(data):
        # Best-effort cleanup of the bad object before raising.
        try:
            client.delete_object(Bucket=MINIO_BUCKET, Key=key)
        except Exception:  # noqa: BLE001
            pass
        raise UploadFailed(f"MinIO upload verification mismatch for key '{key}'")

    url = f"{MINIO_ENDPOINT}/{MINIO_BUCKET}/{key}"
    return {"url": url, "sha256": sha256, "bytes": len(data)}


def delete_key(key: str) -> None:
    try:
        _client().delete_object(Bucket=MINIO_BUCKET, Key=key)
    except Exception:  # noqa: BLE001 - best-effort cleanup only
        pass
