"""Offtake: product batches, QC, Certificate of Analysis, buyer
allocation, dispatch. Closes enterprise spec Module 04.

Buyers mirror api/routers/erp_vendors.py's shape and conventions exactly
(same columns, same simple CRUD) - a buyer is a vendor in every
structural sense except which direction goods/money move.

Batch lifecycle is linear and enforced both here and by CHECK constraints
in the table itself (migration 0011_offtake), so a bug in this router
can't produce an inconsistent row even if it tried:

    produced --QC pass--> (still 'produced', qc_status='passed')
             --allocate--> allocated
             --dispatch--> dispatched

QC is never inferred from sensor/KPI data - passed/failed is only ever
set by record_qc(), an explicit human action with an inspector name
recorded. This mirrors the platform's existing rule that readings/kpis
quality flags are never fabricated; the same discipline applies to what
"passed" means for a batch a customer is about to be sold.
"""
from __future__ import annotations

import io
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from .. import erp_storage
from ..deps import CurrentUser, db_session, get_current_user
from .admin_common import require_global, require_global_admin

router = APIRouter(prefix="/admin/offtake", tags=["admin-offtake"])

_BUYER_COLS = "id, name, gstin, address, state_code, contact, phone, email, notes"
_BATCH_COLS = (
    "id, plant_id, batch_no, product_name, qty_kg, produced_at, "
    "qc_status, qc_result, qc_inspector, qc_notes, qc_at, "
    "status, buyer_id, rate_inr_per_kg, allocated_at, dispatched_at, "
    "coa_object_key, coa_sha256, coa_generated_at, created_by, created_at"
)


def _batch_out(row: dict) -> dict:
    """Never expose the raw MinIO object key - same convention as
    invoices/documents this session: a presigned URL is the only way a
    client sees a downloadable link, and only once auth has already
    gated the request that generated it."""
    d = dict(row)
    key = d.pop("coa_object_key", None)
    d["coa_download_url"] = erp_storage.presigned_url(key) if key else None
    return d


# ---------------------------------------------------------------------------
# Buyers
# ---------------------------------------------------------------------------


class BuyerIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    gstin: str | None = None
    address: str | None = None
    state_code: str | None = None
    contact: str | None = None
    phone: str | None = None
    email: str | None = None
    notes: str | None = None


@router.get("/buyers")
async def list_buyers(user: CurrentUser = Depends(get_current_user), conn: AsyncConnection = Depends(db_session)):
    require_global(user)
    rows = (await conn.execute(text(f"SELECT {_BUYER_COLS} FROM buyers ORDER BY name"))).mappings().all()
    return {"buyers": [dict(r) for r in rows]}


@router.post("/buyers", status_code=status.HTTP_201_CREATED)
async def create_buyer(
    body: BuyerIn, user: CurrentUser = Depends(get_current_user), conn: AsyncConnection = Depends(db_session)
):
    require_global_admin(user)
    row = (
        await conn.execute(
            text(
                f"""
                INSERT INTO buyers (name, gstin, address, state_code, contact, phone, email, notes)
                VALUES (:name, :gstin, :address, :state_code, :contact, :phone, :email, :notes)
                RETURNING {_BUYER_COLS}
                """
            ),
            body.model_dump(),
        )
    ).mappings().first()
    return dict(row)


# ---------------------------------------------------------------------------
# Product batches
# ---------------------------------------------------------------------------


class BatchIn(BaseModel):
    plant_id: str
    batch_no: str = Field(min_length=1, max_length=100)
    product_name: str = Field(min_length=1, max_length=100)
    qty_kg: float = Field(gt=0)


async def _get_batch(conn: AsyncConnection, batch_id: str) -> dict | None:
    row = (
        await conn.execute(text(f"SELECT {_BATCH_COLS} FROM product_batches WHERE id = :id"), {"id": batch_id})
    ).mappings().first()
    return dict(row) if row else None


