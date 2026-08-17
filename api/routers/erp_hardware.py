"""Hardware components register: the edge-unit electrical/instrumentation
BOM (compute/power, gas & CEMS stack, process sensors & translators,
comms & actuators, field survival gear). Read-mostly reference data -
seeded via seed/seed_hardware_components.py - with a create endpoint for
adding new tracked components as the hardware spec evolves.
"""
from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..erp_deps import CurrentUser, db_session, erp_admin_user, erp_read_user

router = APIRouter(prefix="/erp/hardware-components", tags=["erp-hardware"])

_COLS = "id, category, category_order, sort_order, item, spec_function, tag_id, tier, segment, cost_inr"


class HardwareComponentIn(BaseModel):
    category: str
    category_order: int
    sort_order: int
    item: str
    spec_function: str | None = None
    tag_id: str | None = None
    tier: int | None = None
    segment: str | None = None
    cost_inr: Decimal | None = None


class HardwareComponentPatch(BaseModel):
    category: str | None = None
    category_order: int | None = None
    sort_order: int | None = None
    item: str | None = None
    spec_function: str | None = None
    tag_id: str | None = None
    tier: int | None = None
    segment: str | None = None
    cost_inr: Decimal | None = None


@router.get("")
async def list_hardware_components(
    user: CurrentUser = Depends(erp_read_user),
    conn: AsyncConnection = Depends(db_session),
):
    rows = (
        await conn.execute(
            text(f"SELECT {_COLS} FROM hardware_components ORDER BY category_order, sort_order")
        )
    ).mappings().all()
    return [dict(r) for r in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_hardware_component(
    body: HardwareComponentIn,
    user: CurrentUser = Depends(erp_admin_user),
    conn: AsyncConnection = Depends(db_session),
):
    row = (
        await conn.execute(
            text(
                f"""
                INSERT INTO hardware_components
                    (category, category_order, sort_order, item, spec_function,
                     tag_id, tier, segment, cost_inr)
                VALUES (:category, :category_order, :sort_order, :item, :spec_function,
                        :tag_id, :tier, :segment, :cost_inr)
                RETURNING {_COLS}
                """
            ),
            body.model_dump(),
        )
    ).mappings().first()
    return dict(row)


@router.patch("/{component_id}")
async def update_hardware_component(
    component_id: str,
    body: HardwareComponentPatch,
    user: CurrentUser = Depends(erp_admin_user),
    conn: AsyncConnection = Depends(db_session),
):
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        row = (
            await conn.execute(text(f"SELECT {_COLS} FROM hardware_components WHERE id = :id"), {"id": component_id})
        ).mappings().first()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="hardware component not found")
        return dict(row)
    set_clause = ", ".join(f"{k} = :{k}" for k in fields)
    fields["id"] = component_id
    row = (
        await conn.execute(
            text(f"UPDATE hardware_components SET {set_clause} WHERE id = :id RETURNING {_COLS}"), fields
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="hardware component not found")
    return dict(row)


@router.delete("/{component_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_hardware_component(
    component_id: str,
    user: CurrentUser = Depends(erp_admin_user),
    conn: AsyncConnection = Depends(db_session),
):
    result = await conn.execute(text("DELETE FROM hardware_components WHERE id = :id"), {"id": component_id})
    if result.rowcount == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="hardware component not found")
