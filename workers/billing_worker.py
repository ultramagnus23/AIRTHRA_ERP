#!/usr/bin/env python
"""P7 §5.4 monthly billing worker.

For each plant, for a given calendar-month period, computes so2_kg,
k2so3_kg, uptime_pct from `readings` (raw, read-only - never mutated),
renders an A4 PDF invoice via reportlab, uploads it to MinIO with a
sha256 recorded (atomic write/verify, reusing
workers/archive_worker.py's upload_atomic/upload_plain/s3_client/
ensure_bucket helpers rather than re-implementing that pattern), and
upserts one `invoices` row with status='draft'.

Designed to run monthly in production but is a plain on-demand function
here (`generate_invoice`) plus a CLI wrapper, so it can be exercised
directly by tests/p7_gate.py without a real month elapsing.

--------------------------------------------------------------------------
SO2-captured mass calculation (documented assumptions)
--------------------------------------------------------------------------
The plant reports SO2_in/SO2_out in ppm (volumetric) and `flow` in m3/h
(see seed/seed.py's SENSORS manifest). For each calendar hour in the
billed period:

    delta_ppm = avg(SO2_in) - avg(SO2_out)   over that hour
    kg_captured_this_hour = max(0, delta_ppm) * avg(flow_m3h) * SO2_KG_PER_PPM_M3

SO2_KG_PER_PPM_M3 assumes SO2 gas density at STP (0degC, 1atm) of
~2.86 kg/m3 (molar mass 64.07 g/mol / 22.414 L/mol molar volume), so
1 ppm (1e-6 volume fraction) of a flow F (m3, i.e. flow_m3h * 1h) has
mass 2.86e-6 * F kg. This ignores real stack temperature/pressure
correction (a true process-engineering flue-gas model is out of scope
for P7, same "documented placeholder" spirit as
workers/kpi_worker.py's mass_balance_closure).

k2so3_kg is derived stoichiometrically from so2_kg via the reaction
SO2 + 2KOH -> K2SO3 + H2O (1:1 molar), using the molar mass ratio
158.27/64.07 = K2SO3_PER_SO2_MASS_RATIO -- again a placeholder pending a
real yield/efficiency model, not a measured byproduct mass (the schema
has no absolute-mass K2SO3 sensor, only a tank-level % sensor).

--------------------------------------------------------------------------
Contractual gap rule (configurable, documented choice)
--------------------------------------------------------------------------
An hour is "flagged" if it has zero readings for SO2_in/SO2_out/flow, OR
more than FLAGGED_HOUR_THRESHOLD (50%) of the readings feeding any one of
those three sensors' hourly average are non-good (quality_flag != 'good').

Two modes (BILLING_GAP_MODE env var, or the `gap_mode` argument):

  - "exclude" (DEFAULT): flagged hours contribute 0 kg captured and are
    simply not billed for. This is the more DEFENSIBLE default for a
    hardware-as-a-service billing contract: Airthra never invoices the
    client for SO2 capture it cannot actually evidence with good sensor
    data, which avoids billing disputes and is the conservative choice
    when acting as the party issuing the invoice. It does mean flagged
    sensor time directly reduces revenue, which is also the correct
    incentive for Airthra to keep its own sensors calibrated/online.

  - "trailing_avg": flagged hours are imputed using the average of the
    same hour-of-day over the trailing 7 days (looking back from that
    hour, using only hours in that lookback window that were themselves
    NOT flagged). If there isn't enough non-flagged history in the
    lookback window either, that hour silently falls back to "exclude"
    behaviour for this hour only (never fabricates a number from zero
    real data). This mode is offered because some contracts may prefer
    "bill based on best-estimate normal operation" over "bill zero
    during any fault", but it is NOT the default here because it can
    overstate performance during genuine equipment/process faults
    (as opposed to sensor faults), which is a worse look for a billing
    dispute than under-billing.

uptime_pct always reflects the fraction of hours in the period that were
NOT flagged (i.e. data availability), independent of which gap_mode was
used to fill the kg calculation for those hours.

--------------------------------------------------------------------------
Usage
--------------------------------------------------------------------------
    .venv/Scripts/python.exe workers/billing_worker.py \
        [--plant-id ID] [--period YYYY-MM] [--gap-mode exclude|trailing_avg]

    --plant-id   Bill only this plant (default: all plants).
    --period     Calendar month to bill, YYYY-MM (default: previous
                 calendar month, UTC).
    --gap-mode   Overrides BILLING_GAP_MODE env var / the "exclude" default.

Reads DATABASE_URL and MINIO_* from .env (repo root), same convention as
workers/archive_worker.py and workers/kpi_worker.py. Uses the plain
superuser DSN (bypasses RLS) - internal cross-plant batch job, same trust
level as those two workers.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import Engine  # noqa: E402

# Reuse P4's atomic-upload/verify + S3 helpers rather than re-implementing
# them - read-only reuse of workers/archive_worker.py, no modification.
from workers.archive_worker import (  # noqa: E402
    MINIO_BUCKET,
    ensure_bucket,
    public_url,
    s3_client,
    sha256_bytes,
    sha256_file,
    upload_atomic,
)

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL is not set (check .env)", file=sys.stderr)
    sys.exit(1)

# --- Billing constants (documented above) ---
SO2_KG_PER_PPM_M3 = 2.86e-6
K2SO3_PER_SO2_MASS_RATIO = 158.27 / 64.07  # ~2.4700
FLAGGED_HOUR_THRESHOLD = 0.5
TRAILING_LOOKBACK_DAYS = 7
DEFAULT_GAP_MODE = os.environ.get("BILLING_GAP_MODE", "exclude")
assert DEFAULT_GAP_MODE in ("exclude", "trailing_avg")

# SO2_RATE_PER_KG / a single global rate is GONE. Every plant now bills
# against its own `contracts` row (migration 0008_contracts) - base fee +
# usage rate + an uptime-gated performance bonus/penalty, configured per
# plant rather than one number shared across the whole fleet. See
# _active_contract() and _compute_line_items() below.

SENSOR_SO2_IN = "SO2_in"
SENSOR_SO2_OUT = "SO2_out"
SENSOR_FLOW = "flow"


# ---------------------------------------------------------------------------
# Period helpers
# ---------------------------------------------------------------------------

def month_bounds(period: str) -> tuple[datetime, datetime]:
    year, month = (int(x) for x in period.split("-"))
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    end = datetime(year + 1, 1, 1, tzinfo=timezone.utc) if month == 12 else datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, end


def previous_month_period(today: date | None = None) -> str:
    today = today or datetime.now(timezone.utc).date()
    first_of_this_month = today.replace(day=1)
    last_month_end = first_of_this_month - timedelta(days=1)
    return f"{last_month_end.year:04d}-{last_month_end.month:02d}"


# ---------------------------------------------------------------------------
# Hourly sensor aggregation (plain SQL date_trunc, NOT the readings_1h
# continuous aggregate - avoids depending on CAGG materialization timing,
# which matters for freshly bulk-inserted historical/synthetic data such
# as tests/p7_gate.py's synthetic month)
# ---------------------------------------------------------------------------

def hourly_sensor_data(engine: Engine, plant_id: str, sensor_id: str, start: datetime, end: datetime) -> dict:
    """Returns {hour_bucket: {"avg": float|None, "total": int, "non_good": int}}."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT date_trunc('hour', ts) AS bucket,
                       avg(value) AS avg_value,
                       count(*) AS total,
                       count(*) FILTER (WHERE quality_flag <> 'good') AS non_good
                FROM readings
                WHERE plant_id = :plant_id AND sensor_id = :sensor_id
                  AND ts >= :start AND ts < :end
                GROUP BY bucket
                """
            ),
            {"plant_id": plant_id, "sensor_id": sensor_id, "start": start, "end": end},
        ).mappings().all()
    return {
        r["bucket"]: {"avg": r["avg_value"], "total": r["total"], "non_good": r["non_good"]}
        for r in rows
    }


def _is_flagged(hour_data: dict | None) -> bool:
    if hour_data is None or not hour_data["total"] or hour_data["avg"] is None:
        return True
    return (hour_data["non_good"] / hour_data["total"]) > FLAGGED_HOUR_THRESHOLD


def _trailing_avg(series: dict, hour: datetime) -> float | None:
    """Average of the same hour-of-day over the trailing lookback window,
    using only non-flagged hours in that window. None if no such hours."""
    vals = []
    for i in range(1, TRAILING_LOOKBACK_DAYS + 1):
        candidate = hour - timedelta(days=i)
        data = series.get(candidate)
        if data is not None and not _is_flagged(data):
            vals.append(data["avg"])
    return sum(vals) / len(vals) if vals else None


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_billing_numbers(engine: Engine, plant_id: str, period: str, gap_mode: str) -> dict:
    start, end = month_bounds(period)
    lookback_start = start - timedelta(days=TRAILING_LOOKBACK_DAYS)

    so2_in = hourly_sensor_data(engine, plant_id, SENSOR_SO2_IN, lookback_start, end)
    so2_out = hourly_sensor_data(engine, plant_id, SENSOR_SO2_OUT, lookback_start, end)
    flow = hourly_sensor_data(engine, plant_id, SENSOR_FLOW, lookback_start, end)

    total_hours = int((end - start).total_seconds() // 3600)
    good_hours = 0
    so2_kg_total = 0.0
    hours_billed = 0

    hour = start
    while hour < end:
        in_flagged = _is_flagged(so2_in.get(hour))
        out_flagged = _is_flagged(so2_out.get(hour))
        flow_flagged = _is_flagged(flow.get(hour))
        hour_flagged = in_flagged or out_flagged or flow_flagged

        if not hour_flagged:
            good_hours += 1
            in_val, out_val, flow_val = so2_in[hour]["avg"], so2_out[hour]["avg"], flow[hour]["avg"]
        elif gap_mode == "trailing_avg":
            in_val = so2_in[hour]["avg"] if not in_flagged else _trailing_avg(so2_in, hour)
            out_val = so2_out[hour]["avg"] if not out_flagged else _trailing_avg(so2_out, hour)
            flow_val = flow[hour]["avg"] if not flow_flagged else _trailing_avg(flow, hour)
            if in_val is None or out_val is None or flow_val is None:
                in_val = out_val = flow_val = None  # not enough history either -> falls back to exclude below
        else:
            in_val = out_val = flow_val = None  # "exclude" mode: flagged hour contributes 0

        if in_val is not None and out_val is not None and flow_val is not None:
            delta_ppm = max(0.0, in_val - out_val)
            so2_kg_total += delta_ppm * flow_val * SO2_KG_PER_PPM_M3
            hours_billed += 1

        hour += timedelta(hours=1)

    uptime_pct = round(100.0 * good_hours / total_hours, 2) if total_hours else 0.0
    so2_kg = round(so2_kg_total, 3)
    k2so3_kg = round(so2_kg * K2SO3_PER_SO2_MASS_RATIO, 3)

    # NOTE: no `amount` here anymore. Raw operational numbers (how much
    # was captured, how available was the data) are contract-independent
    # facts about the period; converting them to money is a separate step
    # (_compute_line_items) that needs to know WHICH contract applies.
    return {
        "plant_id": plant_id,
        "period": period,
        "so2_kg": so2_kg,
        "k2so3_kg": k2so3_kg,
        "uptime_pct": uptime_pct,
        "total_hours": total_hours,
        "good_hours": good_hours,
        "hours_billed": hours_billed,
        "gap_mode": gap_mode,
    }


# ---------------------------------------------------------------------------
# Contract-driven pricing
#
# Rule #8 of the platform's own commercial spec: don't hardcode Airthra's
# billing formula into the software. This used to be one env var
# (SO2_RATE_PER_KG) shared by every plant on the fleet; now every plant
# bills against its own `contracts` row.
# ---------------------------------------------------------------------------

def _active_contract(engine: Engine, plant_id: str, period: str) -> dict | None:
    """The contract in force on the FIRST day of the billed period - not
    necessarily today's status='active' row, since billing a past month
    must use whichever contract covered that month even if it has since
    been superseded. Returns None if no contract covers the period at
    all, which the caller must treat as "cannot bill this plant/period",
    never as "bill at some default rate"."""
    period_start, _ = month_bounds(period)
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT contract_id, base_fee_inr, usage_rate_inr_per_kg,
                       performance_bonus_threshold_pct, performance_bonus_inr,
                       performance_penalty_threshold_pct, performance_penalty_inr,
                       revenue_share_pct, status
                FROM contracts
                WHERE plant_id = :plant_id
                  AND effective_from <= :period_start
                  AND (effective_to IS NULL OR effective_to >= :period_start)
                ORDER BY effective_from DESC
                LIMIT 1
                """
            ),
            {"plant_id": plant_id, "period_start": period_start.date()},
        ).mappings().first()
    return dict(row) if row else None


