"""P6: production / QC / inventory endpoints.

Covers GRN (read-only here - P5 owns ERP procurement and may build the
write side of GRN receiving under api/routers/erp_*.py; if/when it lands,
these GET endpoints keep working unchanged), inventory_lots, issue_lines
(material issue to a fabrication job, the qty_on_hand debit that must never
go negative), fabrication_jobs/unit_serials status transitions, qc_records,
and installations (the literal ERP <-> machine-data bridge table).

Pydantic request models are defined locally in this file rather than added
to api/schemas.py, to avoid touching a file other concurrent phases may
also be editing.
"""
from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..deps import CurrentUser, db_session, get_current_user, require_plant_access

router = APIRouter(prefix="/erp", tags=["production"])


# ---------------------------------------------------------------------------
# GRN (read-only)
# ---------------------------------------------------------------------------

@router.get("/grn")
async def list_grn(
    po_id: str | None = Query(default=None),
    user: CurrentUser = Depends(get_current_user),
    conn: AsyncConnection = Depends(db_session),
):
    rows = (
        await conn.execute(
            text(
                """
                SELECT id, po_id, grn_no, date, received_by, vehicle_no, eway_bill_no, notes
                FROM grn
                WHERE CAST(:po_id AS uuid) IS NULL OR po_id = :po_id
                ORDER BY date DESC
                """
            ),
            {"po_id": po_id},
        )
    ).mappings().all()
    return {"grn": [dict(r) for r in rows]}


@router.get("/grn/{grn_id}")
async def get_grn(
    grn_id: str,
    user: CurrentUser = Depends(get_current_user),
    conn: AsyncConnection = Depends(db_session),
):
    grn = (
        await conn.execute(
            text(
                """
                SELECT id, po_id, grn_no, date, received_by, vehicle_no, eway_bill_no, notes
                FROM grn WHERE id = :id
                """
            ),
            {"id": grn_id},
        )
    ).mappings().first()
    if grn is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"grn '{grn_id}' not found")
    lines = (
        await conn.execute(
            text(
                """
                SELECT id, grn_id, po_item_id, qty_received, qty_accepted, qty_rejected
                FROM grn_lines WHERE grn_id = :id
                """
            ),
            {"id": grn_id},
        )
    ).mappings().all()
    return {"grn": dict(grn), "lines": [dict(r) for r in lines]}


# ---------------------------------------------------------------------------
# Inventory lots
# ---------------------------------------------------------------------------

@router.get("/inventory-lots")
async def list_inventory_lots(
    material_id: str | None = Query(default=None),
    user: CurrentUser = Depends(get_current_user),
    conn: AsyncConnection = Depends(db_session),
):
    rows = (
        await conn.execute(
            text(
                """
                SELECT lot_id, grn_line_id, material_id, qty_on_hand, unit, location,
                       heat_no, mtc_url, sha256
                FROM inventory_lots
                WHERE CAST(:material_id AS uuid) IS NULL OR material_id = :material_id
                ORDER BY lot_id
                """
            ),
            {"material_id": material_id},
        )
    ).mappings().all()
    return {"lots": [dict(r) for r in rows]}


