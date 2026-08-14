#!/usr/bin/env python
"""P6 gate verification.

Proves the literal P6 acceptance gate from the PRD: genealogy forward-trace
(lot -> vendor/PO/GRN upstream, QC/fabrication/serial/installation
downstream) and recall-trace (vendor + date range -> every plant that ever
received that vendor's material) both return the full expected chain from
one seeded synthetic path through the ERP schema. Also exercises the rest
of the P6 surface built alongside it: issue_lines qty_on_hand debit
(including the "never goes negative" rejection), fabrication_jobs /
unit_serials status-transition validation, installations (the ERP <->
machine-data bridge), logistics trips start/ping/stop with per-trip token
auth, the Tally XML voucher export, and Grafana alert-rule/dashboard
provisioning.

What this script does:
  1. Runs seed/seed.py (idempotent) so company/plants/materials/admin user exist.
  2. Seeds ITS OWN synthetic chain directly via the admin DB connection (not
     seed/seed.py): 1 vendor, 1 PO + PO item, 1 GRN + GRN line, 1 inventory
     lot, 1 QC record, 1 test plant, 1 project, 1 unit serial, 1
     fabrication job, 1 approved vendor invoice.
  3. Starts an ephemeral FastAPI app (tests/_p6_test_app.py) mounting only
     the new P6 routers + the existing (unmodified) auth router, via
     uvicorn subprocess, and waits for /health.
  4. Builds a global_admin JWT directly via api.security (bypasses RLS
     entirely, same as admin@airthra.dev from seed/seed.py) - avoids a
     dependency on that exact seeded row while still exercising the real
     auth-decoding path in api/deps.py.
  5. Exercises every endpoint, asserting PASS/FAIL per check.
  6. Separately verifies Grafana alert-rule + dashboard provisioning via
     Grafana's HTTP API (admin creds from .env).
  7. Cleans up all rows it created (including issue_lines credited during
     the run) and stops the API process.

LIMITATIONS (explicitly NOT claimed as verified by this gate):
  - Tally XML export: only checked for well-formedness (xml.etree parses
    it) and presence of the required top-level Tally envelope elements
    (ENVELOPE/HEADER/BODY/IMPORTDATA/REQUESTDATA/TALLYMESSAGE/VOUCHER).
    This is NOT a real Tally-import validation, which isn't testable in
    this sandboxed environment (no Tally instance available).
  - Grafana webhook round-trip: the KOH-days-remaining alert rule points
    at POST /admin/logistics/task, which is owned by the concurrent P7
    phase and may not exist yet. This gate verifies the alert rule /
    contact point / notification policy are correctly provisioned and
    visible via Grafana's HTTP API - it does NOT fire the alert and does
    NOT verify the webhook actually reaches /admin/logistics/task.

Prints PASS/FAIL per check, exits non-zero on any failure.

Run from repo root: `python tests/p6_genealogy_gate.py`
(Postgres on 5433 and Grafana on GF_PORT must already be up via
`docker compose up -d`.)
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
except ImportError:
    pass

import httpx  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from api import security  # noqa: E402

DATABASE_URL = os.environ.get("DATABASE_URL")
API_HOST = "127.0.0.1"
API_PORT = 8010
BASE_URL = f"http://{API_HOST}:{API_PORT}"

GF_PORT = os.environ.get("GF_PORT", "3001")
GF_USER = os.environ.get("GF_SECURITY_ADMIN_USER", "admin")
GF_PASSWORD = os.environ.get("GF_SECURITY_ADMIN_PASSWORD", "change_me_dev_only")
GF_BASE_URL = f"http://localhost:{GF_PORT}"

# Fixed ids for this gate's synthetic chain, so re-running after a crash
# cleans up its own leftovers instead of accumulating garbage.
VENDOR_ID = "00000000-0000-4000-8000-000000000601"
PROJECT_ID = "00000000-0000-4000-8000-000000000602"
PO_ID = "00000000-0000-4000-8000-000000000603"
PO_ITEM_ID = "00000000-0000-4000-8000-000000000604"
GRN_ID = "00000000-0000-4000-8000-000000000605"
GRN_LINE_ID = "00000000-0000-4000-8000-000000000606"
LOT_ID = "00000000-0000-4000-8000-000000000607"
QC_ID = "00000000-0000-4000-8000-000000000608"
JOB_ID = "00000000-0000-4000-8000-000000000609"
SERIAL = "P6-GATE-SERIAL-001"
INSTALLATION_ID = "00000000-0000-4000-8000-00000000060a"
VENDOR_INVOICE_ID = "00000000-0000-4000-8000-00000000060b"
SMALL_LOT_ID = "00000000-0000-4000-8000-00000000060c"  # for insufficient-qty check
TEST_PLANT_ID = "p6_gate_test_plant"
PO_NO = "AIR/PO/99-99/9999"
GRN_NO = "P6-GATE-GRN-0001"

results: list[tuple[str, bool]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok))
    line = f"[{'PASS' if ok else 'FAIL'}] {name}"
    if detail:
        line += f" - {detail}"
    print(line)


def wait_for_health(timeout_s: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            r = httpx.get(f"{BASE_URL}/health", timeout=2.0)
            if r.status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    return False


def cleanup_db(engine) -> None:
    with engine.begin() as conn:
        # The installation row created via POST /erp/installations during the
        # run gets a server-generated id (not INSTALLATION_ID, which is
        # unused/reserved) - delete by serial instead so cleanup is correct
        # regardless of how many times this gate has run against a fresh id.
        conn.execute(text("DELETE FROM installations WHERE serial = :s"), {"s": SERIAL})
        conn.execute(text("DELETE FROM issue_lines WHERE fabrication_job_id = :id"), {"id": JOB_ID})
        conn.execute(text("DELETE FROM issue_lines WHERE lot_id IN (:l1, :l2)"), {"l1": LOT_ID, "l2": SMALL_LOT_ID})
        conn.execute(text("DELETE FROM qc_records WHERE id = :id"), {"id": QC_ID})
        conn.execute(text("DELETE FROM fabrication_jobs WHERE id = :id"), {"id": JOB_ID})
        conn.execute(text("DELETE FROM unit_serials WHERE serial = :s"), {"s": SERIAL})
        conn.execute(text("DELETE FROM inventory_lots WHERE lot_id IN (:l1, :l2)"), {"l1": LOT_ID, "l2": SMALL_LOT_ID})
        conn.execute(text("DELETE FROM grn_lines WHERE id = :id"), {"id": GRN_LINE_ID})
        conn.execute(text("DELETE FROM grn WHERE id = :id"), {"id": GRN_ID})
        conn.execute(text("DELETE FROM vendor_invoices WHERE id = :id"), {"id": VENDOR_INVOICE_ID})
        conn.execute(text("DELETE FROM po_items WHERE id = :id"), {"id": PO_ITEM_ID})
        conn.execute(text("DELETE FROM pos WHERE id = :id"), {"id": PO_ID})
        conn.execute(text("DELETE FROM projects WHERE id = :id"), {"id": PROJECT_ID})
        conn.execute(text("DELETE FROM vendors WHERE id = :id"), {"id": VENDOR_ID})
        conn.execute(text("DELETE FROM trip_pings WHERE trip_id IN (SELECT id FROM trips WHERE vehicle_no = 'P6-GATE-VEH-01')"))
        conn.execute(text("DELETE FROM trips WHERE vehicle_no = 'P6-GATE-VEH-01'"))
        conn.execute(text("DELETE FROM plants WHERE plant_id = :p"), {"p": TEST_PLANT_ID})


def seed_db(engine) -> str:
    """Seed the synthetic genealogy chain. Returns a materials.id to use."""
    with engine.begin() as conn:
        material_id = conn.execute(text("SELECT id FROM materials LIMIT 1")).scalar()
        if material_id is None:
            raise RuntimeError("no materials rows found - run seed/seed.py first")

        conn.execute(
            text("INSERT INTO plants (plant_id, name) VALUES (:p, 'P6 Gate Test Plant')"),
            {"p": TEST_PLANT_ID},
        )
        conn.execute(
            text(
                "INSERT INTO vendors (id, name, gstin, state_code) "
                "VALUES (:id, 'P6 Gate Test Vendor Pvt Ltd', '30ABCDE9999F1Z1', '30')"
            ),
            {"id": VENDOR_ID},
        )
        conn.execute(
            text(
                "INSERT INTO projects (id, code, name, status) "
                "VALUES (:id, 'P6-GATE-PROJ', 'P6 Gate Test Project', 'active')"
            ),
            {"id": PROJECT_ID},
        )
        conn.execute(
            text(
                "INSERT INTO pos (id, po_no, vendor_id, po_date, status) "
                "VALUES (:id, :po_no, :vendor_id, CURRENT_DATE, 'received')"
            ),
            {"id": PO_ID, "po_no": PO_NO, "vendor_id": VENDOR_ID},
        )
        conn.execute(
            text(
                "INSERT INTO po_items (id, po_id, description, hsn, qty, unit, rate, gst_rate, received_qty) "
                "VALUES (:id, :po_id, 'MS Plate 10mm', '7208', 100, 'kg', 62.5, 18, 100)"
            ),
            {"id": PO_ITEM_ID, "po_id": PO_ID},
        )
        conn.execute(
            text(
                "INSERT INTO grn (id, po_id, grn_no, date, vehicle_no, eway_bill_no) "
                "VALUES (:id, :po_id, :grn_no, CURRENT_DATE, 'GA-07-AB-1234', 'EWB123456789012')"
            ),
            {"id": GRN_ID, "po_id": PO_ID, "grn_no": GRN_NO},
        )
        conn.execute(
            text(
                "INSERT INTO grn_lines (id, grn_id, po_item_id, qty_received, qty_accepted, qty_rejected) "
                "VALUES (:id, :grn_id, :po_item_id, 100, 100, 0)"
            ),
            {"id": GRN_LINE_ID, "grn_id": GRN_ID, "po_item_id": PO_ITEM_ID},
        )
        conn.execute(
            text(
                "INSERT INTO inventory_lots (lot_id, grn_line_id, material_id, qty_on_hand, unit, heat_no) "
                "VALUES (:id, :grn_line_id, :material_id, 100, 'kg', 'HEAT-P6-001')"
            ),
            {"id": LOT_ID, "grn_line_id": GRN_LINE_ID, "material_id": material_id},
        )
        # A second, near-empty lot to exercise the "insufficient qty" reject path.
        conn.execute(
            text(
                "INSERT INTO inventory_lots (lot_id, material_id, qty_on_hand, unit, heat_no) "
                "VALUES (:id, :material_id, 1, 'kg', 'HEAT-P6-SMALL')"
            ),
            {"id": SMALL_LOT_ID, "material_id": material_id},
        )
        conn.execute(
            text(
                "INSERT INTO qc_records (id, lot_id, type, result, inspector) "
                "VALUES (:id, :lot_id, 'incoming', 'pass', 'P6 Gate Bot')"
            ),
            {"id": QC_ID, "lot_id": LOT_ID},
        )
        conn.execute(
            text("INSERT INTO unit_serials (serial, model, project_id, status) VALUES (:s, 'AIR-FGD-100', :p, 'fabrication')"),
            {"s": SERIAL, "p": PROJECT_ID},
        )
        conn.execute(
            text(
                "INSERT INTO fabrication_jobs (id, project_id, unit_serial, status) "
                "VALUES (:id, :p, :s, 'planned')"
            ),
            {"id": JOB_ID, "p": PROJECT_ID, "s": SERIAL},
        )
        conn.execute(
            text(
                "INSERT INTO vendor_invoices (id, vendor_id, po_id, inv_no, date, taxable, gst, total, status) "
                "VALUES (:id, :vendor_id, :po_id, 'P6-GATE-INV-001', CURRENT_DATE, 6250, 1125, 7375, 'approved')"
            ),
            {"id": VENDOR_INVOICE_ID, "vendor_id": VENDOR_ID, "po_id": PO_ID},
        )
    return material_id


def make_admin_token() -> str:
    return security.create_access_token(user_id="", role="global_admin", plant_ids=[])


def genealogy_checks(headers: dict) -> None:
    r = httpx.get(f"{BASE_URL}/erp/genealogy/lot/{LOT_ID}", headers=headers, timeout=10.0)
    check("GET genealogy/lot: 200", r.status_code == 200, f"got {r.status_code}: {r.text[:300]}")
    if r.status_code != 200:
        return
    body = r.json()

    check("forward-trace: vendor name present", body["lot"].get("vendor_name") == "P6 Gate Test Vendor Pvt Ltd",
          str(body["lot"].get("vendor_name")))
    check("forward-trace: po_no present", body["lot"].get("po_no") == PO_NO, str(body["lot"].get("po_no")))
    check("forward-trace: grn_no present", body["lot"].get("grn_no") == GRN_NO, str(body["lot"].get("grn_no")))
    check("forward-trace: qc_records include seeded record",
          any(q["id"] == QC_ID for q in body["qc_records"]), str(body["qc_records"]))

    # Issue material from LOT_ID to JOB_ID via the real endpoint before
    # re-checking forward-trace picks up the fabrication_jobs/unit_serials/
    # installations legs (those only appear once material has actually been
    # issued and installed).
    r_issue = httpx.post(
        f"{BASE_URL}/erp/issue-lines", headers=headers, timeout=10.0,
        json={"lot_id": LOT_ID, "qty": 10, "fabrication_job_id": JOB_ID},
    )
    check("POST issue-lines: success debits qty_on_hand", r_issue.status_code == 201,
          f"got {r_issue.status_code}: {r_issue.text[:300]}")
    if r_issue.status_code == 201:
        check("POST issue-lines: qty_on_hand decremented to 90",
              r_issue.json()["lot_qty_on_hand"] == 90, str(r_issue.json()))

    # Insufficient-qty rejection: SMALL_LOT_ID only has 1 kg on hand.
    r_over = httpx.post(
        f"{BASE_URL}/erp/issue-lines", headers=headers, timeout=10.0,
        json={"lot_id": SMALL_LOT_ID, "qty": 999, "fabrication_job_id": JOB_ID},
    )
    check("POST issue-lines: insufficient qty -> 400 (never negative)", r_over.status_code == 400,
          f"got {r_over.status_code}: {r_over.text[:300]}")
    lot_after = httpx.get(f"{BASE_URL}/erp/inventory-lots/{SMALL_LOT_ID}", headers=headers, timeout=10.0).json()
    check("small lot qty_on_hand unchanged (still 1, never negative)", lot_after["qty_on_hand"] == 1,
          str(lot_after))

    # Advance fabrication_jobs status: planned -> in_progress -> completed.
    r_bad_transition = httpx.patch(
        f"{BASE_URL}/erp/fabrication-jobs/{JOB_ID}/status", headers=headers, timeout=10.0,
        json={"status": "completed"},
    )
    check("PATCH fabrication-jobs status: planned->completed rejected", r_bad_transition.status_code == 400,
          f"got {r_bad_transition.status_code}")
    r_ok_transition = httpx.patch(
        f"{BASE_URL}/erp/fabrication-jobs/{JOB_ID}/status", headers=headers, timeout=10.0,
        json={"status": "in_progress"},
    )
    check("PATCH fabrication-jobs status: planned->in_progress ok", r_ok_transition.status_code == 200,
          f"got {r_ok_transition.status_code}: {r_ok_transition.text[:200]}")
    r_complete = httpx.patch(
        f"{BASE_URL}/erp/fabrication-jobs/{JOB_ID}/status", headers=headers, timeout=10.0,
        json={"status": "completed"},
    )
    check("PATCH fabrication-jobs status: in_progress->completed ok", r_complete.status_code == 200,
          f"got {r_complete.status_code}")

    # Advance unit_serials status: fabrication -> qc -> dispatched -> installed.
    r_skip = httpx.patch(
        f"{BASE_URL}/erp/unit-serials/{SERIAL}/status", headers=headers, timeout=10.0,
        json={"status": "dispatched"},
    )
    check("PATCH unit-serials status: fabrication->dispatched (skip) rejected", r_skip.status_code == 400,
          f"got {r_skip.status_code}")
    for step in ("qc", "dispatched", "installed"):
        r_step = httpx.patch(
            f"{BASE_URL}/erp/unit-serials/{SERIAL}/status", headers=headers, timeout=10.0,
            json={"status": step},
        )
        check(f"PATCH unit-serials status: ...->{step} ok", r_step.status_code == 200,
              f"got {r_step.status_code}: {r_step.text[:200]}")

    # Record the installation (ERP <-> machine-data bridge).
    r_install = httpx.post(
        f"{BASE_URL}/erp/installations", headers=headers, timeout=10.0,
        json={"serial": SERIAL, "plant_id": TEST_PLANT_ID},
    )
    check("POST installations: created", r_install.status_code == 201,
          f"got {r_install.status_code}: {r_install.text[:300]}")

    # Re-fetch forward-trace: now expect fabrication_jobs/unit_serials/installations populated.
    r2 = httpx.get(f"{BASE_URL}/erp/genealogy/lot/{LOT_ID}", headers=headers, timeout=10.0)
    check("GET genealogy/lot (after issue+install): 200", r2.status_code == 200, f"got {r2.status_code}")
    body2 = r2.json()
    check("forward-trace: fabrication_jobs includes JOB_ID",
          any(j["id"] == JOB_ID for j in body2["fabrication_jobs"]), str(body2["fabrication_jobs"]))
    check("forward-trace: unit_serials includes SERIAL",
          any(s["serial"] == SERIAL for s in body2["unit_serials"]), str(body2["unit_serials"]))
    check("forward-trace: installations includes TEST_PLANT_ID",
          any(i["plant_id"] == TEST_PLANT_ID for i in body2["installations"]), str(body2["installations"]))

    # Recall-trace: vendor + date range spanning today should surface TEST_PLANT_ID.
    today = date.today()
    r3 = httpx.get(
        f"{BASE_URL}/erp/genealogy/vendor-recall", headers=headers, timeout=10.0,
        params={"vendor_id": VENDOR_ID, "start": (today - timedelta(days=1)).isoformat(),
                "end": (today + timedelta(days=1)).isoformat()},
    )
    check("GET genealogy/vendor-recall: 200", r3.status_code == 200, f"got {r3.status_code}: {r3.text[:300]}")
    if r3.status_code == 200:
        recall_body = r3.json()
        affected = [p["plant_id"] for p in recall_body["affected_plants"]]
        check("recall-trace: TEST_PLANT_ID in affected_plants", TEST_PLANT_ID in affected, str(affected))

    # Recall-trace: date range NOT covering the PO should NOT surface the plant.
    r4 = httpx.get(
        f"{BASE_URL}/erp/genealogy/vendor-recall", headers=headers, timeout=10.0,
        params={"vendor_id": VENDOR_ID, "start": "2000-01-01", "end": "2000-01-02"},
    )
    check("GET genealogy/vendor-recall (out-of-range dates): 200", r4.status_code == 200)
    if r4.status_code == 200:
        affected2 = [p["plant_id"] for p in r4.json()["affected_plants"]]
        check("recall-trace: TEST_PLANT_ID absent for out-of-range dates", TEST_PLANT_ID not in affected2,
              str(affected2))


def logistics_checks(headers: dict) -> None:
    r_start = httpx.post(
        f"{BASE_URL}/logistics/trips", headers=headers, timeout=10.0,
        json={"vehicle_no": "P6-GATE-VEH-01", "driver": "Test Driver", "purpose": "koh_delivery",
              "dest_plant_id": TEST_PLANT_ID},
    )
    check("POST logistics/trips: created", r_start.status_code == 201,
          f"got {r_start.status_code}: {r_start.text[:300]}")
    if r_start.status_code != 201:
        return
    trip = r_start.json()
    trip_id = trip["id"]
    token = trip["token"]
    check("POST logistics/trips: token issued", bool(token), str(token))

    r_ping_bad = httpx.post(
        f"{BASE_URL}/logistics/trips/{trip_id}/ping", timeout=10.0,
        headers={"X-Trip-Token": "wrong-token"},
        json={"lat": 15.38, "lon": 73.96, "speed": 40},
    )
    check("POST trip ping: wrong token -> 401", r_ping_bad.status_code == 401, f"got {r_ping_bad.status_code}")

    r_ping = httpx.post(
        f"{BASE_URL}/logistics/trips/{trip_id}/ping", timeout=10.0,
        headers={"X-Trip-Token": token},
        json={"lat": 15.38, "lon": 73.96, "speed": 42.5},
    )
    check("POST trip ping: correct token -> 201", r_ping.status_code == 201, f"got {r_ping.status_code}: {r_ping.text[:200]}")

    r_pings = httpx.get(f"{BASE_URL}/logistics/trips/{trip_id}/pings", headers=headers, timeout=10.0)
    check("GET trip pings: includes the ping just sent", r_pings.status_code == 200
          and any(abs(p["lat"] - 15.38) < 1e-6 for p in r_pings.json()["pings"]),
          f"got {r_pings.status_code}: {r_pings.text[:200]}")

    r_stop = httpx.post(f"{BASE_URL}/logistics/trips/{trip_id}/stop", timeout=10.0, headers={"X-Trip-Token": token})
    check("POST trip stop: token auth -> 200, status completed",
          r_stop.status_code == 200 and r_stop.json().get("status") == "completed",
          f"got {r_stop.status_code}: {r_stop.text[:200]}")


TALLY_REQUIRED_ELEMENTS = ("HEADER", "TALLYREQUEST", "BODY", "IMPORTDATA", "REQUESTDATA", "TALLYMESSAGE", "VOUCHER")


def tally_checks(headers: dict) -> None:
    r = httpx.get(f"{BASE_URL}/erp/tally-export/vendor-invoice/{VENDOR_INVOICE_ID}", headers=headers, timeout=10.0)
    check("GET tally-export (approved invoice): 200", r.status_code == 200, f"got {r.status_code}: {r.text[:300]}")
    if r.status_code != 200:
        return
    try:
        root = ET.fromstring(r.content)
        well_formed = True
    except ET.ParseError as exc:
        well_formed = False
        root = None
        check("tally XML: well-formed", False, str(exc))
    if well_formed:
        check("tally XML: well-formed", True)
        check("tally XML: root is ENVELOPE", root.tag == "ENVELOPE", root.tag)
        found = {el.tag for el in root.iter()}
        missing = [e for e in TALLY_REQUIRED_ELEMENTS if e not in found]
        check("tally XML: required Tally envelope elements present", not missing, f"missing={missing}")
        # NOTE (documented limitation): the above proves structural
        # well-formedness only, NOT that a real Tally instance would accept
        # this as an importable voucher - not testable in this environment.

    # Non-approved invoice should be rejected.
    tmp_id = str(uuid.uuid4())
    engine = create_engine(DATABASE_URL, future=True)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO vendor_invoices (id, vendor_id, po_id, inv_no, date, taxable, gst, total, status) "
                "VALUES (:id, :vendor_id, :po_id, 'P6-GATE-INV-UNAPPROVED', CURRENT_DATE, 100, 18, 118, 'received')"
            ),
            {"id": tmp_id, "vendor_id": VENDOR_ID, "po_id": PO_ID},
        )
    try:
        r_bad = httpx.get(f"{BASE_URL}/erp/tally-export/vendor-invoice/{tmp_id}", headers=headers, timeout=10.0)
        check("GET tally-export (unapproved invoice): 400", r_bad.status_code == 400, f"got {r_bad.status_code}")
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM vendor_invoices WHERE id = :id"), {"id": tmp_id})


def grafana_checks() -> None:
    auth = (GF_USER, GF_PASSWORD)
    try:
        r = httpx.get(f"{GF_BASE_URL}/api/v1/provisioning/alert-rules", auth=auth, timeout=10.0)
        check("Grafana: alert-rules API reachable", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
        if r.status_code == 200:
            titles = [rule.get("title") for rule in r.json()]
            check("Grafana: KOH days remaining rule provisioned", "KOH days remaining critical" in titles,
                  str(titles))

        r_cp = httpx.get(f"{GF_BASE_URL}/api/v1/provisioning/contact-points", auth=auth, timeout=10.0)
        check("Grafana: contact-points API reachable", r_cp.status_code == 200, f"got {r_cp.status_code}")
        if r_cp.status_code == 200:
            names = [cp.get("name") for cp in r_cp.json()]
            check("Grafana: logistics webhook contact point provisioned",
                  "airthra-logistics-webhook" in names, str(names))

        r_dash = httpx.get(f"{GF_BASE_URL}/api/search", auth=auth, params={"query": ""}, timeout=10.0)
        check("Grafana: search API reachable", r_dash.status_code == 200, f"got {r_dash.status_code}")
        if r_dash.status_code == 200:
            dash_titles = {d.get("title") for d in r_dash.json() if d.get("type") == "dash-db"}
            expected = {
                "Machine Overview (per plant)", "Fleet Overview", "PO Spend by Vendor",
                "Inventory Value", "Fabrication Jobs by Status", "Live Trip Geomap",
            }
            missing = expected - dash_titles
            check("Grafana: all 6 P6 dashboards provisioned", not missing, f"missing={missing}")
    except httpx.HTTPError as exc:
        check("Grafana: reachable at all", False, f"{type(exc).__name__}: {exc} "
              f"(is `docker compose up -d grafana` running? GF_PORT={GF_PORT})")

    print()
    print("NOTE (documented limitation): the checks above verify the alert")
    print("rule/contact point/dashboards are correctly PROVISIONED and visible")
    print("via Grafana's HTTP API. They do NOT fire the alert and do NOT verify")
    print("the webhook actually reaches POST /admin/logistics/task, which is")
    print("owned by the concurrent P7 phase and may not exist yet.")


def main() -> int:
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL not set (check .env)", file=sys.stderr)
        return 2

    engine = create_engine(DATABASE_URL, future=True)

    print("=" * 70)
    print("P6 GATE: setup (seed + synthetic genealogy chain)")
    print("=" * 70)

    seed_proc = subprocess.run(
        [sys.executable, os.path.join(ROOT, "seed", "seed.py")],
        cwd=ROOT, capture_output=True, text=True,
    )
    if seed_proc.returncode != 0:
        print(seed_proc.stdout)
        print(seed_proc.stderr, file=sys.stderr)
        print("ERROR: seed/seed.py failed", file=sys.stderr)
        return 2
    print(seed_proc.stdout.strip())

    cleanup_db(engine)  # idempotent: remove any leftovers from a prior crashed run
    material_id = seed_db(engine)
    print(f"seeded synthetic chain (material_id={material_id}, lot_id={LOT_ID}, vendor_id={VENDOR_ID})")

    print()
    print("=" * 70)
    print("P6 GATE: starting ephemeral test API (tests/_p6_test_app.py)")
    print("=" * 70)

    env = os.environ.copy()
    log_path = os.path.join(ROOT, "tests", "_p6_gate_api.log")
    log_file = open(log_path, "w", encoding="utf-8")
    api_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "tests._p6_test_app:app",
         "--host", API_HOST, "--port", str(API_PORT)],
        cwd=ROOT, env=env,
        stdout=log_file, stderr=subprocess.STDOUT, text=True,
    )

    exit_code = 1
    try:
        if not wait_for_health():
            print(f"ERROR: API did not become healthy in time - see {log_path}", file=sys.stderr)
            log_file.flush()
            return 2
        print(f"API healthy at {BASE_URL}")

        token = make_admin_token()
        headers = {"Authorization": f"Bearer {token}"}

        print()
        print("=" * 70)
        print("P6 GATE: genealogy forward-trace / recall-trace + production endpoints")
        print("=" * 70)
        genealogy_checks(headers)

        print()
        print("=" * 70)
        print("P6 GATE: logistics trips (start/ping/stop, per-trip token auth)")
        print("=" * 70)
        logistics_checks(headers)

        print()
        print("=" * 70)
        print("P6 GATE: Tally XML export")
        print("=" * 70)
        tally_checks(headers)

        print()
        print("=" * 70)
        print("P6 GATE: Grafana dashboard + alert-rule provisioning")
        print("=" * 70)
        grafana_checks()

        print()
        print("=" * 70)
        failed = [n for n, ok in results if not ok]
        if failed:
            print(f"P6 GATE: FAIL ({len(failed)}/{len(results)} checks failed)")
            for n in failed:
                print(f"  - {n}")
            exit_code = 1
        else:
            print(f"P6 GATE: PASS ({len(results)}/{len(results)} checks passed)")
            exit_code = 0
    finally:
        print()
        print("=" * 70)
        print("P6 GATE: teardown")
        print("=" * 70)
        api_proc.terminate()
        try:
            api_proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            api_proc.kill()
        log_file.close()
        cleanup_db(engine)
        print("removed synthetic chain, stopped API")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
