"""P5: materials CRUD. PRD 4.3 `materials` table - density_kg_m3/rate_per_kg
drive the BOM weight/cost calculator (api/erp_calc.py)."""
from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..dept_deps import CurrentUser, db_session, require_department, require_department_admin

erp_read_user = require_department("procurement")
erp_admin_user = require_department_admin("procurement")

router = APIRouter(prefix="/erp/materials", tags=["erp-materials"])

_COLS = "id, name, grade, density_kg_m3, rate_per_kg, hsn"


class MaterialIn(BaseModel):
    name: str
    grade: str | None = None
    density_kg_m3: Decimal | None = None
    rate_per_kg: Decimal | None = None
    hsn: str | None = None


class MaterialPatch(BaseModel):
    name: str | None = None
    grade: str | None = None
    density_kg_m3: Decimal | None = None
    rate_per_kg: Decimal | None = None
    hsn: str | None = None


@router.get("")
async def list_materials(
    user: CurrentUser = Depends(erp_read_user),
    conn: AsyncConnection = Depends(db_session),
):
    rows = (await conn.execute(text(f"SELECT {_COLS} FROM materials ORDER BY name"))).mappings().all()
    return [dict(r) for r in rows]


@router.get("/{material_id}")
async def get_material(
    material_id: str,
    user: CurrentUser = Depends(erp_read_user),
    conn: AsyncConnection = Depends(db_session),
):
    row = (await conn.execute(text(f"SELECT {_COLS} FROM materials WHERE id = :id"), {"id": material_id})).mappings().first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="material not found")
    return dict(row)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_material(
    body: MaterialIn,
    user: CurrentUser = Depends(erp_admin_user),
    conn: AsyncConnection = Depends(db_session),
):
    row = (
        await conn.execute(
            text(
                f"""
                INSERT INTO materials (name, grade, density_kg_m3, rate_per_kg, hsn)
                VALUES (:name, :grade, :density_kg_m3, :rate_per_kg, :hsn)
                RETURNING {_COLS}
                """
            ),
            body.model_dump(),
        )
    ).mappings().first()
    return dict(row)


@router.patch("/{material_id}")
async def update_material(
    material_id: str,
    body: MaterialPatch,
    user: CurrentUser = Depends(erp_admin_user),
    conn: AsyncConnection = Depends(db_session),
):
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        row = (await conn.execute(text(f"SELECT {_COLS} FROM materials WHERE id = :id"), {"id": material_id})).mappings().first()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="material not found")
        return dict(row)
    set_clause = ", ".join(f"{k} = :{k}" for k in fields)
    fields["id"] = material_id
    row = (
        await conn.execute(text(f"UPDATE materials SET {set_clause} WHERE id = :id RETURNING {_COLS}"), fields)
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="material not found")
    return dict(row)
