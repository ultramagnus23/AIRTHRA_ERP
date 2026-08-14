"""P5: vendors CRUD. PRD 4.3 `vendors` table - master data for PO/GST
logic (vendors.state_code drives CGST+SGST vs IGST in erp_pos.py)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..erp_deps import CurrentUser, db_session, erp_admin_user, erp_read_user

router = APIRouter(prefix="/erp/vendors", tags=["erp-vendors"])


class VendorIn(BaseModel):
    name: str
    gstin: str | None = None
    address: str | None = None
    state_code: str | None = None
    contact: str | None = None
    phone: str | None = None
    email: str | None = None
    category: str | None = None
    rating: int | None = None
    notes: str | None = None


class VendorPatch(BaseModel):
    name: str | None = None
    gstin: str | None = None
    address: str | None = None
    state_code: str | None = None
    contact: str | None = None
    phone: str | None = None
    email: str | None = None
    category: str | None = None
    rating: int | None = None
    notes: str | None = None


_COLS = "id, name, gstin, address, state_code, contact, phone, email, category, rating, notes"


@router.get("")
async def list_vendors(
    user: CurrentUser = Depends(erp_read_user),
    conn: AsyncConnection = Depends(db_session),
):
    rows = (await conn.execute(text(f"SELECT {_COLS} FROM vendors ORDER BY name"))).mappings().all()
    return [dict(r) for r in rows]


@router.get("/{vendor_id}")
async def get_vendor(
    vendor_id: str,
    user: CurrentUser = Depends(erp_read_user),
    conn: AsyncConnection = Depends(db_session),
):
    row = (await conn.execute(text(f"SELECT {_COLS} FROM vendors WHERE id = :id"), {"id": vendor_id})).mappings().first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="vendor not found")
    return dict(row)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_vendor(
    body: VendorIn,
    user: CurrentUser = Depends(erp_admin_user),
    conn: AsyncConnection = Depends(db_session),
):
    row = (
        await conn.execute(
            text(
                f"""
                INSERT INTO vendors (name, gstin, address, state_code, contact, phone, email, category, rating, notes)
                VALUES (:name, :gstin, :address, :state_code, :contact, :phone, :email, :category, :rating, :notes)
                RETURNING {_COLS}
                """
            ),
            body.model_dump(),
        )
    ).mappings().first()
    return dict(row)


@router.patch("/{vendor_id}")
async def update_vendor(
    vendor_id: str,
    body: VendorPatch,
    user: CurrentUser = Depends(erp_admin_user),
    conn: AsyncConnection = Depends(db_session),
):
    fields: dict[str, Any] = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        row = (await conn.execute(text(f"SELECT {_COLS} FROM vendors WHERE id = :id"), {"id": vendor_id})).mappings().first()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="vendor not found")
        return dict(row)

    set_clause = ", ".join(f"{k} = :{k}" for k in fields)
    fields["id"] = vendor_id
    row = (
        await conn.execute(
            text(f"UPDATE vendors SET {set_clause} WHERE id = :id RETURNING {_COLS}"),
            fields,
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="vendor not found")
    return dict(row)
