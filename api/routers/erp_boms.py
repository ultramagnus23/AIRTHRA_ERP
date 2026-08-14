"""P5: boms + bom_items CRUD, server-side material weight/cost calculator
(P5 item 2), and release immutability with revisioning (P5 item 8).

boms.status CHECK is ('draft', 'released') only - there is no 'superseded'
value for boms in the P0 schema (unlike drawings, which does have one).
So unlike drawings::revise, reviseing a released BOM does NOT flip the old
row's status (it stays 'released', which is also the immutable/historical
record of what was actually built) - the new row's supersedes_bom_id
points back at it, giving the same lineage without violating the CHECK
constraint. This is a deliberate, documented deviation from the drawings
pattern, forced by the schema (P0 is already migrated; this phase does not
alter it).
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..erp_calc import BomCalcError, compute_bom_item
from ..erp_deps import CurrentUser, db_session, erp_admin_user, erp_read_user

router = APIRouter(prefix="/erp/boms", tags=["erp-boms"])

_BOM_COLS = "id, project_id, drawing_id, name, revision, status, supersedes_bom_id"
_ITEM_COLS = ("id, bom_id, description, material_id, shape, dims, qty, scrap_pct, "
              "unit_weight_kg, total_weight_kg, cost")


class BomIn(BaseModel):
    project_id: str
    drawing_id: str | None = None
    name: str
    revision: str | None = None


class BomPatch(BaseModel):
    drawing_id: str | None = None
    name: str | None = None
    revision: str | None = None


class BomItemIn(BaseModel):
    description: str
    material_id: str
    shape: str
    dims: dict = {}
    qty: float = 1
    scrap_pct: float = 0


class BomItemPatch(BaseModel):
    description: str | None = None
    material_id: str | None = None
    shape: str | None = None
    dims: dict | None = None
    qty: float | None = None
    scrap_pct: float | None = None


class WeightPreviewIn(BaseModel):
    material_id: str
    shape: str
    dims: dict = {}
    qty: float = 1
    scrap_pct: float = 0


class ReviseIn(BaseModel):
    new_revision: str
    name: str | None = None
    drawing_id: str | None = None
    copy_items: bool = True


async def _get_bom(conn, bom_id: str) -> dict | None:
    row = (await conn.execute(text(f"SELECT {_BOM_COLS} FROM boms WHERE id = :id"), {"id": bom_id})).mappings().first()
    return dict(row) if row else None


async def _get_material(conn, material_id: str) -> dict | None:
    row = (
        await conn.execute(text("SELECT id, density_kg_m3, rate_per_kg FROM materials WHERE id = :id"), {"id": material_id})
    ).mappings().first()
    return dict(row) if row else None


async def _calc_or_400(conn, *, shape: str, dims: dict, qty: float, scrap_pct: float, material_id: str) -> dict:
    material = await _get_material(conn, material_id)
    if material is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"material '{material_id}' not found")
    try:
        return compute_bom_item(shape, dims, qty, scrap_pct, material["density_kg_m3"], material["rate_per_kg"])
    except BomCalcError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("")
async def list_boms(
    user: CurrentUser = Depends(erp_read_user),
    conn: AsyncConnection = Depends(db_session),
):
    rows = (await conn.execute(text(f"SELECT {_BOM_COLS} FROM boms ORDER BY name, revision"))).mappings().all()
    return [dict(r) for r in rows]


@router.get("/{bom_id}")
async def get_bom(
    bom_id: str,
    user: CurrentUser = Depends(erp_read_user),
    conn: AsyncConnection = Depends(db_session),
):
    bom = await _get_bom(conn, bom_id)
    if bom is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="bom not found")
    items = (
        await conn.execute(text(f"SELECT {_ITEM_COLS} FROM bom_items WHERE bom_id = :id ORDER BY id"), {"id": bom_id})
    ).mappings().all()
    bom["items"] = [dict(i) for i in items]
    return bom


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_bom(
    body: BomIn,
    user: CurrentUser = Depends(erp_admin_user),
    conn: AsyncConnection = Depends(db_session),
):
    row = (
        await conn.execute(
            text(
                f"""
                INSERT INTO boms (project_id, drawing_id, name, revision)
                VALUES (:project_id, :drawing_id, :name, :revision)
                RETURNING {_BOM_COLS}
                """
            ),
            body.model_dump(),
        )
    ).mappings().first()
    return dict(row)


@router.patch("/{bom_id}")
async def update_bom(
    bom_id: str,
    body: BomPatch,
    user: CurrentUser = Depends(erp_admin_user),
    conn: AsyncConnection = Depends(db_session),
):
    current = await _get_bom(conn, bom_id)
    if current is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="bom not found")
    if current["status"] == "released":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="bom is released and immutable - use POST /erp/boms/{id}/revise to create a new revision",
        )
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        return current
    set_clause = ", ".join(f"{k} = :{k}" for k in fields)
    fields["id"] = bom_id
    row = (
        await conn.execute(text(f"UPDATE boms SET {set_clause} WHERE id = :id RETURNING {_BOM_COLS}"), fields)
    ).mappings().first()
    return dict(row)


@router.post("/weight-preview")
async def weight_preview(
    body: WeightPreviewIn,
    user: CurrentUser = Depends(erp_read_user),
    conn: AsyncConnection = Depends(db_session),
):
    """Live-preview endpoint: computes weight/cost WITHOUT persisting, for a
    future frontend's "live weight as fields change" UX. Uses the exact
    same calculator as the persist path below - never trust client-computed
    weights, so this is also what create/update bom_items runs server-side."""
    return await _calc_or_400(
        conn, shape=body.shape, dims=body.dims, qty=body.qty, scrap_pct=body.scrap_pct, material_id=body.material_id
    )


@router.post("/{bom_id}/items", status_code=status.HTTP_201_CREATED)
async def add_bom_item(
    bom_id: str,
    body: BomItemIn,
    user: CurrentUser = Depends(erp_admin_user),
    conn: AsyncConnection = Depends(db_session),
):
    bom = await _get_bom(conn, bom_id)
    if bom is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="bom not found")
    if bom["status"] == "released":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="bom is released and immutable")

    calc = await _calc_or_400(
        conn, shape=body.shape, dims=body.dims, qty=body.qty, scrap_pct=body.scrap_pct, material_id=body.material_id
    )
    import json

    row = (
        await conn.execute(
            text(
                f"""
                INSERT INTO bom_items (bom_id, description, material_id, shape, dims, qty, scrap_pct,
                                        unit_weight_kg, total_weight_kg, cost)
                VALUES (:bom_id, :description, :material_id, :shape, CAST(:dims AS jsonb), :qty, :scrap_pct,
                        :unit_weight_kg, :total_weight_kg, :cost)
                RETURNING {_ITEM_COLS}
                """
            ),
            {
                "bom_id": bom_id,
                "description": body.description,
                "material_id": body.material_id,
                "shape": body.shape,
                "dims": json.dumps(body.dims),
                "qty": body.qty,
                "scrap_pct": body.scrap_pct,
                **calc,
            },
        )
    ).mappings().first()
    return dict(row)


@router.patch("/{bom_id}/items/{item_id}")
async def update_bom_item(
    bom_id: str,
    item_id: str,
    body: BomItemPatch,
    user: CurrentUser = Depends(erp_admin_user),
    conn: AsyncConnection = Depends(db_session),
):
    bom = await _get_bom(conn, bom_id)
    if bom is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="bom not found")
    if bom["status"] == "released":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="bom is released and immutable")

    current = (
        await conn.execute(text(f"SELECT {_ITEM_COLS} FROM bom_items WHERE id = :id AND bom_id = :bom_id"),
                            {"id": item_id, "bom_id": bom_id})
    ).mappings().first()
    if current is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="bom item not found")
    current = dict(current)

    merged = {
        "description": body.description if body.description is not None else current["description"],
        "material_id": body.material_id if body.material_id is not None else current["material_id"],
        "shape": body.shape if body.shape is not None else current["shape"],
        "dims": body.dims if body.dims is not None else current["dims"],
        "qty": body.qty if body.qty is not None else current["qty"],
        "scrap_pct": body.scrap_pct if body.scrap_pct is not None else current["scrap_pct"],
    }
    calc = await _calc_or_400(
        conn, shape=merged["shape"], dims=merged["dims"], qty=merged["qty"],
        scrap_pct=merged["scrap_pct"], material_id=merged["material_id"],
    )

    import json

    row = (
        await conn.execute(
            text(
                f"""
                UPDATE bom_items
                SET description = :description, material_id = :material_id, shape = :shape,
                    dims = CAST(:dims AS jsonb), qty = :qty, scrap_pct = :scrap_pct,
                    unit_weight_kg = :unit_weight_kg, total_weight_kg = :total_weight_kg, cost = :cost
                WHERE id = :id AND bom_id = :bom_id
                RETURNING {_ITEM_COLS}
                """
            ),
            {
                "id": item_id, "bom_id": bom_id,
                "description": merged["description"], "material_id": merged["material_id"],
                "shape": merged["shape"], "dims": json.dumps(merged["dims"]),
                "qty": merged["qty"], "scrap_pct": merged["scrap_pct"],
                **calc,
            },
        )
    ).mappings().first()
    return dict(row)


@router.delete("/{bom_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bom_item(
    bom_id: str,
    item_id: str,
    user: CurrentUser = Depends(erp_admin_user),
    conn: AsyncConnection = Depends(db_session),
):
    bom = await _get_bom(conn, bom_id)
    if bom is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="bom not found")
    if bom["status"] == "released":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="bom is released and immutable")
    result = await conn.execute(text("DELETE FROM bom_items WHERE id = :id AND bom_id = :bom_id"),
                                 {"id": item_id, "bom_id": bom_id})
    if result.rowcount == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="bom item not found")


@router.post("/{bom_id}/release")
async def release_bom(
    bom_id: str,
    user: CurrentUser = Depends(erp_admin_user),
    conn: AsyncConnection = Depends(db_session),
):
    bom = await _get_bom(conn, bom_id)
    if bom is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="bom not found")
    if bom["status"] == "released":
        return bom
    row = (
        await conn.execute(
            text(f"UPDATE boms SET status = 'released' WHERE id = :id RETURNING {_BOM_COLS}"),
            {"id": bom_id},
        )
    ).mappings().first()
    return dict(row)


@router.post("/{bom_id}/revise", status_code=status.HTTP_201_CREATED)
async def revise_bom(
    bom_id: str,
    body: ReviseIn,
    user: CurrentUser = Depends(erp_admin_user),
    conn: AsyncConnection = Depends(db_session),
):
    """Create a new BOM row (new revision), status='draft',
    supersedes_bom_id pointing back at the released BOM. Optionally copies
    all bom_items across as a starting point for edits. Only valid from a
    'released' bom."""
    current = await _get_bom(conn, bom_id)
    if current is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="bom not found")
    if current["status"] != "released":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="can only revise a released bom")

    new_id = str(uuid.uuid4())
    new_row = (
        await conn.execute(
            text(
                f"""
                INSERT INTO boms (id, project_id, drawing_id, name, revision, status, supersedes_bom_id)
                VALUES (:id, :project_id, :drawing_id, :name, :revision, 'draft', :supersedes_bom_id)
                RETURNING {_BOM_COLS}
                """
            ),
            {
                "id": new_id,
                "project_id": current["project_id"],
                "drawing_id": body.drawing_id if body.drawing_id is not None else current["drawing_id"],
                "name": body.name if body.name is not None else current["name"],
                "revision": body.new_revision,
                "supersedes_bom_id": bom_id,
            },
        )
    ).mappings().first()

    if body.copy_items:
        old_items = (
            await conn.execute(text(f"SELECT {_ITEM_COLS} FROM bom_items WHERE bom_id = :id"), {"id": bom_id})
        ).mappings().all()
        import json

        for it in old_items:
            it = dict(it)
            it["dims"] = json.dumps(it["dims"])
            await conn.execute(
                text(
                    """
                    INSERT INTO bom_items (bom_id, description, material_id, shape, dims, qty, scrap_pct,
                                            unit_weight_kg, total_weight_kg, cost)
                    VALUES (:bom_id, :description, :material_id, :shape, CAST(:dims AS jsonb), :qty, :scrap_pct,
                            :unit_weight_kg, :total_weight_kg, :cost)
                    """
                ),
                {**it, "bom_id": new_id},
            )

    return dict(new_row)
