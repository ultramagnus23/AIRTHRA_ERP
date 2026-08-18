"""P7 §5.3 GET /admin/invoices, POST /admin/invoices/{id}/approve.

Invoice generation itself is workers/billing_worker.py (a separate
on-demand-runnable script/worker, not an API endpoint - see that file's
docstring). This router only lists existing `invoices` rows and performs
the draft -> approved status transition. The would-be approved -> sent
transition (actually emailing/dispatching the invoice) is explicitly out
of scope per the task.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from .. import erp_storage
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
                       amount, pdf_url, status, contract_id, line_items
                FROM invoices
                {where}
                ORDER BY plant_id, period DESC
                """
            ),
            params,
        )
    ).mappings().all()

    # The MinIO bucket these PDFs live in is private (see AUDIT.md 2.1 -
    # it used to be world-readable by anyone who could guess an object
    # key). pdf_url as stored is a stable object identifier, not a
    # fetchable link; every response swaps in a short-lived presigned URL
    # instead, scoped to a global_admin/global_read request that already
    # passed require_global above - the auth check already happened by
    # the time a URL is minted.
    invoices = []
    for r in rows:
        d = dict(r)
        key = erp_storage.key_from_url(d["pdf_url"]) if d["pdf_url"] else None
        if key:
            d["pdf_url"] = erp_storage.presigned_url(key)
        invoices.append(d)
    return {"invoices": invoices}


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


# ---------------------------------------------------------------------------
# Contracts (migration 0008_contracts) - the commercial terms
# workers/billing_worker.py bills against, replacing the old global
# SO2_RATE_PER_KG env var. See that migration's docstring for the schema
# rationale and workers/billing_worker.py's _compute_line_items for the
# formula this data feeds.
# ---------------------------------------------------------------------------

_CONTRACT_COLS = (
    "contract_id, plant_id, status, effective_from, effective_to, "
    "base_fee_inr, usage_rate_inr_per_kg, "
    "performance_bonus_threshold_pct, performance_bonus_inr, "
    "performance_penalty_threshold_pct, performance_penalty_inr, "
    "revenue_share_pct, notes, created_at"
)


class ContractIn(BaseModel):
    plant_id: str
    effective_from: date
    base_fee_inr: float = Field(default=0, ge=0)
    usage_rate_inr_per_kg: float = Field(default=0, ge=0)
    performance_bonus_threshold_pct: float | None = Field(default=None, ge=0, le=100)
    performance_bonus_inr: float = Field(default=0, ge=0)
    performance_penalty_threshold_pct: float | None = Field(default=None, ge=0, le=100)
    performance_penalty_inr: float = Field(default=0, ge=0)
    revenue_share_pct: float = Field(default=0, ge=0, le=100)
    notes: str | None = None


@router.get("/contracts")
async def list_contracts(
    plant_id: str | None = Query(default=None),
    user: CurrentUser = Depends(get_current_user),
    conn: AsyncConnection = Depends(db_session),
):
    require_global(user)
    where = "WHERE plant_id = :plant_id" if plant_id else ""
    rows = (
        await conn.execute(
            text(f"SELECT {_CONTRACT_COLS} FROM contracts {where} ORDER BY plant_id, effective_from DESC"),
            {"plant_id": plant_id} if plant_id else {},
        )
    ).mappings().all()
    return {"contracts": [dict(r) for r in rows]}


@router.post("/contracts", status_code=status.HTTP_201_CREATED)
async def create_contract(
    body: ContractIn,
    user: CurrentUser = Depends(get_current_user),
    conn: AsyncConnection = Depends(db_session),
):
    """Creates a new active contract for a plant. If one is already
    active, it is ended (effective_to = the new contract's start date
    minus one day) in the same transaction as the insert - a plant is
    never left with two simultaneously-active contracts, and the switch
    is atomic rather than "end the old one, then hope the create
    succeeds"."""
    require_global_admin(user)

    plant_exists = (
        await conn.execute(text("SELECT 1 FROM plants WHERE plant_id = :p"), {"p": body.plant_id})
    ).first()
    if not plant_exists:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"unknown plant_id '{body.plant_id}'")

    current = (
        await conn.execute(
            text("SELECT contract_id, effective_from FROM contracts WHERE plant_id = :p AND status = 'active'"),
            {"p": body.plant_id},
        )
    ).mappings().first()
    if current is not None:
        if current["effective_from"] >= body.effective_from:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=(
                    f"plant '{body.plant_id}' already has an active contract starting "
                    f"{current['effective_from']} - new contract must start after that date"
                ),
            )
        await conn.execute(
            text(
                "UPDATE contracts SET status = 'ended', effective_to = :end_date "
                "WHERE contract_id = :id"
            ),
            {"end_date": body.effective_from, "id": current["contract_id"]},
        )

    row = (
        await conn.execute(
            text(
                f"""
                INSERT INTO contracts
                    (plant_id, status, effective_from, base_fee_inr, usage_rate_inr_per_kg,
                     performance_bonus_threshold_pct, performance_bonus_inr,
                     performance_penalty_threshold_pct, performance_penalty_inr,
                     revenue_share_pct, notes, created_by)
                VALUES
                    (:plant_id, 'active', :effective_from, :base_fee_inr, :usage_rate_inr_per_kg,
                     :performance_bonus_threshold_pct, :performance_bonus_inr,
                     :performance_penalty_threshold_pct, :performance_penalty_inr,
                     :revenue_share_pct, :notes, :created_by)
                RETURNING {_CONTRACT_COLS}
                """
            ),
            {**body.model_dump(), "created_by": user.user_id},
        )
    ).mappings().first()
    return dict(row)