@router.get("/batches")
async def list_batches(
    plant_id: str | None = Query(default=None),
    batch_status: str | None = Query(default=None, alias="status"),
    user: CurrentUser = Depends(get_current_user),
    conn: AsyncConnection = Depends(db_session),
):
    require_global(user)
    clauses, params = [], {}
    if plant_id:
        clauses.append("plant_id = :plant_id")
        params["plant_id"] = plant_id
    if batch_status:
        clauses.append("status = :status")
        params["status"] = batch_status
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = (
        await conn.execute(text(f"SELECT {_BATCH_COLS} FROM product_batches {where} ORDER BY produced_at DESC"), params)
    ).mappings().all()
    return {"batches": [_batch_out(dict(r)) for r in rows]}


@router.post("/batches", status_code=status.HTTP_201_CREATED)
async def create_batch(
    body: BatchIn, user: CurrentUser = Depends(get_current_user), conn: AsyncConnection = Depends(db_session)
):
    require_global_admin(user)
    plant = (await conn.execute(text("SELECT 1 FROM plants WHERE plant_id = :p"), {"p": body.plant_id})).first()
    if not plant:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"unknown plant_id '{body.plant_id}'")

    dup = (
        await conn.execute(
            text("SELECT 1 FROM product_batches WHERE plant_id = :p AND batch_no = :b"),
            {"p": body.plant_id, "b": body.batch_no},
        )
    ).first()
    if dup:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"batch_no '{body.batch_no}' already exists for {body.plant_id}")

    row = (
        await conn.execute(
            text(
                f"""
                INSERT INTO product_batches (plant_id, batch_no, product_name, qty_kg, created_by)
                VALUES (:plant_id, :batch_no, :product_name, :qty_kg, :created_by)
                RETURNING {_BATCH_COLS}
                """
            ),
            {**body.model_dump(), "created_by": user.user_id},
        )
    ).mappings().first()
    return _batch_out(dict(row))


class QcIn(BaseModel):
    passed: bool
    inspector: str = Field(min_length=1, max_length=200)
    result: str | None = Field(default=None, max_length=2000)
    notes: str | None = Field(default=None, max_length=2000)


@router.post("/batches/{batch_id}/qc")
async def record_qc(
    batch_id: str, body: QcIn, user: CurrentUser = Depends(get_current_user), conn: AsyncConnection = Depends(db_session)
):
    """The ONLY way qc_status ever changes from 'pending'. Requires a
    named inspector - there is no path that sets 'passed' without a human
    attached to the decision."""
    require_global_admin(user)
    batch = await _get_batch(conn, batch_id)
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="batch not found")
    if batch["qc_status"] != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"QC already recorded for this batch ('{batch['qc_status']}')")

    row = (
        await conn.execute(
            text(
                f"""
                UPDATE product_batches
                SET qc_status = :qc_status, qc_result = :result, qc_inspector = :inspector,
                    qc_notes = :notes, qc_at = now()
                WHERE id = :id
                RETURNING {_BATCH_COLS}
                """
            ),
            {
                "id": batch_id,
                "qc_status": "passed" if body.passed else "failed",
                "result": body.result,
                "inspector": body.inspector,
                "notes": body.notes,
            },
        )
    ).mappings().first()
    return _batch_out(dict(row))


class AllocateIn(BaseModel):
    buyer_id: str
    rate_inr_per_kg: float | None = Field(default=None, ge=0)


@router.post("/batches/{batch_id}/allocate")
async def allocate_batch(
    batch_id: str, body: AllocateIn, user: CurrentUser = Depends(get_current_user), conn: AsyncConnection = Depends(db_session)
):
    require_global_admin(user)
    batch = await _get_batch(conn, batch_id)
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="batch not found")
    if batch["qc_status"] != "passed":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="batch has not passed QC - cannot allocate to a buyer")
    if batch["status"] != "produced":
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"batch is '{batch['status']}', not 'produced'")

    buyer = (await conn.execute(text("SELECT 1 FROM buyers WHERE id = :id"), {"id": body.buyer_id})).first()
    if not buyer:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="unknown buyer_id")

    row = (
        await conn.execute(
            text(
                f"""
                UPDATE product_batches
                SET status = 'allocated', buyer_id = :buyer_id, rate_inr_per_kg = :rate, allocated_at = now()
                WHERE id = :id
                RETURNING {_BATCH_COLS}
                """
            ),
            {"id": batch_id, "buyer_id": body.buyer_id, "rate": body.rate_inr_per_kg},
        )
    ).mappings().first()
    return _batch_out(dict(row))