def _compute_line_items(numbers: dict, contract: dict) -> dict:
    """Pure function: (operational numbers, contract terms) -> money.
    No I/O, so it's trivial to unit-test and impossible to accidentally
    apply the wrong contract - the caller already resolved which one."""
    base_fee = float(contract["base_fee_inr"])
    usage_fee = round(numbers["so2_kg"] * float(contract["usage_rate_inr_per_kg"]), 2)

    performance_adjustment = 0.0
    performance_note = None
    bonus_threshold = contract["performance_bonus_threshold_pct"]
    penalty_threshold = contract["performance_penalty_threshold_pct"]
    uptime = numbers["uptime_pct"]

    if bonus_threshold is not None and uptime >= float(bonus_threshold):
        performance_adjustment = float(contract["performance_bonus_inr"])
        performance_note = f"uptime {uptime}% >= {bonus_threshold}% bonus threshold"
    elif penalty_threshold is not None and uptime < float(penalty_threshold):
        performance_adjustment = -float(contract["performance_penalty_inr"])
        performance_note = f"uptime {uptime}% < {penalty_threshold}% penalty threshold"

    total = round(base_fee + usage_fee + performance_adjustment, 2)

    return {
        "contract_id": str(contract["contract_id"]),
        "base_fee_inr": round(base_fee, 2),
        "usage_rate_inr_per_kg": float(contract["usage_rate_inr_per_kg"]),
        "usage_fee_inr": usage_fee,
        "performance_adjustment_inr": round(performance_adjustment, 2),
        "performance_note": performance_note,
        "total_inr": total,
    }