@router.get("/inventory-lots/{lot_id}")
async def get_inventory_lot(
    lot_id: str,
    user: CurrentUser = Depends(get_current_user),
    conn: AsyncConnection = Depends(db_session),
):
    row = (
        await conn.execute(
            text(
                """
                SELECT lot_id, grn_line_id, material_id, qty_on_hand, unit, location,
                       heat_no, mtc_url, sha256
                FROM inventory_lots WHERE lot_id = :id
                """
            ),
            {"id": lot_id},
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"lot '{lot_id}' not found")
    return dict(row)


# ---------------------------------------------------------------------------
# Issue lines (material issue -> fabrication job, debits qty_on_hand)
# ---------------------------------------------------------------------------

class IssueLineCreate(BaseModel):
    lot_id: str
    qty: float = Field(gt=0)
    fabrication_job_id: str | None = None


@router.post("/issue-lines", status_code=status.HTTP_201_CREATED)
async def create_issue_line(
    body: IssueLineCreate,
    user: CurrentUser = Depends(get_current_user),
    conn: AsyncConnection = Depends(db_session),
):
    # Atomic debit: the UPDATE's WHERE clause re-checks qty_on_hand >= qty in
    # the same statement as the decrement, so this is safe under concurrent
    # issues against the same lot (no read-then-write race) - if another
    # transaction already drained the lot, this UPDATE simply matches zero
    # rows and we reject with 400, never allowing qty_on_hand to go negative.
    updated = (
        await conn.execute(
            text(
                """
                UPDATE inventory_lots
                SET qty_on_hand = qty_on_hand - :qty
                WHERE lot_id = :lot_id AND qty_on_hand >= :qty
                RETURNING lot_id, qty_on_hand
                """
            ),
            {"lot_id": body.lot_id, "qty": body.qty},
        )
    ).mappings().first()

    if updated is None:
        # Distinguish "lot doesn't exist" from "insufficient qty" for a
        # useful error message rather than a generic 400.
        exists = (
            await conn.execute(
                text("SELECT qty_on_hand FROM inventory_lots WHERE lot_id = :id"),
                {"id": body.lot_id},
            )
        ).first()
        if exists is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"lot '{body.lot_id}' not found",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"insufficient qty_on_hand ({exists[0]}) for lot '{body.lot_id}' "
                   f"to issue {body.qty}",
        )

    issue_id = str(uuid.uuid4())
    row = (
        await conn.execute(
            text(
                """
                INSERT INTO issue_lines (id, lot_id, qty, fabrication_job_id, issued_by)
                VALUES (:id, :lot_id, :qty, :job_id, :issued_by)
                RETURNING id, lot_id, qty, fabrication_job_id, issued_at, issued_by
                """
            ),
            {
                "id": issue_id,
                "lot_id": body.lot_id,
                "qty": body.qty,
                "job_id": body.fabrication_job_id,
                "issued_by": user.user_id or None,
            },
        )
    ).mappings().first()
    return {"issue_line": dict(row), "lot_qty_on_hand": updated["qty_on_hand"]}


# ---------------------------------------------------------------------------
# Fabrication jobs: status transitions
# ---------------------------------------------------------------------------

_JOB_STATUSES = ("planned", "in_progress", "on_hold", "completed", "cancelled")
_JOB_TRANSITIONS = {
    "planned": {"in_progress", "cancelled"},
    "in_progress": {"on_hold", "completed", "cancelled"},
    "on_hold": {"in_progress", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}


class FabricationJobStatusUpdate(BaseModel):
    status: Literal["planned", "in_progress", "on_hold", "completed", "cancelled"]


@router.patch("/fabrication-jobs/{job_id}/status")
async def update_fabrication_job_status(
    job_id: str,
    body: FabricationJobStatusUpdate,
    user: CurrentUser = Depends(get_current_user),
    conn: AsyncConnection = Depends(db_session),
):
    current = (
        await conn.execute(
            text("SELECT status FROM fabrication_jobs WHERE id = :id"),
            {"id": job_id},
        )
    ).first()
    if current is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"job '{job_id}' not found")

    cur_status = current[0]
    if body.status != cur_status and body.status not in _JOB_TRANSITIONS[cur_status]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"invalid transition '{cur_status}' -> '{body.status}'",
        )

    set_started = ", started = COALESCE(started, now())" if body.status == "in_progress" else ""
    set_finished = ", finished = now()" if body.status in ("completed", "cancelled") else ""
    row = (
        await conn.execute(
            text(
                f"""
                UPDATE fabrication_jobs
                SET status = :status {set_started} {set_finished}
                WHERE id = :id
                RETURNING id, project_id, bom_id, unit_serial, status, started, finished
                """
            ),
            {"id": job_id, "status": body.status},
        )
    ).mappings().first()
    return dict(row)


# ---------------------------------------------------------------------------
# Unit serials: status transitions (fabrication -> qc -> dispatched -> installed)
# ---------------------------------------------------------------------------

_SERIAL_ORDER = ("fabrication", "qc", "dispatched", "installed")


class UnitSerialStatusUpdate(BaseModel):
    status: Literal["fabrication", "qc", "dispatched", "installed"]


@router.patch("/unit-serials/{serial}/status")
async def update_unit_serial_status(
    serial: str,
    body: UnitSerialStatusUpdate,
    user: CurrentUser = Depends(get_current_user),
    conn: AsyncConnection = Depends(db_session),
):
    current = (
        await conn.execute(
            text("SELECT status FROM unit_serials WHERE serial = :serial"),
            {"serial": serial},
        )
    ).first()
    if current is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"serial '{serial}' not found")

    cur_status = current[0]
    cur_idx = _SERIAL_ORDER.index(cur_status)
    new_idx = _SERIAL_ORDER.index(body.status)
    if new_idx != cur_idx + 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unit_serials only advance one step forward: "
                   f"'{cur_status}' -> '{_SERIAL_ORDER[cur_idx + 1] if cur_idx + 1 < len(_SERIAL_ORDER) else 'n/a'}' "
                   f"expected, got '{body.status}'",
        )

    row = (
        await conn.execute(
            text(
                """
                UPDATE unit_serials SET status = :status WHERE serial = :serial
                RETURNING serial, model, project_id, status
                """
            ),
            {"serial": serial, "status": body.status},
        )
    ).mappings().first()
    return dict(row)


