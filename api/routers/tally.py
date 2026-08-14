"""P6: Tally XML voucher export for approved vendor invoices.

Generates a Tally-compatible "Purchase" voucher XML for a single approved
`vendor_invoices` row: party name, voucher date, taxable/GST amounts (split
CGST+SGST if vendor and company share a GST state_code, else IGST), and
total. This implements a reasonable, well-formed subset of Tally's XML
data-interchange schema (ENVELOPE > BODY > IMPORTDATA > REQUESTDATA >
TALLYMESSAGE > VOUCHER, with ALLLEDGERENTRIES.LIST lines) - not a full
Tally-certified export. Structural validity (well-formed XML + required
envelope elements) is what tests/p6_genealogy_gate.py can actually check
in this sandboxed environment; a real Tally-import round-trip is not
testable here and is NOT claimed as verified. See that gate script's
docstring for the explicit limitation.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..deps import CurrentUser, db_session, get_current_user

router = APIRouter(prefix="/erp/tally-export", tags=["tally-export"])


def _sub(parent: ET.Element, tag: str, text_val: str | None = None, **attrib) -> ET.Element:
    el = ET.SubElement(parent, tag, attrib)
    if text_val is not None:
        el.text = text_val
    return el


def _yyyymmdd(d) -> str:
    return d.strftime("%Y%m%d") if d else ""


def build_purchase_voucher_xml(*, company: dict, vendor: dict, invoice: dict) -> bytes:
    taxable = float(invoice["taxable"] or 0)
    gst = float(invoice["gst"] or 0)
    total = float(invoice["total"] or (taxable + gst))

    same_state = bool(company.get("state_code")) and company.get("state_code") == vendor.get("state_code")

    envelope = ET.Element("ENVELOPE")
    header = _sub(envelope, "HEADER")
    _sub(header, "TALLYREQUEST", "Import Data")

    body = _sub(envelope, "BODY")
    import_data = _sub(body, "IMPORTDATA")
    request_desc = _sub(import_data, "REQUESTDESC")
    _sub(request_desc, "REPORTNAME", "Vouchers")
    static_vars = _sub(request_desc, "STATICVARIABLES")
    _sub(static_vars, "SVCURRENTCOMPANY", company.get("name", ""))

    request_data = _sub(import_data, "REQUESTDATA")
    tally_message = _sub(request_data, "TALLYMESSAGE", **{"xmlns:UDF": "TallyUDF"})

    voucher = _sub(
        tally_message, "VOUCHER",
        VCHTYPE="Purchase", ACTION="Create", **{"OBJVIEW": "Accounting Voucher View"},
    )
    _sub(voucher, "DATE", _yyyymmdd(invoice.get("date")))
    _sub(voucher, "VOUCHERTYPENAME", "Purchase")
    _sub(voucher, "VOUCHERNUMBER", invoice.get("inv_no", ""))
    _sub(voucher, "PARTYLEDGERNAME", vendor.get("name", ""))
    _sub(voucher, "PARTYNAME", vendor.get("name", ""))
    _sub(voucher, "NARRATION", f"Vendor invoice {invoice.get('inv_no', '')} (Airthra ERP export)")
    _sub(voucher, "REFERENCE", invoice.get("inv_no", ""))

    # Party ledger: credit, full invoice amount.
    party_entry = _sub(voucher, "ALLLEDGERENTRIES.LIST")
    _sub(party_entry, "LEDGERNAME", vendor.get("name", ""))
    _sub(party_entry, "ISDEEMEDPOSITIVE", "No")
    _sub(party_entry, "AMOUNT", f"{total:.2f}")

    # Purchase ledger: debit, taxable value.
    purchase_entry = _sub(voucher, "ALLLEDGERENTRIES.LIST")
    _sub(purchase_entry, "LEDGERNAME", "Purchase Account")
    _sub(purchase_entry, "ISDEEMEDPOSITIVE", "Yes")
    _sub(purchase_entry, "AMOUNT", f"{-taxable:.2f}")

    # GST ledgers: debit, split CGST+SGST (intra-state) or IGST (inter-state).
    if gst > 0:
        if same_state:
            half = gst / 2
            for name in ("CGST", "SGST"):
                gst_entry = _sub(voucher, "ALLLEDGERENTRIES.LIST")
                _sub(gst_entry, "LEDGERNAME", name)
                _sub(gst_entry, "ISDEEMEDPOSITIVE", "Yes")
                _sub(gst_entry, "AMOUNT", f"{-half:.2f}")
        else:
            gst_entry = _sub(voucher, "ALLLEDGERENTRIES.LIST")
            _sub(gst_entry, "LEDGERNAME", "IGST")
            _sub(gst_entry, "ISDEEMEDPOSITIVE", "Yes")
            _sub(gst_entry, "AMOUNT", f"{-gst:.2f}")

    xml_bytes = ET.tostring(envelope, encoding="utf-8", xml_declaration=True)
    return xml_bytes


@router.get("/vendor-invoice/{invoice_id}")
async def export_vendor_invoice_tally_xml(
    invoice_id: str,
    user: CurrentUser = Depends(get_current_user),
    conn: AsyncConnection = Depends(db_session),
):
    invoice = (
        await conn.execute(
            text(
                """
                SELECT id, vendor_id, po_id, inv_no, date, taxable, gst, total, status
                FROM vendor_invoices WHERE id = :id
                """
            ),
            {"id": invoice_id},
        )
    ).mappings().first()
    if invoice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"vendor_invoice '{invoice_id}' not found")
    if invoice["status"] not in ("approved", "paid"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"vendor_invoice '{invoice_id}' is not approved (status={invoice['status']!r}); "
                   "Tally export requires an approved invoice",
        )

    vendor = (
        await conn.execute(
            text("SELECT id, name, gstin, state_code FROM vendors WHERE id = :id"),
            {"id": invoice["vendor_id"]},
        )
    ).mappings().first()
    if vendor is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invoice has no matching vendor")

    company = (
        await conn.execute(text("SELECT name, gstin, state_code FROM company LIMIT 1"))
    ).mappings().first()
    if company is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="no company record configured")

    xml_bytes = build_purchase_voucher_xml(company=dict(company), vendor=dict(vendor), invoice=dict(invoice))
    return Response(content=xml_bytes, media_type="application/xml")