# ---------------------------------------------------------------------------
# PDF rendering
# ---------------------------------------------------------------------------

def render_invoice_pdf(numbers: dict, line_items: dict, plant_name: str, out_path: Path) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(out_path), pagesize=A4)
    width, height = A4
    y = height - 25 * mm

    def line(text_, size=11, dy=8 * mm, bold=False):
        nonlocal y
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        c.drawString(20 * mm, y, text_)
        y -= dy

    line("Airthra Research Private Limited", size=16, bold=True, dy=10 * mm)
    line("FGD Hardware-as-a-Service - Monthly Invoice", size=12, dy=10 * mm)
    line(f"Plant: {plant_name} ({numbers['plant_id']})", bold=True)
    line(f"Billing period: {numbers['period']}")
    line(f"Gap-fill mode: {numbers['gap_mode']}", dy=10 * mm)

    line("Headline figures", size=13, bold=True, dy=9 * mm)
    line(f"SO2 captured:       {numbers['so2_kg']:.3f} kg")
    line(f"K2SO3 produced:     {numbers['k2so3_kg']:.3f} kg")
    line(f"Uptime:              {numbers['uptime_pct']:.2f} %", dy=10 * mm)

    line(f"Billed hours: {numbers['hours_billed']} / {numbers['total_hours']}", size=10, dy=10 * mm)

    line("Charges", size=13, bold=True, dy=9 * mm)
    line(f"Base fee:                    INR {line_items['base_fee_inr']:,.2f}")
    line(
        f"Usage ({line_items['usage_rate_inr_per_kg']:.2f}/kg x {numbers['so2_kg']:.3f} kg): "
        f"INR {line_items['usage_fee_inr']:,.2f}"
    )
    if line_items["performance_adjustment_inr"] != 0:
        sign = "+" if line_items["performance_adjustment_inr"] >= 0 else "-"
        line(
            f"Performance adjustment ({line_items['performance_note']}): "
            f"{sign} INR {abs(line_items['performance_adjustment_inr']):,.2f}"
        )
    line("", dy=2 * mm)

    line("Amount due", size=13, bold=True, dy=9 * mm)
    line(f"INR {line_items['total_inr']:,.2f}", size=14, bold=True)

    c.showPage()
    c.save()