@router.post("/batches/{batch_id}/dispatch")
async def dispatch_batch(
    batch_id: str, user: CurrentUser = Depends(get_current_user), conn: AsyncConnection = Depends(db_session)
):
    require_global_admin(user)
    batch = await _get_batch(conn, batch_id)
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="batch not found")
    if batch["status"] != "allocated":
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"batch is '{batch['status']}', not 'allocated' - allocate to a buyer first")

    row = (
        await conn.execute(
            text(
                f"UPDATE product_batches SET status = 'dispatched', dispatched_at = now() "
                f"WHERE id = :id RETURNING {_BATCH_COLS}"
            ),
            {"id": batch_id},
        )
    ).mappings().first()
    return _batch_out(dict(row))


@router.post("/batches/{batch_id}/coa")
async def generate_coa(
    batch_id: str, user: CurrentUser = Depends(get_current_user), conn: AsyncConnection = Depends(db_session)
):
    """Renders and uploads a Certificate of Analysis PDF. Only valid once
    QC has passed - a CoA is a certification, and this platform does not
    certify a product that failed or was never tested. Re-generating is
    allowed (e.g. a corrected inspector name) and overwrites the prior
    PDF at the same object key."""
    require_global_admin(user)
    batch = await _get_batch(conn, batch_id)
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="batch not found")
    if batch["qc_status"] != "passed":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="cannot certify a batch that has not passed QC")

    plant = (
        await conn.execute(text("SELECT name FROM plants WHERE plant_id = :p"), {"p": batch["plant_id"]})
    ).mappings().first()

    pdf_bytes = _render_coa_pdf(batch, plant["name"] if plant else batch["plant_id"])
    object_key = f"coa/{batch['plant_id']}/{batch['batch_no']}.pdf"
    try:
        result = erp_storage.upload_bytes(object_key, pdf_bytes, "application/pdf")
    except erp_storage.UploadFailed as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    row = (
        await conn.execute(
            text(
                f"""
                UPDATE product_batches
                SET coa_object_key = :key, coa_sha256 = :sha256, coa_generated_at = now()
                WHERE id = :id
                RETURNING {_BATCH_COLS}
                """
            ),
            {"id": batch_id, "key": object_key, "sha256": result["sha256"]},
        )
    ).mappings().first()
    return _batch_out(dict(row))


def _render_coa_pdf(batch: dict, plant_name: str) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    y = height - 25 * mm

    def line(text_, size=11, dy=8 * mm, bold=False):
        nonlocal y
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        c.drawString(20 * mm, y, text_)
        y -= dy

    line("Airthra Research Private Limited", size=16, bold=True, dy=10 * mm)
    line("Certificate of Analysis", size=13, bold=True, dy=10 * mm)
    line(f"Batch: {batch['batch_no']}  (Plant: {plant_name} / {batch['plant_id']})", bold=True)
    line(f"Product: {batch['product_name']}")
    line(f"Quantity: {batch['qty_kg']} kg")
    line(f"Produced: {batch['produced_at']}", dy=10 * mm)

    line("QC Result", size=13, bold=True, dy=9 * mm)
    line(f"Status: {batch['qc_status'].upper()}")
    line(f"Inspector: {batch['qc_inspector']}")
    if batch["qc_result"]:
        line(f"Result: {batch['qc_result']}")
    if batch["qc_notes"]:
        line(f"Notes: {batch['qc_notes']}")
    line(f"QC date: {batch['qc_at']}", dy=10 * mm)

    line(f"Generated {datetime.now(timezone.utc).isoformat()}", size=8, dy=6 * mm)

    c.showPage()
    c.save()
    return buf.getvalue()
