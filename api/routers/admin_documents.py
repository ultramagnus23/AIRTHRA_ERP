"""Document management: upload/list/delete files attached to any entity.

Generic by design (entity_type + entity_id, migration 0009_documents) so
the same three endpoints serve a plant's compliance certificate, a
contract's signed PDF, a vendor's ISO certification, or a BOM's
supporting spec sheet - one system instead of a bespoke upload endpoint
per table.

This is the FIRST genuine user-file-upload endpoint in the codebase.
Every prior upload (POs, quotations, drawings) is the API server itself
generating a PDF and pushing it to storage - never a browser sending
arbitrary bytes. That distinction matters for what has to be validated
here and nowhere else in this codebase: file size, content-type,
and which entity_id actually exists before attaching a document to it.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from .. import erp_storage
from ..deps import CurrentUser, db_session, get_current_user
from .admin_common import require_global, require_global_admin

router = APIRouter(prefix="/admin/documents", tags=["admin-documents"])

# Generous enough for a scanned certificate or a drawing PDF, small enough
# that an authenticated-but-careless upload can't fill the disk. MinIO
# itself has no opinion on this; it's a deliberate application-level cap.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

# entity_type -> (table, id column, id is uuid?). Mirrors migration
# 0009_documents's CHECK constraint exactly - if a type is added there,
# it must be added here too, or every upload against it will 500 at the
# existence check rather than a clean 422.
_ENTITY_TABLES: dict[str, tuple[str, str]] = {
    "plant": ("plants", "plant_id"),
    "contract": ("contracts", "contract_id"),
    "vendor": ("vendors", "id"),
    "purchase_order": ("pos", "id"),
    "bom": ("boms", "id"),
    "invoice": ("invoices", "invoice_id"),
    "fabrication_job": ("fabrication_jobs", "id"),
    "unit_serial": ("unit_serials", "serial"),
    "user": ("users", "user_id"),
    "company": ("company", "id"),
}

_DOC_COLS = "document_id, entity_type, entity_id, filename, content_type, object_key, sha256, bytes, notes, uploaded_by, uploaded_at"


async def _assert_entity_exists(conn: AsyncConnection, entity_type: str, entity_id: str) -> None:
    if entity_type not in _ENTITY_TABLES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"unknown entity_type '{entity_type}'")
    table, id_col = _ENTITY_TABLES[entity_type]
    found = (await conn.execute(text(f"SELECT 1 FROM {table} WHERE {id_col} = :id"), {"id": entity_id})).first()
    if not found:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"no {entity_type} with id '{entity_id}' - cannot attach a document to it",
        )


@router.get("")
async def list_documents(
    entity_type: str | None = Query(default=None),
    entity_id: str | None = Query(default=None),
    user: CurrentUser = Depends(get_current_user),
    conn: AsyncConnection = Depends(db_session),
):
    require_global(user)
    if bool(entity_type) != bool(entity_id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="entity_type and entity_id must be given together")

    where = "WHERE entity_type = :entity_type AND entity_id = :entity_id" if entity_type else ""
    rows = (
        await conn.execute(
            text(
                f"""
                SELECT d.{_DOC_COLS.replace(', ', ', d.')}, u.email AS uploaded_by_email
                FROM documents d
                LEFT JOIN users u ON u.user_id = d.uploaded_by
                {where}
                ORDER BY d.uploaded_at DESC
                """
            ),
            {"entity_type": entity_type, "entity_id": entity_id} if entity_type else {},
        )
    ).mappings().all()

    documents = []
    for r in rows:
        d = dict(r)
        d["download_url"] = erp_storage.presigned_url(d.pop("object_key"))
        documents.append(d)
    return {"documents": documents}


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_document(
    entity_type: str = Form(...),
    entity_id: str = Form(...),
    notes: str | None = Form(default=None),
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
    conn: AsyncConnection = Depends(db_session),
):
    require_global_admin(user)
    await _assert_entity_exists(conn, entity_type, entity_id)

    data = await file.read()
    if len(data) == 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="uploaded file is empty")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"file is {len(data)} bytes, exceeds the {MAX_UPLOAD_BYTES} byte limit",
        )

    # object_key includes the document_id up front so two uploads of a
    # file with the same name can never collide - generated here (not by
    # the DB default) because upload_bytes needs the final key before the
    # row exists.
    document_id = str(uuid.uuid4())
    safe_name = "".join(c for c in file.filename or "upload" if c.isalnum() or c in "._- ")[:200]
    object_key = f"documents/{entity_type}/{entity_id}/{document_id}_{safe_name}"

    try:
        result = erp_storage.upload_bytes(object_key, data, file.content_type or "application/octet-stream")
    except erp_storage.UploadFailed as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    row = (
        await conn.execute(
            text(
                f"""
                INSERT INTO documents
                    (document_id, entity_type, entity_id, filename, content_type,
                     object_key, sha256, bytes, notes, uploaded_by)
                VALUES
                    (:document_id, :entity_type, :entity_id, :filename, :content_type,
                     :object_key, :sha256, :bytes, :notes, :uploaded_by)
                RETURNING {_DOC_COLS}
                """
            ),
            {
                "document_id": document_id,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "filename": file.filename or safe_name,
                "content_type": file.content_type or "application/octet-stream",
                "object_key": object_key,
                "sha256": result["sha256"],
                "bytes": result["bytes"],
                "notes": notes,
                "uploaded_by": user.user_id,
            },
        )
    ).mappings().first()

    d = dict(row)
    d["download_url"] = erp_storage.presigned_url(d.pop("object_key"))
    return d


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: str,
    user: CurrentUser = Depends(get_current_user),
    conn: AsyncConnection = Depends(db_session),
):
    require_global_admin(user)
    row = (
        await conn.execute(text("SELECT object_key FROM documents WHERE document_id = :id"), {"id": document_id})
    ).mappings().first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="document not found")

    # DB row goes first, then storage: if the DELETE FROM MinIO fails or
    # the process dies between the two, the failure mode is an orphaned
    # object nobody links to (harmless, cleanable later) rather than a
    # document row that "exists" but 404s on download.
    await conn.execute(text("DELETE FROM documents WHERE document_id = :id"), {"id": document_id})
    erp_storage.delete_key(row["object_key"])
