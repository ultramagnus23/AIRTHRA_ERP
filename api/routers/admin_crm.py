"""CRM: a lightweight lead pipeline. See migration 0012_crm_leads's
docstring for why this is deliberately one table, not a department.

Stage transitions are validated here (forward-only through the pipeline,
except 'lost' which is reachable from anywhere and 'won' which requires
an actual plant to point at) rather than as a DB state machine - a rigid
DB-level CHECK on "which stage can follow which" would fight the real
sales process (a deal can stall, get re-approached, or die at any point).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..deps import CurrentUser, db_session, get_current_user
from .admin_common import require_global_admin_or_department, require_global_or_department


def require_global(user: CurrentUser) -> None:
    require_global_or_department(user, "sales")


def require_global_admin(user: CurrentUser) -> None:
    require_global_admin_or_department(user, "sales")

router = APIRouter(prefix="/admin/leads", tags=["admin-crm"])

_COLS = (
    "id, company_name, contact_name, contact_email, contact_phone, source, stage, "
    "estimated_boiler_capacity_tpd, notes, lost_reason, converted_plant_id, "
    "assigned_to, created_by, created_at, updated_at"
)

class LeadIn(BaseModel):
    company_name: str = Field(min_length=1, max_length=200)
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    source: str | None = None
    estimated_boiler_capacity_tpd: float | None = None
    notes: str | None = None


class StageIn(BaseModel):
    stage: str
    lost_reason: str | None = None
    converted_plant_id: str | None = None


@router.get("")
async def list_leads(
    stage: str | None = Query(default=None),
    user: CurrentUser = Depends(get_current_user),
    conn: AsyncConnection = Depends(db_session),
):
    require_global(user)
    where = "WHERE stage = :stage" if stage else ""
    rows = (
        await conn.execute(
            text(f"SELECT {_COLS} FROM leads {where} ORDER BY updated_at DESC"),
            {"stage": stage} if stage else {},
        )
    ).mappings().all()
    return {"leads": [dict(r) for r in rows]}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_lead(
    body: LeadIn, user: CurrentUser = Depends(get_current_user), conn: AsyncConnection = Depends(db_session)
):
    require_global_admin(user)
    row = (
        await conn.execute(
            text(
                f"""
                INSERT INTO leads (company_name, contact_name, contact_email, contact_phone,
                                    source, estimated_boiler_capacity_tpd, notes, created_by, assigned_to)
                VALUES (:company_name, :contact_name, :contact_email, :contact_phone,
                        :source, :estimated_boiler_capacity_tpd, :notes, :created_by, :created_by)
                RETURNING {_COLS}
                """
            ),
            {**body.model_dump(), "created_by": user.user_id},
        )
    ).mappings().first()
    return dict(row)


async def _get_lead(conn: AsyncConnection, lead_id: str) -> dict | None:
    row = (await conn.execute(text(f"SELECT {_COLS} FROM leads WHERE id = :id"), {"id": lead_id})).mappings().first()
    return dict(row) if row else None


@router.patch("/{lead_id}/stage")
async def update_stage(
    lead_id: str, body: StageIn, user: CurrentUser = Depends(get_current_user), conn: AsyncConnection = Depends(db_session)
):
    require_global_admin(user)
    lead = await _get_lead(conn, lead_id)
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="lead not found")

    if body.stage not in ("lead", "site_assessment", "proposal", "contract_sent", "won", "lost"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"unknown stage '{body.stage}'")
    if lead["stage"] in ("won", "lost"):
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"lead is already '{lead['stage']}' - a closed lead cannot change stage")
    if body.stage == "lost" and not body.lost_reason:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="marking a lead 'lost' requires lost_reason")
    if body.stage == "won":
        if not body.converted_plant_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="marking a lead 'won' requires converted_plant_id")
        plant = (await conn.execute(text("SELECT 1 FROM plants WHERE plant_id = :p"), {"p": body.converted_plant_id})).first()
        if not plant:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"unknown plant_id '{body.converted_plant_id}'")

    row = (
        await conn.execute(
            text(
                f"""
                UPDATE leads
                SET stage = :stage, lost_reason = :lost_reason, converted_plant_id = :converted_plant_id,
                    updated_at = now()
                WHERE id = :id
                RETURNING {_COLS}
                """
            ),
            {
                "id": lead_id,
                "stage": body.stage,
                "lost_reason": body.lost_reason,
                "converted_plant_id": body.converted_plant_id,
            },
        )
    ).mappings().first()
    return dict(row)
