"""P6 acceptance gate: genealogy queries.

Forward-trace (lot -> everywhere it went) and recall-trace (vendor+date
range -> every plant that could have received affected material) are the
literal P6 acceptance gate per the PRD. Both are implemented as a small,
fixed number of well-indexed queries (never N+1: one query per "hop level",
fanned out in Python over already-fetched id lists) rather than one giant
join, so partial chains (e.g. a lot never issued to any job yet) don't
collapse the whole response via INNER JOINs.

No plant_id-scoped RLS applies to any table touched here (vendors, pos,
grn, inventory_lots, qc_records, fabrication_jobs, unit_serials are all
company-wide ERP tables per migrations/README.md - "not partitioned per
plant"). installations DOES have plant_id + RLS, so a tenant_read caller
only sees the installations/plants rows within their own scope; a
global_admin/global_read caller (BYPASSRLS) sees the full genealogy. This
is enforced automatically by api/db.py's role-based connection - no extra
code needed here.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..deps import CurrentUser, db_session, get_current_user

router = APIRouter(prefix="/erp/genealogy", tags=["genealogy"])


@router.get("/lot/{lot_id}")
async def forward_trace(
    lot_id: str,
    user: CurrentUser = Depends(get_current_user),
    conn: AsyncConnection = Depends(db_session),
):
    """Forward-trace: everything downstream (and the vendor/PO/GRN upstream)
    of a single inventory lot."""
    lot = (
        await conn.execute(
            text(
                """
                SELECT l.lot_id, l.material_id, m.name AS material_name, l.qty_on_hand,
                       l.unit, l.location, l.heat_no, l.mtc_url, l.sha256,
                       l.grn_line_id,
                       gl.grn_id, gl.po_item_id, gl.qty_received, gl.qty_accepted, gl.qty_rejected,
                       g.grn_no, g.date AS grn_date, g.vehicle_no, g.eway_bill_no,
                       poi.po_id,
                       p.po_no, p.po_date, p.status AS po_status,
                       p.vendor_id, v.name AS vendor_name, v.gstin AS vendor_gstin
                FROM inventory_lots l
                JOIN materials m ON m.id = l.material_id
                LEFT JOIN grn_lines gl ON gl.id = l.grn_line_id
                LEFT JOIN grn g ON g.id = gl.grn_id
                LEFT JOIN po_items poi ON poi.id = gl.po_item_id
                LEFT JOIN pos p ON p.id = poi.po_id
                LEFT JOIN vendors v ON v.id = p.vendor_id
                WHERE l.lot_id = :lot_id
                """
            ),
            {"lot_id": lot_id},
        )
    ).mappings().first()
    if lot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"lot '{lot_id}' not found")

    qc_records = (
        await conn.execute(
            text(
                """
                SELECT id, lot_id, job_id, unit_serial, type, result, inspector, ts, report_url, sha256
                FROM qc_records
                WHERE lot_id = :lot_id
                ORDER BY ts
                """
            ),
            {"lot_id": lot_id},
        )
    ).mappings().all()

    issue_lines = (
        await conn.execute(
            text(
                """
                SELECT id, lot_id, qty, fabrication_job_id, issued_at, issued_by
                FROM issue_lines
                WHERE lot_id = :lot_id
                ORDER BY issued_at
                """
            ),
            {"lot_id": lot_id},
        )
    ).mappings().all()

    job_ids = sorted({str(r["fabrication_job_id"]) for r in issue_lines if r["fabrication_job_id"]})
    fabrication_jobs: list[dict] = []
    unit_serials: list[dict] = []
    installations: list[dict] = []

    if job_ids:
        fabrication_jobs = (
            await conn.execute(
                text(
                    """
                    SELECT id, project_id, bom_id, unit_serial, status, started, finished
                    FROM fabrication_jobs
                    WHERE id = ANY(:job_ids)
                    ORDER BY id
                    """
                ),
                {"job_ids": job_ids},
            )
        ).mappings().all()
        fabrication_jobs = [dict(r) for r in fabrication_jobs]

        serials = sorted({r["unit_serial"] for r in fabrication_jobs if r["unit_serial"]})
        if serials:
            unit_serials = (
                await conn.execute(
                    text(
                        """
                        SELECT serial, model, project_id, status
                        FROM unit_serials
                        WHERE serial = ANY(:serials)
                        ORDER BY serial
                        """
                    ),
                    {"serials": serials},
                )
            ).mappings().all()
            unit_serials = [dict(r) for r in unit_serials]

            installations = (
                await conn.execute(
                    text(
                        """
                        SELECT id, serial, plant_id, installed_at, commissioned_at
                        FROM installations
                        WHERE serial = ANY(:serials)
                        ORDER BY installed_at NULLS LAST
                        """
                    ),
                    {"serials": serials},
                )
            ).mappings().all()
            installations = [dict(r) for r in installations]

    return {
        "lot": dict(lot),
        "qc_records": [dict(r) for r in qc_records],
        "issue_lines": [dict(r) for r in issue_lines],
        "fabrication_jobs": fabrication_jobs,
        "unit_serials": unit_serials,
        "installations": installations,
    }


@router.get("/vendor-recall")
async def recall_trace(
    vendor_id: str = Query(...),
    start: date = Query(...),
    end: date = Query(...),
    user: CurrentUser = Depends(get_current_user),
    conn: AsyncConnection = Depends(db_session),
):
    """Recall-trace: every plant that ever received material from
    `vendor_id` via a PO dated within [start, end], walked all the way
    through POs -> GRNs -> lots -> issue_lines -> fabrication_jobs ->
    unit_serials -> installations -> plants.
    """
    if end < start:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="end must be >= start")

    vendor = (
        await conn.execute(
            text("SELECT id, name, gstin FROM vendors WHERE id = :id"),
            {"id": vendor_id},
        )
    ).mappings().first()
    if vendor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"vendor '{vendor_id}' not found")

    # Single walk, one query, covering the whole chain via joins - safe here
    # (unlike the forward-trace) because every hop is INNER-joinable by
    # definition of "material that actually reached an installed plant";
    # rows that don't yet have a fabrication_job/unit_serial/installation
    # simply don't contribute a plant to the recall set, which is correct
    # recall semantics (nothing to recall at a plant it never reached).
    rows = (
        await conn.execute(
            text(
                """
                SELECT DISTINCT
                    pl.plant_id, pl.name AS plant_name,
                    p.id AS po_id, p.po_no, p.po_date,
                    g.id AS grn_id, g.grn_no, g.date AS grn_date,
                    l.lot_id, l.heat_no,
                    fj.id AS fabrication_job_id,
                    us.serial AS unit_serial,
                    i.id AS installation_id, i.installed_at, i.commissioned_at
                FROM pos p
                JOIN po_items poi ON poi.po_id = p.id
                JOIN grn_lines gl ON gl.po_item_id = poi.id
                JOIN grn g ON g.id = gl.grn_id
                JOIN inventory_lots l ON l.grn_line_id = gl.id
                JOIN issue_lines il ON il.lot_id = l.lot_id
                JOIN fabrication_jobs fj ON fj.id = il.fabrication_job_id
                JOIN unit_serials us ON us.serial = fj.unit_serial
                JOIN installations i ON i.serial = us.serial
                JOIN plants pl ON pl.plant_id = i.plant_id
                WHERE p.vendor_id = :vendor_id
                  AND p.po_date BETWEEN :start AND :end
                ORDER BY pl.plant_id, p.po_no
                """
            ),
            {"vendor_id": vendor_id, "start": start, "end": end},
        )
    ).mappings().all()

    plants: dict[str, dict] = {}
    chains: list[dict] = []
    for r in rows:
        r = dict(r)
        chains.append(r)
        pid = r["plant_id"]
        if pid not in plants:
            plants[pid] = {"plant_id": pid, "plant_name": r["plant_name"]}

    return {
        "vendor": dict(vendor),
        "start": start,
        "end": end,
        "affected_plants": sorted(plants.values(), key=lambda x: x["plant_id"]),
        "chains": chains,
    }
