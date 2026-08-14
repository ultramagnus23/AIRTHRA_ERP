"""P5 items 1/7: vendor_invoices CRUD + 3-way match (PO vs GRN vs invoice).

3-way match tolerance: +/-2% on each of taxable/GST/total (rounding /
minor vendor-invoice rounding is common and shouldn't block approval), and
received (GRN-accepted) quantity must be >= 98% of ordered quantity (so an
invoice for goods that were never actually received - or only
partially/short received beyond a small tolerance - is blocked). Documented
here as the single source of truth for the tolerance value.

There is no vendor_invoice_lines table in the P0 schema (vendor_invoices is
a header-only row: taxable/gst/total), so the match is necessarily at
header level: invoice.taxable/gst/total are compared against the PO's own
GST-engine-computed totals (api/erp_calc.gst_split_for_line, the same logic
erp_pos.py uses - so "the PO's expected tax" is always freshly derived, not
a stale stored value), and received quantity is compared against ordered
quantity via grn_lines joined through po_items.
"""
from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..erp_calc import gst_split_for_line
from ..erp_deps import CurrentUser, db_session, erp_admin_user, erp_read_user

router = APIRouter(prefix="/erp/vendor-invoices", tags=["erp-vendor-invoices"])

TOLERANCE_PCT = Decimal("2")  # +/-2% on taxable/gst/total; see module docstring

_COLS = "id, vendor_id, po_id, inv_no, date, taxable, gst, total, file_url, sha256, status"


class InvoiceIn(BaseModel):
    vendor_id: str
    po_id: str | None = None
    inv_no: str
    date: str | None = None
    taxable: Decimal
    gst: Decimal
    total: Decimal
    file_url: str | None = None
    sha256: str | None = None


async def _get_invoice(conn: AsyncConnection, invoice_id: str) -> dict | None:
    row = (await conn.execute(text(f"SELECT {_COLS} FROM vendor_invoices WHERE id = :id"), {"id": invoice_id})).mappings().first()
    return dict(row) if row else None


def _within_tolerance(actual: Decimal, expected: Decimal, pct: Decimal) -> bool:
    if expected == 0:
        return actual == 0
    diff_pct = abs(actual - expected) / abs(expected) * 100
    return diff_pct <= pct


async def _run_three_way_match(conn: AsyncConnection, invoice: dict) -> dict:
    if not invoice["po_id"]:
        return {
            "ok": False,
            "reason": "invoice is not linked to a PO (po_id is null) - 3-way match requires a PO",
            "checks": {},
        }

    po = (await conn.execute(text("SELECT id, vendor_id, status FROM pos WHERE id = :id"), {"id": invoice["po_id"]})).mappings().first()
    if po is None:
        return {"ok": False, "reason": f"linked PO '{invoice['po_id']}' not found", "checks": {}}
    if str(po["vendor_id"]) != str(invoice["vendor_id"]):
        return {"ok": False, "reason": "invoice.vendor_id does not match the linked PO's vendor_id", "checks": {}}

    company = (await conn.execute(text("SELECT state_code FROM company LIMIT 1"))).mappings().first()
    vendor = (await conn.execute(text("SELECT state_code FROM vendors WHERE id = :id"), {"id": invoice["vendor_id"]})).mappings().first()

    po_items = (
        await conn.execute(text("SELECT id, qty, rate, gst_rate FROM po_items WHERE po_id = :po_id"), {"po_id": invoice["po_id"]})
    ).mappings().all()

    po_taxable = Decimal("0")
    po_gst = Decimal("0")
    for it in po_items:
        line_taxable = (Decimal(str(it["qty"])) * Decimal(str(it["rate"]))).quantize(Decimal("0.01"))
        split = gst_split_for_line(line_taxable, Decimal(str(it["gst_rate"])), vendor["state_code"], company["state_code"])
        po_taxable += line_taxable
        po_gst += split["total_gst"]
    po_total = po_taxable + po_gst

    ordered_qty = sum(Decimal(str(it["qty"])) for it in po_items) if po_items else Decimal("0")
    accepted_qty_row = (
        await conn.execute(
            text(
                """
                SELECT COALESCE(SUM(gl.qty_accepted), 0) AS accepted
                FROM grn_lines gl
                JOIN po_items pi ON pi.id = gl.po_item_id
                WHERE pi.po_id = :po_id
                """
            ),
            {"po_id": invoice["po_id"]},
        )
    ).scalar()
    accepted_qty = Decimal(str(accepted_qty_row))

    inv_taxable = Decimal(str(invoice["taxable"] or 0))
    inv_gst = Decimal(str(invoice["gst"] or 0))
    inv_total = Decimal(str(invoice["total"] or 0))

    checks = {
        "taxable_matches_po": {
            "ok": _within_tolerance(inv_taxable, po_taxable, TOLERANCE_PCT),
            "invoice": str(inv_taxable), "po_expected": str(po_taxable), "tolerance_pct": str(TOLERANCE_PCT),
        },
        "gst_matches_po": {
            "ok": _within_tolerance(inv_gst, po_gst, TOLERANCE_PCT),
            "invoice": str(inv_gst), "po_expected": str(po_gst), "tolerance_pct": str(TOLERANCE_PCT),
        },
        "total_matches_po": {
            "ok": _within_tolerance(inv_total, po_total, TOLERANCE_PCT),
            "invoice": str(inv_total), "po_expected": str(po_total), "tolerance_pct": str(TOLERANCE_PCT),
        },
        "grn_received_covers_po_qty": {
            "ok": bool(ordered_qty > 0 and accepted_qty >= ordered_qty * Decimal("0.98")),
            "ordered_qty": str(ordered_qty), "grn_accepted_qty": str(accepted_qty),
        },
    }
    ok = all(c["ok"] for c in checks.values())
    reason = None if ok else "one or more 3-way-match checks failed: " + ", ".join(k for k, v in checks.items() if not v["ok"])
    return {"ok": ok, "reason": reason, "checks": checks}


