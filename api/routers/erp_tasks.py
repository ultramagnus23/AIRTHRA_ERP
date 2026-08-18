"""P5: tasks CRUD. PRD 4.3 `tasks` table - project checklist items,
optionally blocked on a PO (blocked_by_po_id)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..dept_deps import CurrentUser, db_session, require_department, require_department_admin

erp_read_user = require_department("engineering")
erp_admin_user = require_department_admin("engineering")

router = APIRouter(prefix="/erp/tasks", tags=["erp-tasks"])

_COLS = "id, project_id, title, assignee, due, status, blocked_by_po_id"


class TaskIn(BaseModel):
    project_id: str | None = None
    title: str
    assignee: str | None = None
    due: str | None = None
    status: str = "open"
    blocked_by_po_id: str | None = None


class TaskPatch(BaseModel):
    project_id: str | None = None
    title: str | None = None
    assignee: str | None = None
    due: str | None = None
    status: str | None = None
    blocked_by_po_id: str | None = None


@router.get("")
async def list_tasks(
    project_id: str | None = Query(default=None),
    user: CurrentUser = Depends(erp_read_user),
    conn: AsyncConnection = Depends(db_session),
):
    if project_id:
        rows = (
            await conn.execute(
                text(f"SELECT {_COLS} FROM tasks WHERE project_id = :pid ORDER BY due NULLS LAST"),
                {"pid": project_id},
            )
        ).mappings().all()
    else:
        rows = (await conn.execute(text(f"SELECT {_COLS} FROM tasks ORDER BY due NULLS LAST"))).mappings().all()
    return [dict(r) for r in rows]


@router.get("/{task_id}")
async def get_task(
    task_id: str,
    user: CurrentUser = Depends(erp_read_user),
    conn: AsyncConnection = Depends(db_session),
):
    row = (await conn.execute(text(f"SELECT {_COLS} FROM tasks WHERE id = :id"), {"id": task_id})).mappings().first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    return dict(row)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_task(
    body: TaskIn,
    user: CurrentUser = Depends(erp_admin_user),
    conn: AsyncConnection = Depends(db_session),
):
    row = (
        await conn.execute(
            text(
                f"""
                INSERT INTO tasks (project_id, title, assignee, due, status, blocked_by_po_id)
                VALUES (:project_id, :title, :assignee, :due, :status, :blocked_by_po_id)
                RETURNING {_COLS}
                """
            ),
            body.model_dump(),
        )
    ).mappings().first()
    return dict(row)


@router.patch("/{task_id}")
async def update_task(
    task_id: str,
    body: TaskPatch,
    user: CurrentUser = Depends(erp_admin_user),
    conn: AsyncConnection = Depends(db_session),
):
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        row = (await conn.execute(text(f"SELECT {_COLS} FROM tasks WHERE id = :id"), {"id": task_id})).mappings().first()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
        return dict(row)
    set_clause = ", ".join(f"{k} = :{k}" for k in fields)
    fields["id"] = task_id
    row = (
        await conn.execute(text(f"UPDATE tasks SET {set_clause} WHERE id = :id RETURNING {_COLS}"), fields)
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    return dict(row)