# ---------------------------------------------------------------------------
# QC records
# ---------------------------------------------------------------------------

class QcRecordCreate(BaseModel):
    lot_id: str | None = None
    job_id: str | None = None
    unit_serial: str | None = None
    type: Literal["incoming", "in_process", "final"]
    result: str | None = None
    inspector: str | None = None
    report_url: str | None = None
    sha256: str | None = None


@router.post("/qc-records", status_code=status.HTTP_201_CREATED)
async def create_qc_record(
    body: QcRecordCreate,
    user: CurrentUser = Depends(get_current_user),
    conn: AsyncConnection = Depends(db_session),
):
    if body.lot_id is None and body.job_id is None and body.unit_serial is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="at least one of lot_id, job_id, unit_serial is required",
        )
    qc_id = str(uuid.uuid4())
    try:
        row = (
            await conn.execute(
                text(
                    """
                    INSERT INTO qc_records (id, lot_id, job_id, unit_serial, type, result,
                                             inspector, report_url, sha256)
                    VALUES (:id, :lot_id, :job_id, :unit_serial, :type, :result,
                            :inspector, :report_url, :sha256)
                    RETURNING id, lot_id, job_id, unit_serial, type, result, inspector, ts, report_url, sha256
                    """
                ),
                {
                    "id": qc_id,
                    "lot_id": body.lot_id,
                    "job_id": body.job_id,
                    "unit_serial": body.unit_serial,
                    "type": body.type,
                    "result": body.result,
                    "inspector": body.inspector,
                    "report_url": body.report_url,
                    "sha256": body.sha256,
                },
            )
        ).mappings().first()
    except Exception as exc:  # FK violation on a bad lot_id/job_id/unit_serial
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return dict(row)


# ---------------------------------------------------------------------------
# Installations: the ERP <-> machine-data bridge (serial -> plant_id)
# ---------------------------------------------------------------------------

class InstallationCreate(BaseModel):
    serial: str
    plant_id: str
    installed_at: str | None = None
    commissioned_at: str | None = None


@router.post("/installations", status_code=status.HTTP_201_CREATED)
async def create_installation(
    body: InstallationCreate,
    user: CurrentUser = Depends(get_current_user),
    conn: AsyncConnection = Depends(db_session),
):
    # installations carries plant_id + native RLS (see migrations/README.md);
    # explicit 403 check here is defense-in-depth, matching the codebase
    # convention (api/deps.py docstring) of never silently relying on RLS
    # alone to turn an unauthorized write into an empty result.
    require_plant_access(user, body.plant_id)

    inst_id = str(uuid.uuid4())
    try:
        row = (
            await conn.execute(
                text(
                    """
                    INSERT INTO installations (id, serial, plant_id, installed_at, commissioned_at)
                    VALUES (:id, :serial, :plant_id, :installed_at, :commissioned_at)
                    RETURNING id, serial, plant_id, installed_at, commissioned_at
                    """
                ),
                {
                    "id": inst_id,
                    "serial": body.serial,
                    "plant_id": body.plant_id,
                    "installed_at": body.installed_at,
                    "commissioned_at": body.commissioned_at,
                },
            )
        ).mappings().first()
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return dict(row)


@router.get("/installations")
async def list_installations(
    serial: str | None = Query(default=None),
    plant_id: str | None = Query(default=None),
    user: CurrentUser = Depends(get_current_user),
    conn: AsyncConnection = Depends(db_session),
):
    if plant_id is not None:
        require_plant_access(user, plant_id)
    rows = (
        await conn.execute(
            text(
                """
                SELECT id, serial, plant_id, installed_at, commissioned_at
                FROM installations
                WHERE (CAST(:serial AS text) IS NULL OR serial = :serial)
                  AND (CAST(:plant_id AS text) IS NULL OR plant_id = :plant_id)
                ORDER BY installed_at NULLS LAST
                """
            ),
            {"serial": serial, "plant_id": plant_id},
        )
    ).mappings().all()
    return {"installations": [dict(r) for r in rows]}
