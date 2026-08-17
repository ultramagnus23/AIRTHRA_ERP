#!/usr/bin/env python
"""Seeds one contract for goa_pilot_01, matching the rate the old global
SO2_RATE_PER_KG env var used (INR 45.00/kg, default value), so migrating
to the contract-driven billing engine (migration 0008_contracts,
workers/billing_worker.py) does not silently change what the one plant
with real historical invoices gets billed.

Deliberately does NOT create contracts for other plants - a plant with no
contract is correctly billed nothing (billing_worker.py skips it with an
explicit reason) rather than inheriting a default rate it never agreed
to. Every other plant needs a real commercial decision, made through
POST /admin/contracts, not a seed script's guess.

Idempotent: skips if goa_pilot_01 already has an active contract.

Usage:
    .venv/Scripts/python.exe workers/seed_contracts.py
"""
from __future__ import annotations

import os
import sys
from datetime import date

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT, ".env"))

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL is not set (check .env)", file=sys.stderr)
    sys.exit(1)

# Matches the legacy SO2_RATE_PER_KG default exactly - a like-for-like
# migration, not a silent price change.
LEGACY_USAGE_RATE = 45.0


def main() -> None:
    engine = create_engine(DATABASE_URL, future=True)
    with engine.begin() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM contracts WHERE plant_id = 'goa_pilot_01' AND status = 'active'")
        ).first()
        if exists:
            print("[seed_contracts] goa_pilot_01 already has an active contract - no-op")
            return

        row = conn.execute(
            text(
                """
                INSERT INTO contracts
                    (plant_id, status, effective_from, base_fee_inr, usage_rate_inr_per_kg,
                     performance_bonus_threshold_pct, performance_bonus_inr,
                     performance_penalty_threshold_pct, performance_penalty_inr, notes)
                VALUES
                    ('goa_pilot_01', 'active', :from_date, 0, :rate,
                     98, 5000, 85, 10000,
                     'Migrated from the legacy global SO2_RATE_PER_KG env var (INR 45/kg). '
                     'Performance thresholds are illustrative pilot defaults, not a negotiated '
                     'commercial term - review before relying on them.')
                RETURNING contract_id
                """
            ),
            {"from_date": date(2026, 6, 1), "rate": LEGACY_USAGE_RATE},
        ).first()
    print(f"[seed_contracts] created contract {row[0]} for goa_pilot_01 at INR {LEGACY_USAGE_RATE}/kg")


if __name__ == "__main__":
    main()
