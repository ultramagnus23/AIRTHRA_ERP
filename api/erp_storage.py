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


# Presigned link lifetime. Short enough that a leaked URL in a log, a
# referrer header or a forwarded email expires quickly; long enough for a
# human to actually click it after the page renders.
PRESIGN_EXPIRY_S = int(os.environ.get("MINIO_PRESIGN_EXPIRY_S", "900"))


def presigned_url(key: str, expires_s: int | None = None) -> str:
    """Time-limited download URL for a private object.

    The bucket is no longer anonymously readable (it was provisioned with
    `mc anonymous set download`, which made every tenant's PO PDFs,
    drawings and invoices fetchable by anyone who could guess or obtain an
    object key - see AUDIT.md 2.1). Object keys are structured rather than
    random, so enumeration was plausible.

    The `url` returned by upload_bytes is therefore an IDENTIFIER, not a
    fetchable link. Anything handing a download to a browser must mint one
    of these instead, behind the same auth check that protects the record
    the object belongs to.
    """
    return _client().generate_presigned_url(
        "get_object",
        Params={"Bucket": MINIO_BUCKET, "Key": key},
        ExpiresIn=expires_s or PRESIGN_EXPIRY_S,
    )


def key_from_url(url: str) -> str | None:
    """Recover the object key from a stored file_url. Returns None if the
    URL doesn't belong to this bucket, so a caller can't be tricked into
    presigning something outside it."""
    prefix = f"{MINIO_ENDPOINT}/{MINIO_BUCKET}/"
    return url[len(prefix):] if url.startswith(prefix) else None


def delete_key(key: str) -> None:
    """Best-effort object deletion, used by DELETE /admin/documents/{id}
    (api/routers/admin_documents.py). Deliberately does not raise: the DB
    row is the source of truth for "does this document exist" and is
    already gone by the time this is called, so a storage-side failure
    here means an orphaned object, not a user-visible inconsistency - see
    that endpoint's docstring for why the DB delete happens first."""
    try:
        _client().delete_object(Bucket=MINIO_BUCKET, Key=key)
    except Exception:  # noqa: BLE001 - best-effort cleanup only
        pass