@router.get("")
async def list_invoices(
    user: CurrentUser = Depends(erp_read_user),
    conn: AsyncConnection = Depends(db_session),
):
    rows = (await conn.execute(text(f"SELECT {_COLS} FROM vendor_invoices ORDER BY date DESC NULLS LAST"))).mappings().all()
    return [dict(r) for r in rows]


@router.get("/{invoice_id}")
async def get_invoice(
    invoice_id: str,
    user: CurrentUser = Depends(erp_read_user),
    conn: AsyncConnection = Depends(db_session),
):
    row = await _get_invoice(conn, invoice_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="vendor invoice not found")
    return row


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_invoice(
    body: InvoiceIn,
    user: CurrentUser = Depends(erp_admin_user),
    conn: AsyncConnection = Depends(db_session),
):
    row = (
        await conn.execute(
            text(
                f"""
                INSERT INTO vendor_invoices (vendor_id, po_id, inv_no, date, taxable, gst, total, file_url, sha256)
                VALUES (:vendor_id, :po_id, :inv_no, :date, :taxable, :gst, :total, :file_url, :sha256)
                RETURNING {_COLS}
                """
            ),
            body.model_dump(),
        )
    ).mappings().first()
    return dict(row)


@router.post("/{invoice_id}/check")
async def check_three_way_match(
    invoice_id: str,
    user: CurrentUser = Depends(erp_read_user),
    conn: AsyncConnection = Depends(db_session),
):
    """Read-only: runs the 3-way match and returns the detailed result
    without changing vendor_invoices.status."""
    invoice = await _get_invoice(conn, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="vendor invoice not found")
    return await _run_three_way_match(conn, invoice)


@router.post("/{invoice_id}/approve")
async def approve_invoice(
    invoice_id: str,
    user: CurrentUser = Depends(erp_admin_user),
    conn: AsyncConnection = Depends(db_session),
):
    """Advances status -> 'approved'. Always re-runs the 3-way match itself
    (never trusts a previously-stored 'matched' status) and rejects with a
    clear error if it fails - this is the literal P5 acceptance-gate
    behaviour."""
    invoice = await _get_invoice(conn, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="vendor invoice not found")
    if invoice["status"] == "approved":
        return invoice
    if invoice["status"] == "paid":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="invoice is already paid")

    match = await _run_three_way_match(conn, invoice)
    if not match["ok"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "3-way match failed - cannot approve", "match": match},
        )

    row = (
        await conn.execute(text(f"UPDATE vendor_invoices SET status = 'approved' WHERE id = :id RETURNING {_COLS}"), {"id": invoice_id})
    ).mappings().first()
    return dict(row)
