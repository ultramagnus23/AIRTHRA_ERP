"""P5: drawings CRUD + release immutability (P5 item 8).

drawings.status: draft | for_review | released | superseded (P0 migration).
Once a drawing is 'released', PATCH is rejected (409) - further changes
must go through POST /erp/drawings/{id}/revise, which creates a new
drawing row (new revision string, status='draft') and flips the old row's
status to 'superseded'.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..erp_deps import CurrentUser, db_session, erp_admin_user, erp_read_user

router = APIRouter(prefix="/erp/drawings", tags=["erp-drawings"])

_COLS = "id, project_id, dwg_no, title, revision, file_url, sha256, status, released_by, released_at"


class DrawingIn(BaseModel):
    project_id: str
    dwg_no: str
    title: str | None = None
    revision: str | None = None
    file_url: str | None = None
    sha256: str | None = None


class DrawingPatch(BaseModel):
    title: str | None = None
    revision: str | None = None
    file_url: str | None = None
    sha256: str | None = None
    status: str | None = None


class ReviseIn(BaseModel):
    new_revision: str
    title: str | None = None
    file_url: str | None = None
    sha256: str | None = None


async def _get(conn, drawing_id: str) -> dict | None:
    row = (await conn.execute(text(f"SELECT {_COLS} FROM drawings WHERE id = :id"), {"id": drawing_id})).mappings().first()
    return dict(row) if row else None


@router.get("")
async def list_drawings(
    user: CurrentUser = Depends(erp_read_user),
    conn: AsyncConnection = Depends(db_session),
):
    rows = (await conn.execute(text(f"SELECT {_COLS} FROM drawings ORDER BY dwg_no, revision"))).mappings().all()
    return [dict(r) for r in rows]


@router.get("/{drawing_id}")
async def get_drawing(
    drawing_id: str,
    user: CurrentUser = Depends(erp_read_user),
    conn: AsyncConnection = Depends(db_session),
):
    row = await _get(conn, drawing_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="drawing not found")
    return row


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_drawing(
    body: DrawingIn,
    user: CurrentUser = Depends(erp_admin_user),
    conn: AsyncConnection = Depends(db_session),
):
    row = (
        await conn.execute(
            text(
                f"""
                INSERT INTO drawings (project_id, dwg_no, title, revision, file_url, sha256)
                VALUES (:project_id, :dwg_no, :title, :revision, :file_url, :sha256)
                RETURNING {_COLS}
                """
            ),
            body.model_dump(),
        )
    ).mappings().first()
    return dict(row)


@router.patch("/{drawing_id}")
async def update_drawing(
    drawing_id: str,
    body: DrawingPatch,
    user: CurrentUser = Depends(erp_admin_user),
    conn: AsyncConnection = Depends(db_session),
):
    current = await _get(conn, drawing_id)
    if current is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="drawing not found")
    if current["status"] == "released":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="drawing is released and immutable - use POST /erp/drawings/{id}/revise to create a new revision",
        )

    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        return current
    set_clause = ", ".join(f"{k} = :{k}" for k in fields)
    fields["id"] = drawing_id
    row = (
        await conn.execute(text(f"UPDATE drawings SET {set_clause} WHERE id = :id RETURNING {_COLS}"), fields)
    ).mappings().first()
    return dict(row)


@router.post("/{drawing_id}/release")
async def release_drawing(
    drawing_id: str,
    user: CurrentUser = Depends(erp_admin_user),
    conn: AsyncConnection = Depends(db_session),
):
    current = await _get(conn, drawing_id)
    if current is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="drawing not found")
    if current["status"] == "released":
        return current
    if current["status"] == "superseded":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="cannot release a superseded drawing")

    row = (
        await conn.execute(
            text(
                f"""
                UPDATE drawings
                SET status = 'released', released_by = :uid, released_at = now()
                WHERE id = :id
                RETURNING {_COLS}
                """
            ),
            {"id": drawing_id, "uid": user.user_id or None},
        )
    ).mappings().first()
    return dict(row)


@router.post("/{drawing_id}/revise", status_code=status.HTTP_201_CREATED)
async def revise_drawing(
    drawing_id: str,
    body: ReviseIn,
    user: CurrentUser = Depends(erp_admin_user),
    conn: AsyncConnection = Depends(db_session),
):
    """Create a new drawing row (new revision) carrying forward
    project_id/dwg_no from the old one, and flip the old row to
    'superseded'. Only valid from a 'released' drawing (that's the whole
    point of immutability - draft/for_review rows should just be PATCHed)."""
    current = await _get(conn, drawing_id)
    if current is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="drawing not found")
    if current["status"] != "released":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="can only revise a released drawing")

    new_id = str(uuid.uuid4())
    new_row = (
        await conn.execute(
            text(
                f"""
                INSERT INTO drawings (id, project_id, dwg_no, title, revision, file_url, sha256, status)
                VALUES (:id, :project_id, :dwg_no, :title, :revision, :file_url, :sha256, 'draft')
                RETURNING {_COLS}
                """
            ),
            {
                "id": new_id,
                "project_id": current["project_id"],
                "dwg_no": current["dwg_no"],
                "title": body.title if body.title is not None else current["title"],
                "revision": body.new_revision,
                "file_url": body.file_url,
                "sha256": body.sha256,
            },
        )
    ).mappings().first()

    await conn.execute(text("UPDATE drawings SET status = 'superseded' WHERE id = :id"), {"id": drawing_id})
    return dict(new_row)
