"""P7 §5.3 GET /admin/invoices, POST /admin/invoices/{id}/approve.

Invoice generation itself is workers/billing_worker.py (a separate
on-demand-runnable script/worker, not an API endpoint - see that file's
docstring). This router only lists existing `invoices` rows and performs
the draft -> approved status transition. The would-be approved -> sent
transition (actually emailing/dispatching the invoice) is explicitly out
of scope per the task.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..deps import CurrentUser, db_session, get_current_user
from .admin_common import require_global, require_global_admin

router = APIRouter(prefix="/admin", tags=["admin-billing"])


@router.get("/invoices")
async def list_invoices(
    plant_id: str | None = Query(default=None),
    period: str | None = Query(default=None),
    inv_status: str | None = Query(default=None, alias="status"),
    user: CurrentUser = Depends(get_current_user),
    conn: AsyncConnection = Depends(db_session),
):
    require_global(user)

    clauses = []
    params: dict = {}
    if plant_id:
        clauses.append("plant_id = :plant_id")
        params["plant_id"] = plant_id
    if period:
        clauses.append("period = :period")
        params["period"] = period
    if inv_status:
        clauses.append("status = :status")
        params["status"] = inv_status
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    rows = (
        await conn.execute(
            text(
                f"""
                SELECT invoice_id, plant_id, period, so2_kg, k2so3_kg, uptime_pct,
                       amount, pdf_url, status
                FROM invoices
                {where}
                ORDER BY plant_id, period DESC
                """
            ),
            params,
        )
    ).mappings().all()
    return {"invoices": [dict(r) for r in rows]}


@router.post("/invoices/{invoice_id}/approve")
async def approve_invoice(
    invoice_id: str,
    user: CurrentUser = Depends(get_current_user),
    conn: AsyncConnection = Depends(db_session),
):
    require_global_admin(user)

    existing = (
        await conn.execute(
            text("SELECT invoice_id, status FROM invoices WHERE invoice_id = :id"),
            {"id": invoice_id},
        )
    ).mappings().first()
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"invoice '{invoice_id}' not found")
    if existing["status"] != "draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"invoice '{invoice_id}' is '{existing['status']}', not 'draft' - cannot approve",
        )

    row = (
        await conn.execute(
            text(
                """
                UPDATE invoices SET status = 'approved'
                WHERE invoice_id = :id
                RETURNING invoice_id, plant_id, period, status
                """
            ),
            {"id": invoice_id},
        )
    ).mappings().first()
    return dict(row)
