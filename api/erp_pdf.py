"""P5: Purchase Order PDF generation (ReportLab, A4). Pure function
(dict-in -> bytes-out) so it's easy to test without the API/DB.
"""
from __future__ import annotations

import io
from decimal import Decimal
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet

from .erp_calc import amount_in_words, indian_group_str

_styles = getSampleStyleSheet()
_title = ParagraphStyle("PoTitle", parent=_styles["Title"], fontSize=16, spaceAfter=2)
_h2 = ParagraphStyle("PoH2", parent=_styles["Heading2"], fontSize=11, spaceAfter=2)
_normal = ParagraphStyle("PoNormal", parent=_styles["Normal"], fontSize=9, leading=12)
_small = ParagraphStyle("PoSmall", parent=_styles["Normal"], fontSize=8, leading=10)


def _money(v) -> str:
    return f"Rs. {indian_group_str(int(round(float(v))))}.{str(round(float(v) % 1, 2))[2:].ljust(2, '0')[:2]}"


def build_po_pdf(*, company: dict[str, Any], vendor: dict[str, Any], po: dict[str, Any],
                  items: list[dict[str, Any]], totals: dict[str, Decimal]) -> bytes:
    """items: list of dicts with description/hsn/qty/unit/rate/gst_rate/
    taxable/cgst/sgst/igst/line_total (already computed via erp_calc).
    totals: dict with taxable/cgst/sgst/igst/freight/grand_total (Decimal).
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=15 * mm,
        title=f"Purchase Order {po['po_no']}",
    )
    story: list = []

    story.append(Paragraph(company["name"], _title))
    story.append(Paragraph(company["address"], _normal))
    story.append(Paragraph(f"GSTIN: {company['gstin']} | State Code: {company['state_code']}", _normal))
    if company.get("phone") or company.get("email"):
        story.append(Paragraph(f"Phone: {company.get('phone', '')} | Email: {company.get('email', '')}", _normal))
    story.append(Spacer(1, 8))
    story.append(Paragraph("PURCHASE ORDER", _h2))

    meta_table = Table(
        [
            ["PO No.", po["po_no"], "PO Date", str(po["po_date"])],
            ["Payment Terms", po.get("payment_terms") or "-", "Delivery Terms", po.get("delivery_terms") or "-"],
        ],
        colWidths=[30 * mm, 60 * mm, 30 * mm, 60 * mm],
    )
    meta_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 8))

    vendor_ship = Table(
        [[
            Paragraph(
                f"<b>Vendor</b><br/>{vendor['name']}<br/>{vendor.get('address') or ''}"
                f"<br/>GSTIN: {vendor.get('gstin') or '-'} | State Code: {vendor.get('state_code') or '-'}"
                f"<br/>Contact: {vendor.get('contact') or '-'} {vendor.get('phone') or ''}",
                _normal,
            ),
            Paragraph(
                f"<b>Ship To</b><br/>{po.get('delivery_address') or company['address']}",
                _normal,
            ),
        ]],
        colWidths=[90 * mm, 90 * mm],
    )
    vendor_ship.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(vendor_ship)
    story.append(Spacer(1, 8))

    header = ["#", "Description", "HSN", "Qty", "Unit", "Rate", "Taxable", "GST%", "CGST", "SGST", "IGST", "Total"]
    rows = [header]
    for i, it in enumerate(items, start=1):
        rows.append([
            str(i),
            Paragraph(it["description"], _small),
            it.get("hsn") or "-",
            f"{float(it['qty']):g}",
            it["unit"],
            f"{float(it['rate']):.2f}",
            f"{it['taxable']:.2f}",
            f"{float(it['gst_rate']):g}",
            f"{it['cgst']:.2f}",
            f"{it['sgst']:.2f}",
            f"{it['igst']:.2f}",
            f"{it['line_total']:.2f}",
        ])
    items_table = Table(
        rows,
        colWidths=[8 * mm, 42 * mm, 14 * mm, 12 * mm, 12 * mm, 16 * mm, 18 * mm, 10 * mm, 14 * mm, 14 * mm, 14 * mm, 18 * mm],
        repeatRows=1,
    )
    items_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5e5e5")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(items_table)
    story.append(Spacer(1, 8))

    totals_rows = [
        ["Taxable Total", f"Rs. {totals['taxable']:.2f}"],
        ["CGST", f"Rs. {totals['cgst']:.2f}"],
        ["SGST", f"Rs. {totals['sgst']:.2f}"],
        ["IGST", f"Rs. {totals['igst']:.2f}"],
    ]
    if totals.get("freight"):
        totals_rows.append(["Freight", f"Rs. {totals['freight']:.2f}"])
    totals_rows.append(["Grand Total", f"Rs. {totals['grand_total']:.2f}"])
    totals_table = Table(totals_rows, colWidths=[40 * mm, 40 * mm], hAlign="RIGHT")
    totals_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("LINEABOVE", (0, -1), (-1, -1), 0.75, colors.black),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
    ]))
    story.append(totals_table)
    story.append(Spacer(1, 6))
    story.append(Paragraph(f"<b>Amount in Words:</b> {amount_in_words(totals['grand_total'])}", _normal))
    story.append(Spacer(1, 10))

    if po.get("notes"):
        story.append(Paragraph(f"<b>Notes:</b> {po['notes']}", _normal))
        story.append(Spacer(1, 6))

    story.append(Paragraph("<b>Terms &amp; Conditions</b>", _small))
    terms = [
        "1. Please acknowledge receipt of this Purchase Order and confirm the delivery schedule.",
        "2. Material must be accompanied by a valid Test Certificate / MTC and E-Way Bill where applicable.",
        "3. Invoice must quote this PO number and mention GSTIN, HSN codes, and applicable GST breakup.",
        "4. Any variation in quantity/rate must be pre-approved in writing before dispatch.",
        "5. Payment as per Payment Terms above, subject to acceptance at Airthra's incoming QC.",
        "6. This PO is subject to Goa jurisdiction.",
    ]
    for t in terms:
        story.append(Paragraph(t, _small))
    story.append(Spacer(1, 20))

    sig_table = Table(
        [["For " + vendor["name"], "For " + company["name"]],
         ["", ""],
         ["Authorized Signatory", "Authorized Signatory"]],
        colWidths=[90 * mm, 90 * mm],
        rowHeights=[10 * mm, 14 * mm, 6 * mm],
    )
    sig_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("LINEBELOW", (0, 1), (0, 1), 0.5, colors.black),
        ("LINEBELOW", (1, 1), (1, 1), 0.5, colors.black),
    ]))
    story.append(sig_table)

    doc.build(story)
    return buf.getvalue()
