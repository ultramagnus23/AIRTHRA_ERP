"""P5 item 6: GRN receiving. POST /erp/grn creates a grn + grn_lines,
updates the corresponding po_items.received_qty, and rolls the parent
pos.status forward: issued -> partial (some but not all po_items fully
received) -> received (once every po_items.qty is met).

`received_qty` is incremented by qty_accepted only (rejected material never
counts as "received" for PO-fulfilment purposes - it goes back to the
vendor / a QC hold, not into stock)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from ..erp_deps import CurrentUser, db_session, erp_admin_user, erp_read_user

router = APIRouter(prefix="/erp/grn", tags=["erp-grn"])

_GRN_COLS = "id, po_id, grn_no, date, received_by, vehicle_no, eway_bill_no, notes"
_LINE_COLS = "id, grn_id, po_item_id, qty_received, qty_accepted, qty_rejected"


class GrnLineIn(BaseModel):
    po_item_id: str
    qty_received: float
    qty_accepted: float
    qty_rejected: float = 0


class GrnIn(BaseModel):
    po_id: str
    grn_no: str
    vehicle_no: str | None = None
    eway_bill_no: str | None = None
    notes: str | None = None
    lines: list[GrnLineIn]


@router.get("/{grn_id}")
async def get_grn(
    grn_id: str,
    user: CurrentUser = Depends(erp_read_user),
    conn: AsyncConnection = Depends(db_session),
):
    row = (await conn.execute(text(f"SELECT {_GRN_COLS} FROM grn WHERE id = :id"), {"id": grn_id})).mappings().first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="GRN not found")
    grn = dict(row)
    lines = (
        await conn.execute(text(f"SELECT {_LINE_COLS} FROM grn_lines WHERE grn_id = :id ORDER BY id"), {"id": grn_id})
    ).mappings().all()
    grn["lines"] = [dict(l) for l in lines]
    return grn


@router.get("")
async def list_grn(
    po_id: str | None = None,
    user: CurrentUser = Depends(erp_read_user),
    conn: AsyncConnection = Depends(db_session),
):
    if po_id:
        rows = (await conn.execute(text(f"SELECT {_GRN_COLS} FROM grn WHERE po_id = :po_id ORDER BY date DESC"), {"po_id": po_id})).mappings().all()
    else:
        rows = (await conn.execute(text(f"SELECT {_GRN_COLS} FROM grn ORDER BY date DESC"))).mappings().all()
    return [dict(r) for r in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_grn(
    body: GrnIn,
    user: CurrentUser = Depends(erp_admin_user),
    conn: AsyncConnection = Depends(db_session),
):
    po = (await conn.execute(text("SELECT id, status FROM pos WHERE id = :id"), {"id": body.po_id})).mappings().first()
    if po is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"PO '{body.po_id}' not found")
    if po["status"] not in ("issued", "partial"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"PO status is '{po['status']}' - GRN can only be recorded against an 'issued' or 'partial' PO",
        )
    if not body.lines:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="GRN must have at least one line")

    # Validate every po_item_id actually belongs to this PO before writing
    # anything.
    po_items = (
        await conn.execute(text("SELECT id, qty, received_qty FROM po_items WHERE po_id = :po_id"), {"po_id": body.po_id})
    ).mappings().all()
    po_items_by_id = {str(r["id"]): dict(r) for r in po_items}
    for line in body.lines:
        if line.po_item_id not in po_items_by_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"po_item '{line.po_item_id}' does not belong to PO '{body.po_id}'",
            )
        if abs(line.qty_received - (line.qty_accepted + line.qty_rejected)) > 1e-6:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="qty_received must equal qty_accepted + qty_rejected",
            )

    try:
        grn_row = (
            await conn.execute(
                text(
                    f"""
                    INSERT INTO grn (po_id, grn_no, received_by, vehicle_no, eway_bill_no, notes)
                    VALUES (:po_id, :grn_no, :received_by, :vehicle_no, :eway_bill_no, :notes)
                    RETURNING {_GRN_COLS}
                    """
                ),
                {
                    "po_id": body.po_id, "grn_no": body.grn_no, "received_by": user.user_id or None,
                    "vehicle_no": body.vehicle_no, "eway_bill_no": body.eway_bill_no, "notes": body.notes,
                },
            )
        ).mappings().first()
    except IntegrityError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"grn_no conflict: {exc.orig}") from exc
    grn_row = dict(grn_row)

    for line in body.lines:
        await conn.execute(
            text(
                f"""
                INSERT INTO grn_lines (grn_id, po_item_id, qty_received, qty_accepted, qty_rejected)
                VALUES (:grn_id, :po_item_id, :qty_received, :qty_accepted, :qty_rejected)
                """
            ),
            {"grn_id": grn_row["id"], **line.model_dump()},
        )
        await conn.execute(
            text("UPDATE po_items SET received_qty = received_qty + :accepted WHERE id = :id"),
            {"accepted": line.qty_accepted, "id": line.po_item_id},
        )

    # Roll pos.status forward based on the fresh received_qty vs qty for
    # every item on the PO (not just the ones on this GRN).
    fresh_items = (
        await conn.execute(text("SELECT qty, received_qty FROM po_items WHERE po_id = :po_id"), {"po_id": body.po_id})
    ).mappings().all()
    all_received = all(float(r["received_qty"]) >= float(r["qty"]) for r in fresh_items)
    any_received = any(float(r["received_qty"]) > 0 for r in fresh_items)
    new_status = "received" if all_received else ("partial" if any_received else po["status"])
    await conn.execute(text("UPDATE pos SET status = :s WHERE id = :id"), {"s": new_status, "id": body.po_id})

    lines_out = (
        await conn.execute(text(f"SELECT {_LINE_COLS} FROM grn_lines WHERE grn_id = :id ORDER BY id"), {"id": grn_row["id"]})
    ).mappings().all()
    grn_row["lines"] = [dict(l) for l in lines_out]
    grn_row["po_status"] = new_status
    return grn_row