# ---------------------------------------------------------------------------
# Invoice generation (compute -> render -> upload+verify -> upsert row)
# ---------------------------------------------------------------------------

def generate_invoice(engine: Engine, client, plant_id: str, period: str, gap_mode: str | None = None) -> dict:
    gap_mode = gap_mode or DEFAULT_GAP_MODE
    assert gap_mode in ("exclude", "trailing_avg")

    with engine.connect() as conn:
        plant_row = conn.execute(
            text("SELECT name FROM plants WHERE plant_id = :p"), {"p": plant_id}
        ).mappings().first()
    if plant_row is None:
        raise ValueError(f"unknown plant_id '{plant_id}'")
    plant_name = plant_row["name"]

    # No contract covering this period -> cannot honestly produce a
    # figure. Returning a sentinel (never $0, which reads as "billed
    # nothing" rather than "not billed at all") so the CLI loop can skip
    # this plant/period and say so plainly instead of guessing a rate.
    contract = _active_contract(engine, plant_id, period)
    if contract is None:
        return {
            "plant_id": plant_id,
            "period": period,
            "skipped": True,
            "reason": f"no contract covers {plant_id} for period {period} - not billed",
        }

    numbers = compute_billing_numbers(engine, plant_id, period, gap_mode)
    line_items = _compute_line_items(numbers, contract)

    with tempfile.TemporaryDirectory(prefix="airthra_invoice_") as tmpdir:
        local_pdf = Path(tmpdir) / f"{plant_id}_{period}.pdf"
        render_invoice_pdf(numbers, line_items, plant_name, local_pdf)

        digest_hex = sha256_file(local_pdf)
        final_key = f"invoices/{plant_id}/{period}.pdf"

        verified = upload_atomic(client, local_pdf, final_key, digest_hex)
        if not verified:
            raise RuntimeError(
                f"invoice PDF upload verification FAILED for {plant_id} {period}: "
                f"re-downloaded object's sha256 did not match - invoices row NOT written"
            )

        pdf_url = public_url(final_key)

    row = _upsert_invoice(engine, plant_id, period, numbers, line_items, pdf_url)
    numbers["line_items"] = line_items
    numbers["amount"] = line_items["total_inr"]
    numbers["pdf_url"] = pdf_url
    numbers["sha256"] = digest_hex
    numbers["invoice_id"] = str(row["invoice_id"])
    numbers["status"] = row["status"]
    numbers["written"] = row["status"] == "draft" and row["pdf_url"] == pdf_url
    return numbers


