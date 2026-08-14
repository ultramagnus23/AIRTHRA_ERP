"""P5: projects CRUD. PRD 4.3 `projects` table - parent of drawings/boms/
tasks; mutually referenced with quotations via projects.quotation_id."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from ..erp_deps import CurrentUser, db_session, erp_admin_user, erp_read_user

router = APIRouter(prefix="/erp/projects", tags=["erp-projects"])

_COLS = "id, code, name, client, status, quotation_id"


class ProjectIn(BaseModel):
    code: str
    name: str
    client: str | None = None
    status: str = "active"
    quotation_id: str | None = None


class ProjectPatch(BaseModel):
    code: str | None = None
    name: str | None = None
    client: str | None = None
    status: str | None = None
    quotation_id: str | None = None


@router.get("")
async def list_projects(
    user: CurrentUser = Depends(erp_read_user),
    conn: AsyncConnection = Depends(db_session),
):
    rows = (await conn.execute(text(f"SELECT {_COLS} FROM projects ORDER BY code"))).mappings().all()
    return [dict(r) for r in rows]


@router.get("/{project_id}")
async def get_project(
    project_id: str,
    user: CurrentUser = Depends(erp_read_user),
    conn: AsyncConnection = Depends(db_session),
):
    row = (await conn.execute(text(f"SELECT {_COLS} FROM projects WHERE id = :id"), {"id": project_id})).mappings().first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found")
    return dict(row)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectIn,
    user: CurrentUser = Depends(erp_admin_user),
    conn: AsyncConnection = Depends(db_session),
):
    try:
        row = (
            await conn.execute(
                text(
                    f"""
                    INSERT INTO projects (code, name, client, status, quotation_id)
                    VALUES (:code, :name, :client, :status, :quotation_id)
                    RETURNING {_COLS}
                    """
                ),
                body.model_dump(),
            )
        ).mappings().first()
    except IntegrityError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"project code conflict: {exc.orig}") from exc
    return dict(row)


@router.patch("/{project_id}")
async def update_project(
    project_id: str,
    body: ProjectPatch,
    user: CurrentUser = Depends(erp_admin_user),
    conn: AsyncConnection = Depends(db_session),
):
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        row = (await conn.execute(text(f"SELECT {_COLS} FROM projects WHERE id = :id"), {"id": project_id})).mappings().first()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found")
        return dict(row)
    set_clause = ", ".join(f"{k} = :{k}" for k in fields)
    fields["id"] = project_id
    try:
        row = (
            await conn.execute(text(f"UPDATE projects SET {set_clause} WHERE id = :id RETURNING {_COLS}"), fields)
        ).mappings().first()
    except IntegrityError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"project code conflict: {exc.orig}") from exc
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found")
    return dict(row)
