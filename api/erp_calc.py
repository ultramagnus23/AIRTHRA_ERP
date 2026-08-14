"""P5 pure-function helpers: BOM material-weight/cost calculator, PO number
generation (fiscal-year formatting only - the atomic sequence itself is a
DB-side concern, see erp_pos.py::next_po_no), GST split, and Indian-numbering
amount-in-words.

Kept dependency-free (no DB, no FastAPI) so it is trivially unit-testable and
reused identically by both the live-preview endpoint and the persist-on-save
path, per the P5 spec ("never trust client-computed weights").
"""
from __future__ import annotations

import math
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

Shape = Literal["plate", "rod", "pipe", "custom"]


class BomCalcError(ValueError):
    """Raised when dims are missing/invalid for the given shape."""


def _num(dims: dict[str, Any], key: str) -> float:
    if key not in dims or dims[key] is None:
        raise BomCalcError(f"dims.{key} is required for this shape")
    try:
        v = float(dims[key])
    except (TypeError, ValueError) as exc:
        raise BomCalcError(f"dims.{key} must be numeric") from exc
    if v < 0:
        raise BomCalcError(f"dims.{key} must be >= 0")
    return v


def compute_unit_weight_kg(shape: Shape, dims: dict[str, Any], density_kg_m3: float | None,
                            scrap_pct: float) -> float:
    """unit_weight_kg for one piece, per PRD 4.3 BOM calculator (P5 item 2).

    plate/rod/pipe: geometry (mm inputs, converted to m) x density x
    (1 + scrap_pct/100).
    custom: dims.unit_weight_kg is a catalog value already representing the
    real per-piece weight - used as-is, no geometry, no scrap multiplier
    (scrap only applies to material Airthra machines from raw stock; a
    custom/catalog item is bought finished).
    """
    if shape == "custom":
        if "unit_weight_kg" not in dims or dims["unit_weight_kg"] is None:
            raise BomCalcError("dims.unit_weight_kg is required for shape 'custom'")
        try:
            return float(dims["unit_weight_kg"])
        except (TypeError, ValueError) as exc:
            raise BomCalcError("dims.unit_weight_kg must be numeric") from exc

    if density_kg_m3 is None:
        raise BomCalcError("material has no density_kg_m3 set - cannot compute geometry-based weight")
    density = float(density_kg_m3)

    if shape == "plate":
        length_m = _num(dims, "length_mm") / 1000.0
        width_m = _num(dims, "width_mm") / 1000.0
        thickness_m = _num(dims, "thickness_mm") / 1000.0
        volume_m3 = length_m * width_m * thickness_m
    elif shape == "rod":
        diameter_m = _num(dims, "diameter_mm") / 1000.0
        length_m = _num(dims, "length_mm") / 1000.0
        volume_m3 = math.pi * (diameter_m / 2) ** 2 * length_m
    elif shape == "pipe":
        od_m = _num(dims, "od_mm") / 1000.0
        wall_m = _num(dims, "wall_mm") / 1000.0
        length_m = _num(dims, "length_mm") / 1000.0
        outer_r = od_m / 2
        inner_r = outer_r - wall_m
        if inner_r < 0:
            raise BomCalcError("dims.wall_mm cannot exceed od_mm/2")
        volume_m3 = math.pi * (outer_r ** 2 - inner_r ** 2) * length_m
    else:
        raise BomCalcError(f"unknown shape '{shape}'")

    scrap_mult = 1 + (float(scrap_pct or 0) / 100.0)
    return volume_m3 * density * scrap_mult


def compute_bom_item(shape: Shape, dims: dict[str, Any], qty: float, scrap_pct: float,
                      density_kg_m3: float | None, rate_per_kg: float | None) -> dict[str, float]:
    """Full server-side calc for one bom_items row: unit weight, total
    weight (x qty), and cost (x materials.rate_per_kg)."""
    unit_weight_kg = compute_unit_weight_kg(shape, dims, density_kg_m3, scrap_pct)
    total_weight_kg = unit_weight_kg * float(qty)
    rate = float(rate_per_kg) if rate_per_kg is not None else 0.0
    cost = total_weight_kg * rate
    # Round via string formatting (not `round()` on the raw float) before
    # converting to Decimal, so what actually gets bound into the numeric
    # DB columns is the clean decimal value, not float64 binary noise like
    # Decimal(5151.5600000000004...) - see api/routers/erp_invoices.py's
    # docstring for the same class of bug on the money-input side.
    return {
        "unit_weight_kg": Decimal(f"{unit_weight_kg:.6f}"),
        "total_weight_kg": Decimal(f"{total_weight_kg:.6f}"),
        "cost": Decimal(f"{cost:.2f}"),
    }


# ---------------------------------------------------------------------------
# Indian fiscal year / PO numbering
# ---------------------------------------------------------------------------

