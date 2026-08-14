"""P5: quotations + quotation_lines CRUD. PRD 4.3 `quotations`/
`quotation_lines`. quotations.party_id is intentionally not an FK (see
migration comment: direction='vendor' -> vendors.id, direction='customer'
has no customers table in P0) - the API does not attempt to validate it
beyond direction-appropriate use, matching that documented deviation."""
from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..erp_deps import CurrentUser, db_session, erp_admin_user, erp_read_user

router = APIRouter(prefix="/erp/quotations", tags=["erp-quotations"])

_COLS = "id, direction, party_id, project_id, ref_no, date, valid_till, file_url, sha256, status"
_LINE_COLS = "id, quotation_id, description, qty, unit, rate"


class QuotationIn(BaseModel):
    direction: str
    party_id: str
    project_id: str | None = None
    ref_no: str | None = None
    date: str | None = None
    valid_till: str | None = None
    file_url: str | None = None
    sha256: str | None = None
    status: str = "draft"


class QuotationPatch(BaseModel):
    ref_no: str | None = None
    date: str | None = None
    valid_till: str | None = None
    file_url: str | None = None
    sha256: str | None = None
    status: str | None = None
    project_id: str | None = None


class QuotationLineIn(BaseModel):
    description: str
    qty: Decimal
    unit: str
    rate: Decimal


async def _get_quotation(conn, quotation_id: str) -> dict | None:
    row = (
        await conn.execute(text(f"SELECT {_COLS} FROM quotations WHERE id = :id"), {"id": quotation_id})
    ).mappings().first()
    return dict(row) if row else None


@router.get("")
async def list_quotations(
    user: CurrentUser = Depends(erp_read_user),
    conn: AsyncConnection = Depends(db_session),
):
    rows = (await conn.execute(text(f"SELECT {_COLS} FROM quotations ORDER BY date DESC NULLS LAST"))).mappings().all()
    return [dict(r) for r in rows]


@router.get("/{quotation_id}")
async def get_quotation(
    quotation_id: str,
    user: CurrentUser = Depends(erp_read_user),
    conn: AsyncConnection = Depends(db_session),
):
    q = await _get_quotation(conn, quotation_id)
    if q is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="quotation not found")
    lines = (
        await conn.execute(
            text(f"SELECT {_LINE_COLS} FROM quotation_lines WHERE quotation_id = :id ORDER BY id"),
            {"id": quotation_id},
        )
    ).mappings().all()
    q["lines"] = [dict(l) for l in lines]
    return q


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_quotation(
    body: QuotationIn,
    user: CurrentUser = Depends(erp_admin_user),
    conn: AsyncConnection = Depends(db_session),
):
    if body.direction not in ("vendor", "customer"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="direction must be 'vendor' or 'customer'")
    row = (
        await conn.execute(
            text(
                f"""
                INSERT INTO quotations (direction, party_id, project_id, ref_no, date, valid_till, file_url, sha256, status)
                VALUES (:direction, :party_id, :project_id, :ref_no, :date, :valid_till, :file_url, :sha256, :status)
                RETURNING {_COLS}
                """
            ),
            body.model_dump(),
        )
    ).mappings().first()
    return dict(row)


@router.patch("/{quotation_id}")
async def update_quotation(
    quotation_id: str,
    body: QuotationPatch,
    user: CurrentUser = Depends(erp_admin_user),
    conn: AsyncConnection = Depends(db_session),
):
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        q = await _get_quotation(conn, quotation_id)
        if q is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="quotation not found")
        return q
    set_clause = ", ".join(f"{k} = :{k}" for k in fields)
    fields["id"] = quotation_id
    row = (
        await conn.execute(text(f"UPDATE quotations SET {set_clause} WHERE id = :id RETURNING {_COLS}"), fields)
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="quotation not found")
    return dict(row)


@router.post("/{quotation_id}/lines", status_code=status.HTTP_201_CREATED)
async def add_quotation_line(
    quotation_id: str,
    body: QuotationLineIn,
    user: CurrentUser = Depends(erp_admin_user),
    conn: AsyncConnection = Depends(db_session),
):
    q = await _get_quotation(conn, quotation_id)
    if q is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="quotation not found")
    row = (
        await conn.execute(
            text(
                f"""
                INSERT INTO quotation_lines (quotation_id, description, qty, unit, rate)
                VALUES (:quotation_id, :description, :qty, :unit, :rate)
                RETURNING {_LINE_COLS}
                """
            ),
            {"quotation_id": quotation_id, **body.model_dump()},
        )
    ).mappings().first()
    return dict(row)


@router.delete("/{quotation_id}/lines/{line_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_quotation_line(
    quotation_id: str,
    line_id: str,
    user: CurrentUser = Depends(erp_admin_user),
    conn: AsyncConnection = Depends(db_session),
):
    result = await conn.execute(
        text("DELETE FROM quotation_lines WHERE id = :id AND quotation_id = :qid"),
        {"id": line_id, "qid": quotation_id},
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="quotation line not found")