def _upsert_invoice(engine: Engine, plant_id: str, period: str, numbers: dict, line_items: dict, pdf_url: str) -> dict:
    with engine.begin() as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO invoices (invoice_id, plant_id, period, so2_kg, k2so3_kg, uptime_pct,
                                       amount, pdf_url, status, contract_id, line_items)
                VALUES (gen_random_uuid(), :plant_id, :period, :so2_kg, :k2so3_kg, :uptime_pct,
                        :amount, :pdf_url, 'draft', :contract_id, CAST(:line_items AS jsonb))
                ON CONFLICT (plant_id, period) DO UPDATE SET
                    so2_kg = EXCLUDED.so2_kg,
                    k2so3_kg = EXCLUDED.k2so3_kg,
                    uptime_pct = EXCLUDED.uptime_pct,
                    amount = EXCLUDED.amount,
                    pdf_url = EXCLUDED.pdf_url,
                    contract_id = EXCLUDED.contract_id,
                    line_items = EXCLUDED.line_items
                WHERE invoices.status = 'draft'
                RETURNING invoice_id, plant_id, period, status, pdf_url
                """
            ),
            {
                "plant_id": plant_id,
                "period": period,
                "contract_id": line_items["contract_id"],
                "line_items": json.dumps(line_items),
                "amount": line_items["total_inr"],
                "so2_kg": numbers["so2_kg"],
                "k2so3_kg": numbers["k2so3_kg"],
                "uptime_pct": numbers["uptime_pct"],
                "pdf_url": pdf_url,
            },
        ).mappings().first()

        if row is None:
            # Conflict happened but WHERE excluded it (existing invoice is no
            # longer 'draft', e.g. already approved) -> don't clobber it,
            # just report its current state.
            row = conn.execute(
                text(
                    """
                    SELECT invoice_id, plant_id, period, status, pdf_url
                    FROM invoices WHERE plant_id = :plant_id AND period = :period
                    """
                ),
                {"plant_id": plant_id, "period": period},
            ).mappings().first()
    return dict(row)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Airthra P7 billing worker")
    parser.add_argument("--plant-id", help="Bill only this plant (default: all plants)")
    parser.add_argument("--period", help="YYYY-MM (default: previous calendar month UTC)")
    parser.add_argument("--gap-mode", choices=["exclude", "trailing_avg"], help="Overrides BILLING_GAP_MODE/default")
    args = parser.parse_args()

    period = args.period or previous_month_period()
    engine = create_engine(DATABASE_URL, future=True)
    client = s3_client()
    ensure_bucket(client)

    if args.plant_id:
        plant_ids = [args.plant_id]
    else:
        with engine.connect() as conn:
            plant_ids = [r[0] for r in conn.execute(text("SELECT plant_id FROM plants ORDER BY plant_id")).fetchall()]

    print(f"[billing_worker] billing period={period} for {len(plant_ids)} plant(s), gap_mode={args.gap_mode or DEFAULT_GAP_MODE}")

    failures = []
    skipped = []
    for plant_id in plant_ids:
        try:
            result = generate_invoice(engine, client, plant_id, period, gap_mode=args.gap_mode)
            if result.get("skipped"):
                # No contract covers this plant/period - NOT a failure, and
                # explicitly not billed at any guessed rate. Distinct from
                # an error so a missing contract doesn't look like a bug.
                print(f"[billing_worker] {plant_id} {period}: SKIPPED - {result['reason']}")
                skipped.append(plant_id)
                continue
            print(
                f"[billing_worker] {plant_id} {period}: so2_kg={result['so2_kg']} "
                f"k2so3_kg={result['k2so3_kg']} uptime_pct={result['uptime_pct']} "
                f"amount={result['amount']} status={result['status']} -> {result['pdf_url']}"
            )
        except Exception as exc:  # noqa: BLE001 - one plant's failure must not kill the rest
            print(f"[billing_worker] ERROR billing {plant_id} {period}: {exc}", file=sys.stderr)
            failures.append((plant_id, str(exc)))

    print()
    billed = len(plant_ids) - len(failures) - len(skipped)
    print(f"[billing_worker] done: {billed} billed, {len(skipped)} skipped (no contract), {len(failures)} failed")
    if failures:
        for plant_id, err in failures:
            print(f"  - {plant_id}: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
