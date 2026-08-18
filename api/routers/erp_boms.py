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

ENGINEERING CHANGE MANAGEMENT (migration 0010_bom_change_requests)
POST .../revise below is a direct action: an erp_admin_user creates a new
revision themselves, no separate approver, no recorded reason beyond
whatever they put in commit history. That's fine for an admin's own
change. The change-request endpoints further down are an ADDITIVE formal
path for changes that need a reviewable trail - request (with a reason)
-> approval by an erp_admin_user (who did not have to be the requester)
-> the new revision, atomically. Both paths end up calling the same
_create_revision() helper, so "was this revision governed by an ECR or
not" is answered by whether a bom_change_requests row points at it, not
by two different revision-creation code paths that could drift apart.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..erp_calc import BomCalcError, compute_bom_item
from ..dept_deps import CurrentUser, db_session, require_department, require_department_admin

erp_read_user = require_department("engineering")
erp_admin_user = require_department_admin("engineering")

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


_ECR_COLS = (
    "id, bom_id, reason, affected_note, requested_new_revision, status, "
    "requested_by, requested_at, reviewed_by, reviewed_at, review_note, resulting_bom_id"
)


@router.get("")
async def list_boms(
    user: CurrentUser = Depends(erp_read_user),
    conn: AsyncConnection = Depends(db_session),
):
    rows = (await conn.execute(text(f"SELECT {_BOM_COLS} FROM boms ORDER BY name, revision"))).mappings().all()
    return [dict(r) for r in rows]


@router.get("/change-requests")
async def list_change_requests(
    ecr_status: str | None = Query(default=None, alias="status"),
    bom_id: str | None = Query(default=None),
    user: CurrentUser = Depends(erp_read_user),
    conn: AsyncConnection = Depends(db_session),
):
    """Fleet-wide queue (no bom_id) or scoped to one BOM's history.

    MUST be registered before GET /{bom_id} below - FastAPI/Starlette
    matches routes in registration order, and "change-requests" would
    otherwise be captured as a bom_id path parameter by that route
    (same method, same single path segment) and never reach this one.
    """
    clauses, params = [], {}
    if ecr_status:
        clauses.append("status = :status")
        params["status"] = ecr_status
    if bom_id:
        clauses.append("bom_id = :bom_id")
        params["bom_id"] = bom_id
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    rows = (
        await conn.execute(
            text(f"SELECT {_ECR_COLS} FROM bom_change_requests {where} ORDER BY requested_at DESC"),
            params,
        )
    ).mappings().all()
    return {"change_requests": [dict(r) for r in rows]}


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


async def _create_revision(
    conn: AsyncConnection,
    current: dict,
    bom_id: str,
    new_revision: str,
    name: str | None,
    drawing_id: str | None,
    copy_items: bool,
) -> dict:
    """Shared by POST .../revise (direct) and the change-request approval
    path below - one place that actually inserts a new BOM revision, so
    the two entry points can never drift into different behaviour."""
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
                "drawing_id": drawing_id if drawing_id is not None else current["drawing_id"],
                "name": name if name is not None else current["name"],
                "revision": new_revision,
                "supersedes_bom_id": bom_id,
            },
        )
    ).mappings().first()

    if copy_items:
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


@router.post("/{bom_id}/revise", status_code=status.HTTP_201_CREATED)
async def revise_bom(
    bom_id: str,
    body: ReviseIn,
    user: CurrentUser = Depends(erp_admin_user),
    conn: AsyncConnection = Depends(db_session),
):
    """Direct revision, no change-request ceremony - see this module's
    ENGINEERING CHANGE MANAGEMENT docstring note for when to use this vs.
    the formal POST .../change-requests path below."""
    current = await _get_bom(conn, bom_id)
    if current is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="bom not found")
    if current["status"] != "released":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="can only revise a released bom")

    return await _create_revision(
        conn, current, bom_id, body.new_revision, body.name, body.drawing_id, body.copy_items
    )


# ---------------------------------------------------------------------------
# Engineering Change Management (migration 0010_bom_change_requests)
#
# _ECR_COLS and GET /change-requests are defined earlier in this file
# (immediately after the router is created), not here - see that
# definition's docstring for why the route registration order matters.
# ---------------------------------------------------------------------------


