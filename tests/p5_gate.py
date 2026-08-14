#!/usr/bin/env python
"""P5 gate verification.

Proves the literal P5 acceptance gate from the PRD (GST logic is called out
explicitly as "the P5 acceptance gate"), plus the other hard-line P5
behaviours:

  1. GST: a PO for an intra-state vendor (same state_code as `company`)
     shows CGST+SGST summing correctly to the line's GST; a PO for an
     inter-state vendor shows IGST only (CGST=SGST=0). Both show the
     correct grand total and Indian-numbering amount-in-words for a known
     line total.
  2. BOM release immutability: releasing a BOM then attempting to PATCH it
     is rejected (409), not silently accepted.
  3. 3-way match: an invoice whose total doesn't reconcile with the PO
     blocks POST /erp/vendor-invoices/{id}/approve (400, no status
     change); a matching invoice is approved.

What this script does:
  1. Runs seed/seed.py (idempotent) so the baseline `company` row, the
     `global_admin` dev user, and `materials` exist (same convention as
     tests/p2_gate.py - this is baseline fixture data owned by P0/P2, not
     the P5-specific vendors this gate needs, which are seeded directly
     below via this script, NOT via seed/seed.py).
  2. Seeds two temporary vendors directly via SQL: one intra-state (same
     state_code as `company`), one inter-state - plus a temporary project.
  3. Starts api.erp_app (api/erp_app.py - a standalone FastAPI app that
     mounts auth + every new P5 router, kept separate from api/main.py
     which is owned by other concurrently-developed phases) as a
     background uvicorn process and waits for /health.
  4. Logs in as the global_admin dev user.
  5. Runs the three checks above against the live API + live Postgres.
  6. Cleans up every row it created (vendors, project, boms/bom_items,
     pos/po_items, grn/grn_lines, vendor_invoices) and stops the API
     process.

Prints PASS/FAIL per check, exits non-zero on any failure.

Run from repo root: `python tests/p5_gate.py`
(the API is started automatically; nothing else needs to be running
except Postgres on 5433, and MinIO on 9000 for the PDF-generation smoke
check).
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from decimal import Decimal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
except ImportError:
    pass

import httpx  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

DATABASE_URL = os.environ.get("DATABASE_URL")
API_HOST = os.environ.get("API_HOST", "127.0.0.1")
API_PORT = int(os.environ.get("P5_GATE_API_PORT", "8011"))
BASE_URL = f"http://{API_HOST}:{API_PORT}"

ADMIN_EMAIL = "admin@airthra.dev"
ADMIN_PASSWORD = "Airthra_Dev_2026!"

results: list[tuple[str, bool]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok))
    status = "PASS" if ok else "FAIL"
    line = f"[{status}] {name}"
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


# ---------------------------------------------------------------------------
# Seed / teardown (own script - NOT seed/seed.py, per the P5 task spec)
# ---------------------------------------------------------------------------

def seed_db() -> dict:
    engine = create_engine(DATABASE_URL, future=True)
    ids = {
        "project_id": str(uuid.uuid4()),
        "vendor_intra_id": str(uuid.uuid4()),
        "vendor_inter_id": str(uuid.uuid4()),
    }
    with engine.begin() as conn:
        company = conn.execute(text("SELECT state_code FROM company LIMIT 1")).mappings().first()
        if company is None:
            raise RuntimeError("no `company` row - run seed/seed.py first (P0 baseline fixture)")
        company_state = company["state_code"]
        ids["company_state_code"] = company_state
        other_state = "27" if company_state != "27" else "29"
        ids["other_state_code"] = other_state

        conn.execute(
            text(
                """
                INSERT INTO vendors (id, name, gstin, address, state_code)
                VALUES (:id, 'P5 Gate Intra-State Vendor', :gstin, 'Same state as company', :state_code)
                """
            ),
            {"id": ids["vendor_intra_id"], "gstin": f"{company_state}P5GATE0000A1Z1", "state_code": company_state},
        )
        conn.execute(
            text(
                """
                INSERT INTO vendors (id, name, gstin, address, state_code)
                VALUES (:id, 'P5 Gate Inter-State Vendor', :gstin, 'Different state from company', :state_code)
                """
            ),
            {"id": ids["vendor_inter_id"], "gstin": f"{other_state}P5GATE0000B1Z1", "state_code": other_state},
        )
        conn.execute(
            text("INSERT INTO projects (id, code, name) VALUES (:id, :code, 'P5 Gate Test Project')"),
            {"id": ids["project_id"], "code": f"P5GATE-{ids['project_id'][:8]}"},
        )
    return ids


def teardown_db(state: dict) -> None:
    engine = create_engine(DATABASE_URL, future=True)
    with engine.begin() as conn:
        for inv_id in state.get("invoice_ids", []):
            conn.execute(text("DELETE FROM vendor_invoices WHERE id = :id"), {"id": inv_id})
        for grn_id in state.get("grn_ids", []):
            conn.execute(text("DELETE FROM grn_lines WHERE grn_id = :id"), {"id": grn_id})
            conn.execute(text("DELETE FROM grn WHERE id = :id"), {"id": grn_id})
        for po_id in state.get("po_ids", []):
            conn.execute(text("DELETE FROM po_items WHERE po_id = :id"), {"id": po_id})
            conn.execute(text("DELETE FROM pos WHERE id = :id"), {"id": po_id})
        for bom_id in state.get("bom_ids", []):
            conn.execute(text("DELETE FROM bom_items WHERE bom_id = :id"), {"id": bom_id})
        for bom_id in state.get("bom_ids", []):
            conn.execute(text("UPDATE boms SET supersedes_bom_id = NULL WHERE id = :id"), {"id": bom_id})
        for bom_id in state.get("bom_ids", []):
            conn.execute(text("DELETE FROM boms WHERE id = :id"), {"id": bom_id})
        if state.get("project_id"):
            conn.execute(text("DELETE FROM tasks WHERE project_id = :id"), {"id": state["project_id"]})
            conn.execute(text("DELETE FROM projects WHERE id = :id"), {"id": state["project_id"]})
        for vid in (state.get("vendor_intra_id"), state.get("vendor_inter_id")):
            if vid:
                conn.execute(text("DELETE FROM vendors WHERE id = :id"), {"id": vid})


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def login(client: httpx.Client) -> str:
    r = client.post(f"{BASE_URL}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=5.0)
    r.raise_for_status()
    body = r.json()
    assert body["role"] == "global_admin", f"expected global_admin role, got {body['role']}"
    return body["access_token"]


def gst_checks(client: httpx.Client, headers: dict, ids: dict) -> None:
    # Known line: qty=10, rate=100 -> taxable=1000.00, gst_rate=18% -> GST=180.00, grand_total=1180.00
    for label, vendor_key, expect_regime in (
        ("intra-state", "vendor_intra_id", "intra_state (CGST+SGST)"),
        ("inter-state", "vendor_inter_id", "inter_state (IGST)"),
    ):
        r = client.post(
            f"{BASE_URL}/erp/pos", headers=headers, timeout=10.0,
            json={
                "vendor_id": ids[vendor_key],
                "items": [{"description": "P5 gate test line", "hsn": "9999", "qty": 10, "unit": "nos", "rate": 100, "gst_rate": 18}],
            },
        )
        check(f"create PO ({label} vendor) -> 201", r.status_code == 201, f"got {r.status_code}: {r.text[:300]}")
        po = r.json()
        ids.setdefault("po_ids", []).append(po["id"])
        check(f"po_no format ({label})", bool(__import__("re").match(r"^AIR/PO/\d{2}-\d{2}/\d{4}$", po["po_no"])), po["po_no"])

        r2 = client.get(f"{BASE_URL}/erp/pos/{po['id']}", headers=headers, timeout=10.0)
        check(f"get PO detail ({label}) -> 200", r2.status_code == 200, f"got {r2.status_code}")
        detail = r2.json()
        totals = detail["totals"]

        check(f"tax regime correct ({label})", totals["tax_regime"] == expect_regime, totals["tax_regime"])
        if label == "intra-state":
            check("CGST == 90.00 (intra-state)", Decimal(str(totals["cgst"])) == Decimal("90.00"), totals["cgst"])
            check("SGST == 90.00 (intra-state)", Decimal(str(totals["sgst"])) == Decimal("90.00"), totals["sgst"])
            check("IGST == 0 (intra-state)", Decimal(str(totals["igst"])) == Decimal("0.00"), totals["igst"])
            check(
                "CGST+SGST sums to total GST (intra-state)",
                Decimal(str(totals["cgst"])) + Decimal(str(totals["sgst"])) == Decimal("180.00"),
                f"cgst+sgst={Decimal(str(totals['cgst'])) + Decimal(str(totals['sgst']))}",
            )
        else:
            check("IGST == 180.00 (inter-state)", Decimal(str(totals["igst"])) == Decimal("180.00"), totals["igst"])
            check("CGST == 0 (inter-state)", Decimal(str(totals["cgst"])) == Decimal("0.00"), totals["cgst"])
            check("SGST == 0 (inter-state)", Decimal(str(totals["sgst"])) == Decimal("0.00"), totals["sgst"])

        check(f"grand_total == 1180.00 ({label})", Decimal(str(totals["grand_total"])) == Decimal("1180.00"), totals["grand_total"])
        check(
            f"amount_in_words correct ({label})",
            detail["amount_in_words"] == "One Thousand One Hundred Eighty Rupees Only",
            detail["amount_in_words"],
        )

        if label == "intra-state":
            r3 = client.get(f"{BASE_URL}/erp/pos/{po['id']}/pdf", headers=headers, timeout=15.0)
            check("PDF generation + MinIO upload -> 200", r3.status_code == 200, f"got {r3.status_code}: {r3.text[:300]}")
            if r3.status_code == 200:
                pdf_url = r3.json()["url"]
                r4 = httpx.get(pdf_url, timeout=10.0)
                check("uploaded PO PDF is downloadable and looks like a PDF", r4.status_code == 200 and r4.content[:5] == b"%PDF-", f"status={r4.status_code}")


def bom_immutability_check(client: httpx.Client, headers: dict, ids: dict) -> None:
    mat = client.get(f"{BASE_URL}/erp/materials", headers=headers, timeout=10.0).json()
    if not mat:
        check("BOM immutability: materials exist to test with", False, "no materials seeded")
        return
    material_id = mat[0]["id"]

    r = client.post(
        f"{BASE_URL}/erp/boms", headers=headers, timeout=10.0,
        json={"project_id": ids["project_id"], "name": "P5 Gate BOM", "revision": "A"},
    )
    check("create BOM -> 201", r.status_code == 201, f"got {r.status_code}: {r.text[:300]}")
    bom = r.json()
    ids.setdefault("bom_ids", []).append(bom["id"])

    r2 = client.post(
        f"{BASE_URL}/erp/boms/{bom['id']}/items", headers=headers, timeout=10.0,
        json={
            "description": "P5 gate plate", "material_id": material_id, "shape": "plate",
            "dims": {"length_mm": 200, "width_mm": 100, "thickness_mm": 5}, "qty": 1, "scrap_pct": 0,
        },
    )
    check("add bom item -> 201", r2.status_code == 201, f"got {r2.status_code}: {r2.text[:300]}")

    r3 = client.post(f"{BASE_URL}/erp/boms/{bom['id']}/release", headers=headers, timeout=10.0)
    check("release BOM -> 200, status=released", r3.status_code == 200 and r3.json().get("status") == "released", f"got {r3.status_code}: {r3.text[:300]}")

    r4 = client.patch(f"{BASE_URL}/erp/boms/{bom['id']}", headers=headers, timeout=10.0, json={"name": "should be rejected"})
    check("PATCH released BOM -> 409 (rejected, not silently accepted)", r4.status_code == 409, f"got {r4.status_code}: {r4.text[:300]}")

    r5 = client.post(
        f"{BASE_URL}/erp/boms/{bom['id']}/revise", headers=headers, timeout=10.0,
        json={"new_revision": "B", "copy_items": True},
    )
    check("revise released BOM -> 201, new draft revision", r5.status_code == 201 and r5.json().get("status") == "draft", f"got {r5.status_code}: {r5.text[:300]}")
    if r5.status_code == 201:
        ids["bom_ids"].append(r5.json()["id"])
        check("revision.supersedes_bom_id points at old BOM", r5.json().get("supersedes_bom_id") == bom["id"], r5.json().get("supersedes_bom_id"))


def three_way_match_checks(client: httpx.Client, headers: dict, ids: dict) -> None:
    # PO for the intra-state vendor, qty=50 kg @ rate=20 -> taxable=1000.00
    r = client.post(
        f"{BASE_URL}/erp/pos", headers=headers, timeout=10.0,
        json={
            "vendor_id": ids["vendor_intra_id"],
            "items": [{"description": "3-way match test material", "hsn": "9999", "qty": 50, "unit": "kg", "rate": 20, "gst_rate": 18}],
        },
    )
    check("3wm: create PO -> 201", r.status_code == 201, f"got {r.status_code}: {r.text[:300]}")
    po = r.json()
    ids.setdefault("po_ids", []).append(po["id"])

    r2 = client.post(f"{BASE_URL}/erp/pos/{po['id']}/issue", headers=headers, timeout=10.0)
    check("3wm: issue PO -> 200", r2.status_code == 200, f"got {r2.status_code}")

    detail = client.get(f"{BASE_URL}/erp/pos/{po['id']}", headers=headers, timeout=10.0).json()
    po_item_id = detail["items"][0]["id"]
    grand_total = Decimal(str(detail["totals"]["grand_total"]))
    taxable = Decimal(str(detail["totals"]["taxable"]))
    gst = Decimal(str(detail["totals"]["cgst"])) + Decimal(str(detail["totals"]["sgst"])) + Decimal(str(detail["totals"]["igst"]))

    r3 = client.post(
        f"{BASE_URL}/erp/grn", headers=headers, timeout=10.0,
        json={
            "po_id": po["id"], "grn_no": f"P5GATE-GRN-{uuid.uuid4().hex[:10]}",
            "lines": [{"po_item_id": po_item_id, "qty_received": 50, "qty_accepted": 50, "qty_rejected": 0}],
        },
    )
    check("3wm: create GRN (full receipt) -> 201", r3.status_code == 201, f"got {r3.status_code}: {r3.text[:300]}")
    if r3.status_code == 201:
        ids.setdefault("grn_ids", []).append(r3.json()["id"])
        check("3wm: PO status rolls to 'received' after full GRN", r3.json().get("po_status") == "received", r3.json().get("po_status"))

    # Mismatched invoice (total is wildly off) -> check() says not ok, approve -> 400, status unchanged.
    r4 = client.post(
        f"{BASE_URL}/erp/vendor-invoices", headers=headers, timeout=10.0,
        json={
            "vendor_id": ids["vendor_intra_id"], "po_id": po["id"], "inv_no": f"P5GATE-INV-MISMATCH-{uuid.uuid4().hex[:6]}",
            "taxable": str(taxable), "gst": str(gst), "total": str(grand_total * Decimal("2")),
        },
    )
    check("3wm: create mismatched invoice -> 201", r4.status_code == 201, f"got {r4.status_code}: {r4.text[:300]}")
    if r4.status_code == 201:
        inv_bad = r4.json()
        ids.setdefault("invoice_ids", []).append(inv_bad["id"])

        r5 = client.post(f"{BASE_URL}/erp/vendor-invoices/{inv_bad['id']}/check", headers=headers, timeout=10.0)
        check("3wm: /check on mismatched invoice reports ok=false", r5.status_code == 200 and r5.json().get("ok") is False, r5.text[:300])

        r6 = client.post(f"{BASE_URL}/erp/vendor-invoices/{inv_bad['id']}/approve", headers=headers, timeout=10.0)
        check("3wm: approve on mismatched invoice -> 400 (blocked)", r6.status_code == 400, f"got {r6.status_code}: {r6.text[:300]}")

        r7 = client.get(f"{BASE_URL}/erp/vendor-invoices/{inv_bad['id']}", headers=headers, timeout=10.0)
        check("3wm: mismatched invoice status did NOT advance to approved", r7.json().get("status") != "approved", r7.json().get("status"))

    # Matching invoice -> check() ok=true, approve -> 200, status='approved'.
    r8 = client.post(
        f"{BASE_URL}/erp/vendor-invoices", headers=headers, timeout=10.0,
        json={
            "vendor_id": ids["vendor_intra_id"], "po_id": po["id"], "inv_no": f"P5GATE-INV-MATCH-{uuid.uuid4().hex[:6]}",
            "taxable": str(taxable), "gst": str(gst), "total": str(grand_total),
        },
    )
    check("3wm: create matching invoice -> 201", r8.status_code == 201, f"got {r8.status_code}: {r8.text[:300]}")
    if r8.status_code == 201:
        inv_good = r8.json()
        ids.setdefault("invoice_ids", []).append(inv_good["id"])

        r9 = client.post(f"{BASE_URL}/erp/vendor-invoices/{inv_good['id']}/check", headers=headers, timeout=10.0)
        check("3wm: /check on matching invoice reports ok=true", r9.status_code == 200 and r9.json().get("ok") is True, r9.text[:300])

        r10 = client.post(f"{BASE_URL}/erp/vendor-invoices/{inv_good['id']}/approve", headers=headers, timeout=10.0)
        check(
            "3wm: approve on matching invoice -> 200, status='approved'",
            r10.status_code == 200 and r10.json().get("status") == "approved",
            f"got {r10.status_code}: {r10.text[:300]}",
        )


def main() -> int:
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL not set (check .env)", file=sys.stderr)
        return 2

    print("=" * 70)
    print("P5 GATE: setup (seed/seed.py baseline + P5 gate fixtures)")
    print("=" * 70)

    seed_proc = subprocess.run([sys.executable, os.path.join(ROOT, "seed", "seed.py")], cwd=ROOT, capture_output=True, text=True)
    if seed_proc.returncode != 0:
        print(seed_proc.stdout)
        print(seed_proc.stderr, file=sys.stderr)
        print("ERROR: seed/seed.py failed", file=sys.stderr)
        return 2
    print(seed_proc.stdout.strip())

    ids = seed_db()
    print(f"seeded intra-state vendor {ids['vendor_intra_id']} (state {ids['company_state_code']}), "
          f"inter-state vendor {ids['vendor_inter_id']} (state {ids['other_state_code']}), "
          f"project {ids['project_id']}")

    print()
    print("=" * 70)
    print("P5 GATE: starting API (api.erp_app)")
    print("=" * 70)

    env = os.environ.copy()
    env["API_PORT"] = str(API_PORT)
    log_path = os.path.join(ROOT, "tests", "_p5_gate_api.log")
    log_file = open(log_path, "w", encoding="utf-8")
    api_proc = subprocess.Popen(
        [sys.executable, "-m", "api.erp_app"],
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

        with httpx.Client() as client:
            print()
            print("=" * 70)
            print("P5 GATE: login as global_admin")
            print("=" * 70)
            token = login(client)
            headers = {"Authorization": f"Bearer {token}"}
            check("login: global_admin JWT issued", True)

            print()
            print("=" * 70)
            print("P5 GATE: GST logic (the literal P5 acceptance gate)")
            print("=" * 70)
            gst_checks(client, headers, ids)

            print()
            print("=" * 70)
            print("P5 GATE: BOM release immutability")
            print("=" * 70)
            bom_immutability_check(client, headers, ids)

            print()
            print("=" * 70)
            print("P5 GATE: 3-way match (PO vs GRN vs invoice)")
            print("=" * 70)
            three_way_match_checks(client, headers, ids)

        print()
        print("=" * 70)
        failed = [n for n, ok in results if not ok]
        if failed:
            print(f"P5 GATE: FAIL ({len(failed)}/{len(results)} checks failed)")
            for n in failed:
                print(f"  - {n}")
            exit_code = 1
        else:
            print(f"P5 GATE: PASS ({len(results)}/{len(results)} checks passed)")
            exit_code = 0
    finally:
        print()
        print("=" * 70)
        print("P5 GATE: teardown")
        print("=" * 70)
        api_proc.terminate()
        try:
            api_proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            api_proc.kill()
        log_file.close()
        teardown_db(ids)
        print("removed all P5 gate fixture rows, stopped API")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
