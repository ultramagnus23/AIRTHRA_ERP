"""P5: PO builder, GST logic, PO PDF generation (items 3/4/5), plus base
pos/po_items CRUD.

po_no format: AIR/PO/{FY}/{seq:04d}, Indian fiscal year (Apr-Mar), e.g. a PO
raised on 2026-08-14 is FY 2026-27 -> 'AIR/PO/26-27/0001' (matches the
CHECK constraint on pos.po_no in migrations/versions/0001_initial_schema.py
verbatim, including the FY label's exact 'YY-YY' shape).

Sequence generation: gap-free per FY, DB-side atomic. P0 is already
migrated and this phase must not create new tables, so instead of a
separate counter table we serialize PO-number allocation with
pg_advisory_xact_lock(hashtext(fy_label)) - held for the remainder of the
current transaction (api/deps.py's db_session already opens one connection
+ transaction per request) - then read MAX(seq) for that FY under the lock
and insert +1 before commit/lock-release. This is race-free under
concurrency (a second concurrent request's lock acquisition blocks until
the first transaction commits) without adding new schema.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..erp_calc import fiscal_year_label, format_po_no, gst_split_for_line
from ..erp_deps import CurrentUser, db_session, erp_admin_user, erp_read_user
from ..erp_pdf import build_po_pdf
from ..erp_storage import UploadFailed, upload_bytes

router = APIRouter(prefix="/erp/pos", tags=["erp-pos"])

_PO_COLS = "id, po_no, vendor_id, po_date, delivery_address, payment_terms, delivery_terms, freight, notes, status"
_ITEM_COLS = "id, po_id, bom_item_id, description, hsn, qty, unit, rate, gst_rate, received_qty"


class PoItemIn(BaseModel):
    bom_item_id: str | None = None
    description: str
    hsn: str | None = None
    qty: Decimal
    unit: str
    rate: Decimal
    gst_rate: Decimal = Decimal("18")


class PoCreateIn(BaseModel):
    vendor_id: str
    po_date: str | None = None
    delivery_address: str | None = None
    payment_terms: str | None = None
    delivery_terms: str | None = None
    freight: Decimal | None = None
    notes: str | None = None
    items: list[PoItemIn]


class PoFromBomIn(BaseModel):
    bom_id: str
    vendor_id: str
    po_date: str | None = None
    delivery_address: str | None = None
    payment_terms: str | None = None
    delivery_terms: str | None = None
    freight: Decimal | None = None
    notes: str | None = None
    default_gst_rate: Decimal = Decimal("18")


class PoPatch(BaseModel):
    delivery_address: str | None = None
    payment_terms: str | None = None
    delivery_terms: str | None = None
    freight: Decimal | None = None
    notes: str | None = None


async def next_po_no(conn: AsyncConnection, po_date) -> str:
    fy = fiscal_year_label(po_date)
    lock_key = f"erp_po_seq_{fy}"
    await conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": lock_key})
    last = (
        await conn.execute(
            text("SELECT po_no FROM pos WHERE po_no LIKE :pattern ORDER BY po_no DESC LIMIT 1"),
            {"pattern": f"AIR/PO/{fy}/%"},
        )
    ).scalar()
    seq = int(last.rsplit("/", 1)[1]) + 1 if last else 1
    return format_po_no(fy, seq)


async def _get_po(conn: AsyncConnection, po_id: str) -> dict | None:
    row = (await conn.execute(text(f"SELECT {_PO_COLS} FROM pos WHERE id = :id"), {"id": po_id})).mappings().first()
    return dict(row) if row else None


async def _get_company(conn: AsyncConnection) -> dict:
    row = (
        await conn.execute(text("SELECT name, address, gstin, state_code, phone, email FROM company LIMIT 1"))
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="company row not seeded")
    return dict(row)


async def _get_vendor(conn: AsyncConnection, vendor_id: str) -> dict:
    row = (
        await conn.execute(
            text("SELECT id, name, gstin, address, state_code, contact, phone, email FROM vendors WHERE id = :id"),
            {"id": vendor_id},
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"vendor '{vendor_id}' not found")
    return dict(row)


async def compute_po_lines_and_totals(conn: AsyncConnection, po: dict) -> tuple[list[dict], dict]:
    """Shared by GET /erp/pos/{id} and the PDF builder: recomputes GST per
    line server-side from po_items + vendor.state_code + company.state_code
    every time (never trusts a stored total) - this is the literal P5
    acceptance-gate logic."""
    company = await _get_company(conn)
    vendor = await _get_vendor(conn, po["vendor_id"])

    rows = (
        await conn.execute(text(f"SELECT {_ITEM_COLS} FROM po_items WHERE po_id = :id ORDER BY id"), {"id": po["id"]})
    ).mappings().all()

    lines = []
    taxable_total = Decimal("0")
    cgst_total = Decimal("0")
    sgst_total = Decimal("0")
    igst_total = Decimal("0")

    for r in rows:
        r = dict(r)
        taxable = (Decimal(str(r["qty"])) * Decimal(str(r["rate"]))).quantize(Decimal("0.01"))
        split = gst_split_for_line(taxable, Decimal(str(r["gst_rate"])), vendor["state_code"], company["state_code"])
        line = {**r, "taxable": taxable, **split}
        lines.append(line)
        taxable_total += taxable
        cgst_total += split["cgst"]
        sgst_total += split["sgst"]
        igst_total += split["igst"]

    freight = Decimal(str(po["freight"])) if po.get("freight") else Decimal("0")
    grand_total = (taxable_total + cgst_total + sgst_total + igst_total + freight).quantize(Decimal("0.01"))

    totals = {
        "taxable": taxable_total,
        "cgst": cgst_total,
        "sgst": sgst_total,
        "igst": igst_total,
        "freight": freight,
        "grand_total": grand_total,
        "vendor_state_code": vendor["state_code"],
        "company_state_code": company["state_code"],
        "tax_regime": "intra_state (CGST+SGST)" if vendor["state_code"] == company["state_code"] else "inter_state (IGST)",
    }
    return lines, totals


@router.get("")
async def list_pos(
    user: CurrentUser = Depends(erp_read_user),
    conn: AsyncConnection = Depends(db_session),
):
    rows = (await conn.execute(text(f"SELECT {_PO_COLS} FROM pos ORDER BY po_no DESC"))).mappings().all()
    return [dict(r) for r in rows]


@router.get("/{po_id}")
async def get_po(
    po_id: str,
    user: CurrentUser = Depends(erp_read_user),
    conn: AsyncConnection = Depends(db_session),
):
    po = await _get_po(conn, po_id)
    if po is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PO not found")
    lines, totals = await compute_po_lines_and_totals(conn, po)
    po["items"] = lines
    po["totals"] = totals
    from ..erp_calc import amount_in_words

    po["amount_in_words"] = amount_in_words(totals["grand_total"])
    return po


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_po(
    body: PoCreateIn,
    user: CurrentUser = Depends(erp_admin_user),
    conn: AsyncConnection = Depends(db_session),
):
    await _get_vendor(conn, body.vendor_id)  # 400 if unknown
    if not body.items:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="PO must have at least one item")

    po_date_row = (
        await conn.execute(text("SELECT COALESCE(CAST(:d AS date), CURRENT_DATE) AS d"), {"d": body.po_date})
    ).scalar()
    po_no = await next_po_no(conn, po_date_row)

    po_row = (
        await conn.execute(
            text(
                f"""
                INSERT INTO pos (po_no, vendor_id, po_date, delivery_address, payment_terms, delivery_terms, freight, notes)
                VALUES (:po_no, :vendor_id, COALESCE(CAST(:po_date AS date), CURRENT_DATE), :delivery_address,
                        :payment_terms, :delivery_terms, :freight, :notes)
                RETURNING {_PO_COLS}
                """
            ),
            {
                "po_no": po_no, "vendor_id": body.vendor_id, "po_date": body.po_date,
                "delivery_address": body.delivery_address, "payment_terms": body.payment_terms,
                "delivery_terms": body.delivery_terms, "freight": body.freight, "notes": body.notes,
            },
        )
    ).mappings().first()
    po_row = dict(po_row)

    for item in body.items:
        await conn.execute(
            text(
                f"""
                INSERT INTO po_items (po_id, bom_item_id, description, hsn, qty, unit, rate, gst_rate)
                VALUES (:po_id, :bom_item_id, :description, :hsn, :qty, :unit, :rate, :gst_rate)
                """
            ),
            {"po_id": po_row["id"], **item.model_dump()},
        )

    return po_row


@router.post("/from-bom", status_code=status.HTTP_201_CREATED)
async def create_po_from_bom(
    body: PoFromBomIn,
    user: CurrentUser = Depends(erp_admin_user),
    conn: AsyncConnection = Depends(db_session),
):
    """PO builder: prefills po_items from bom_items at material rate
    (qty = total_weight_kg, unit = 'kg', rate = materials.rate_per_kg,
    hsn = materials.hsn), joined to the chosen vendor."""
    await _get_vendor(conn, body.vendor_id)

    bom = (await conn.execute(text("SELECT id FROM boms WHERE id = :id"), {"id": body.bom_id})).mappings().first()
    if bom is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"bom '{body.bom_id}' not found")

    bom_items = (
        await conn.execute(
            text(
                """
                SELECT bi.id AS bom_item_id, bi.description, bi.total_weight_kg, m.hsn, m.rate_per_kg
                FROM bom_items bi
                JOIN materials m ON m.id = bi.material_id
                WHERE bi.bom_id = :bom_id
                ORDER BY bi.id
                """
            ),
            {"bom_id": body.bom_id},
        )
    ).mappings().all()
    if not bom_items:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="bom has no items (or weights not computed)")

    po_date_row = (
        await conn.execute(text("SELECT COALESCE(CAST(:d AS date), CURRENT_DATE) AS d"), {"d": body.po_date})
    ).scalar()
    po_no = await next_po_no(conn, po_date_row)

    po_row = (
        await conn.execute(
            text(
                f"""
                INSERT INTO pos (po_no, vendor_id, po_date, delivery_address, payment_terms, delivery_terms, freight, notes)
                VALUES (:po_no, :vendor_id, COALESCE(CAST(:po_date AS date), CURRENT_DATE), :delivery_address,
                        :payment_terms, :delivery_terms, :freight, :notes)
                RETURNING {_PO_COLS}
                """
            ),
            {
                "po_no": po_no, "vendor_id": body.vendor_id, "po_date": body.po_date,
                "delivery_address": body.delivery_address, "payment_terms": body.payment_terms,
                "delivery_terms": body.delivery_terms, "freight": body.freight, "notes": body.notes,
            },
        )
    ).mappings().first()
    po_row = dict(po_row)

    for bi in bom_items:
        if bi["total_weight_kg"] is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"bom_item '{bi['bom_item_id']}' has no computed total_weight_kg - save/compute it first",
            )
        await conn.execute(
            text(
                """
                INSERT INTO po_items (po_id, bom_item_id, description, hsn, qty, unit, rate, gst_rate)
                VALUES (:po_id, :bom_item_id, :description, :hsn, :qty, 'kg', :rate, :gst_rate)
                """
            ),
            {
                "po_id": po_row["id"], "bom_item_id": bi["bom_item_id"], "description": bi["description"],
                "hsn": bi["hsn"], "qty": bi["total_weight_kg"], "rate": bi["rate_per_kg"] or 0,
                "gst_rate": body.default_gst_rate,
            },
        )

    return po_row


@router.patch("/{po_id}")
async def update_po(
    po_id: str,
    body: PoPatch,
    user: CurrentUser = Depends(erp_admin_user),
    conn: AsyncConnection = Depends(db_session),
):
    current = await _get_po(conn, po_id)
    if current is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PO not found")
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        return current
    set_clause = ", ".join(f"{k} = :{k}" for k in fields)
    fields["id"] = po_id
    row = (await conn.execute(text(f"UPDATE pos SET {set_clause} WHERE id = :id RETURNING {_PO_COLS}"), fields)).mappings().first()
    return dict(row)


@router.post("/{po_id}/items", status_code=status.HTTP_201_CREATED)
async def add_po_item(
    po_id: str,
    body: PoItemIn,
    user: CurrentUser = Depends(erp_admin_user),
    conn: AsyncConnection = Depends(db_session),
):
    po = await _get_po(conn, po_id)
    if po is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PO not found")
    row = (
        await conn.execute(
            text(
                f"""
                INSERT INTO po_items (po_id, bom_item_id, description, hsn, qty, unit, rate, gst_rate)
                VALUES (:po_id, :bom_item_id, :description, :hsn, :qty, :unit, :rate, :gst_rate)
                RETURNING {_ITEM_COLS}
                """
            ),
            {"po_id": po_id, **body.model_dump()},
        )
    ).mappings().first()
    return dict(row)


@router.post("/{po_id}/issue")
async def issue_po(
    po_id: str,
    user: CurrentUser = Depends(erp_admin_user),
    conn: AsyncConnection = Depends(db_session),
):
    po = await _get_po(conn, po_id)
    if po is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PO not found")
    if po["status"] != "draft":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"PO is already '{po['status']}', cannot issue")
    row = (
        await conn.execute(text(f"UPDATE pos SET status = 'issued' WHERE id = :id RETURNING {_PO_COLS}"), {"id": po_id})
    ).mappings().first()
    return dict(row)


@router.get("/{po_id}/pdf")
async def get_po_pdf(
    po_id: str,
    regenerate: bool = False,
    user: CurrentUser = Depends(erp_read_user),
    conn: AsyncConnection = Depends(db_session),
):
    """Generates (or reuses) the PO PDF, stores it in MinIO (url + sha256
    only, never the blob in Postgres - same convention as archive_log/
    drawings/quotations), and redirects to it. `regenerate=true` forces a
    fresh render+upload (e.g. after items changed)."""
    po = await _get_po(conn, po_id)
    if po is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PO not found")

    # Note: unlike vendor_invoices/quotations/drawings, `pos` has no
    # pdf_url/sha256 columns in the P0 schema (this phase does not alter
    # the schema). So there is nowhere to cache a pointer to a previously
    # generated PDF - we always render fresh from the live po_items/GST
    # calc and re-upload to a stable, po_no-derived key (MinIO overwrite is
    # idempotent). That also guarantees the PDF can never drift from the
    # live data, which matters more here than caching would save.
    lines, totals = await compute_po_lines_and_totals(conn, po)
    company = await _get_company(conn)
    vendor = await _get_vendor(conn, po["vendor_id"])

    pdf_bytes = build_po_pdf(company=company, vendor=vendor, po=po, items=lines, totals=totals)

    key = f"erp/pos/{po['po_no'].replace('/', '_')}.pdf"
    try:
        result = upload_bytes(key, pdf_bytes, "application/pdf")
    except UploadFailed as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    return {
        "po_id": po_id,
        "po_no": po["po_no"],
        "url": result["url"],
        "sha256": result["sha256"],
        "bytes": result["bytes"],
    }