class ChangeRequestIn(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)
    affected_note: str | None = Field(default=None, max_length=1000)
    requested_new_revision: str = Field(min_length=1, max_length=50)
    copy_items: bool = True
    drawing_id: str | None = None
    name: str | None = None


class ReviewIn(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


@router.post("/{bom_id}/change-requests", status_code=status.HTTP_201_CREATED)
async def request_bom_change(
    bom_id: str,
    body: ChangeRequestIn,
    user: CurrentUser = Depends(erp_read_user),
    conn: AsyncConnection = Depends(db_session),
):
    """Any ERP user can REQUEST a change (erp_read_user, not admin-only) -
    per the spec's own workflow, the request step is not restricted to
    whoever can also approve it. Only valid against a 'released' bom, same
    precondition as the direct /revise endpoint."""
    bom = await _get_bom(conn, bom_id)
    if bom is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="bom not found")
    if bom["status"] != "released":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="can only request a change against a released bom - it has nothing to revise yet",
        )

    row = (
        await conn.execute(
            text(
                f"""
                INSERT INTO bom_change_requests
                    (bom_id, reason, affected_note, requested_new_revision, requested_by)
                VALUES (:bom_id, :reason, :affected_note, :requested_new_revision, :requested_by)
                RETURNING {_ECR_COLS}
                """
            ),
            {
                "bom_id": bom_id,
                "reason": body.reason,
                "affected_note": body.affected_note,
                "requested_new_revision": body.requested_new_revision,
                "requested_by": user.user_id,
            },
        )
    ).mappings().first()
    return dict(row)


async def _get_change_request(conn: AsyncConnection, ecr_id: str) -> dict | None:
    row = (
        await conn.execute(text(f"SELECT {_ECR_COLS} FROM bom_change_requests WHERE id = :id"), {"id": ecr_id})
    ).mappings().first()
    return dict(row) if row else None


@router.post("/change-requests/{ecr_id}/approve")
async def approve_change_request(
    ecr_id: str,
    body: ReviewIn,
    user: CurrentUser = Depends(erp_admin_user),
    conn: AsyncConnection = Depends(db_session),
):
    """Approving atomically creates the new draft revision - there is no
    window where a request is 'approved' but the revision doesn't exist
    yet, which would be a state an API client could observe and act on
    incorrectly (e.g. start editing a revision that isn't there)."""
    ecr = await _get_change_request(conn, ecr_id)
    if ecr is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="change request not found")
    if ecr["status"] != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"change request is '{ecr['status']}', not 'pending'")

    bom = await _get_bom(conn, ecr["bom_id"])
    if bom is None or bom["status"] != "released":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="the bom this request targets is no longer 'released' (already revised by another path)",
        )

    new_bom = await _create_revision(
        conn, bom, ecr["bom_id"], ecr["requested_new_revision"],
        None, None, copy_items=True,
    )

    row = (
        await conn.execute(
            text(
                f"""
                UPDATE bom_change_requests
                SET status = 'approved', reviewed_by = :reviewed_by, reviewed_at = now(),
                    review_note = :note, resulting_bom_id = :resulting_bom_id
                WHERE id = :id
                RETURNING {_ECR_COLS}
                """
            ),
            {"id": ecr_id, "reviewed_by": user.user_id, "note": body.note, "resulting_bom_id": new_bom["id"]},
        )
    ).mappings().first()
    return {"change_request": dict(row), "new_bom": new_bom}


@router.post("/change-requests/{ecr_id}/reject")
async def reject_change_request(
    ecr_id: str,
    body: ReviewIn,
    user: CurrentUser = Depends(erp_admin_user),
    conn: AsyncConnection = Depends(db_session),
):
    ecr = await _get_change_request(conn, ecr_id)
    if ecr is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="change request not found")
    if ecr["status"] != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"change request is '{ecr['status']}', not 'pending'")
    if not body.note:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="a rejection requires a note explaining why")

    row = (
        await conn.execute(
            text(
                f"""
                UPDATE bom_change_requests
                SET status = 'rejected', reviewed_by = :reviewed_by, reviewed_at = now(), review_note = :note
                WHERE id = :id
                RETURNING {_ECR_COLS}
                """
            ),
            {"id": ecr_id, "reviewed_by": user.user_id, "note": body.note},
        )
    ).mappings().first()
    return dict(row)