def fiscal_year_label(d: date) -> str:
    """Indian FY (Apr-Mar) as 'YY-YY', e.g. 2026-08-14 -> '26-27'
    (matches the CHECK constraint on pos.po_no in the P0 migration:
    '^AIR/PO/\\d{2}-\\d{2}/\\d{4}$')."""
    start_year = d.year if d.month >= 4 else d.year - 1
    end_year = start_year + 1
    return f"{start_year % 100:02d}-{end_year % 100:02d}"


def format_po_no(fy_label: str, seq: int) -> str:
    return f"AIR/PO/{fy_label}/{seq:04d}"


# ---------------------------------------------------------------------------
# GST
# ---------------------------------------------------------------------------

def gst_split_for_line(taxable: Decimal, gst_rate: Decimal, vendor_state_code: str | None,
                        company_state_code: str) -> dict[str, Decimal]:
    """Per po_items row: CGST+SGST if vendor is in the same state as the
    company, else IGST. Returns cgst/sgst/igst/total_gst/line_total, each a
    Decimal rounded to 2dp."""
    gst_amount = (taxable * gst_rate / Decimal(100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    same_state = vendor_state_code is not None and vendor_state_code == company_state_code
    if same_state:
        half = (gst_amount / 2).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        cgst, sgst, igst = half, gst_amount - half, Decimal("0.00")
    else:
        cgst, sgst, igst = Decimal("0.00"), Decimal("0.00"), gst_amount
    total_gst = cgst + sgst + igst
    return {
        "cgst": cgst,
        "sgst": sgst,
        "igst": igst,
        "total_gst": total_gst,
        "line_total": (taxable + total_gst).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
    }


# ---------------------------------------------------------------------------
# Amount in words (Indian numbering: crore / lakh / thousand / hundred)
# ---------------------------------------------------------------------------

_ONES = [
    "", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
    "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
    "Seventeen", "Eighteen", "Nineteen",
]
_TENS = [
    "", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety",
]


def _two_digit_words(n: int) -> str:
    if n < 20:
        return _ONES[n]
    tens, ones = divmod(n, 10)
    return _TENS[tens] + (f" {_ONES[ones]}" if ones else "")


def _three_digit_words(n: int) -> str:
    hundreds, rest = divmod(n, 100)
    parts = []
    if hundreds:
        parts.append(f"{_ONES[hundreds]} Hundred")
    if rest:
        parts.append(_two_digit_words(rest))
    return " ".join(parts)


def _int_to_indian_words(n: int) -> str:
    if n == 0:
        return "Zero"
    if n < 0:
        return "Minus " + _int_to_indian_words(-n)

    crore, n = divmod(n, 10_000_000)
    lakh, n = divmod(n, 100_000)
    thousand, hundred = divmod(n, 1_000)

    parts = []
    if crore:
        # crore itself grouped in lakh/thousand/hundred (Indian system has no
        # native word above crore in everyday commercial use - good enough
        # for PO amounts, which never approach 100 crore).
        crore_lakh, crore_rest = divmod(crore, 100_000)
        crore_thousand, crore_hundred = divmod(crore_rest, 1_000)
        crore_words = []
        if crore_lakh:
            crore_words.append(f"{_three_digit_words(crore_lakh)} Lakh")
        if crore_thousand:
            crore_words.append(f"{_three_digit_words(crore_thousand)} Thousand")
        if crore_hundred:
            crore_words.append(_three_digit_words(crore_hundred))
        parts.append(" ".join(crore_words) + " Crore")
    if lakh:
        parts.append(f"{_three_digit_words(lakh)} Lakh")
    if thousand:
        parts.append(f"{_three_digit_words(thousand)} Thousand")
    if hundred:
        parts.append(_three_digit_words(hundred))
    return " ".join(parts)


def amount_in_words(amount: Decimal) -> str:
    """e.g. Decimal('1234567.50') -> 'Twelve Lakh Thirty Four Thousand Five
    Hundred Sixty Seven Rupees And Fifty Paise Only'."""
    amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    rupees = int(amount)
    paise = int((amount - rupees) * 100)

    words = f"{_int_to_indian_words(rupees)} Rupees"
    if paise:
        words += f" And {_int_to_indian_words(paise)} Paise"
    return words + " Only"


def indian_group_str(n: int) -> str:
    """Indian-style thousands separators for display, e.g. 1234567 ->
    '12,34,567' (not used for amount_in_words, just for PDF display)."""
    s = str(abs(n))
    if len(s) <= 3:
        out = s
    else:
        last3, rest = s[-3:], s[:-3]
        groups = []
        while len(rest) > 2:
            groups.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            groups.insert(0, rest)
        out = ",".join(groups) + "," + last3
    return ("-" if n < 0 else "") + out
