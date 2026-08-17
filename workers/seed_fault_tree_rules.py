#!/usr/bin/env python
"""Fault decision trees (FEED Addendum A Rev 2, Section 3) mapped onto
alarm_rules, honestly scoped to the platform's REAL sensor manifest.

Section 3's trees are written against the FEED's full 41-tag instrument
list and lean heavily on cross-referencing two sensors at once (e.g. tree
3.1: "is AE-02 [SO2 out] high? -> is AT-01 [SO2 in] ALSO high? -> branch
on the answer"). workers/alarm_engine.py's expression_types (threshold,
rolling_z, rate_of_change - see its module docstring) each evaluate a
SINGLE sensor; there is no two-sensor/bracket comparison evaluator in this
schema. Rather than fake a bracket check by disguising it as two unrelated
rules, this file only encodes the sub-conditions that are legitimately
single-sensor checks on their own, and each rule's params doc comment
below names the specific tree/branch it covers and what it does NOT
cover. Trees that are irreducibly two-sensor (or reference tags with no
live sensor at all, e.g. PT-01 vacuum, VFD-P101 current, DP-101) are
listed as blocked in AUDIT.md instead of being approximated here.

Numeric thresholds below are illustrative pilot-plant setpoints, not
transcribed from a FEED setpoint table (none was provided with exact
alarm limits) - flagged in AUDIT.md as needing process-engineering
sign-off before these fire in a way that pages anyone.

Idempotent, same pattern as workers/seed_alarm_rules.py: deterministic
uuid5(rule_id) off the same fixed namespace, ON CONFLICT DO NOTHING.

Usage:
    .venv/Scripts/python.exe workers/seed_fault_tree_rules.py
"""
from __future__ import annotations

import json
import os
import sys
import uuid

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT, ".env"))

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL is not set (check .env)", file=sys.stderr)
    sys.exit(1)

_NAMESPACE = uuid.UUID("6f0e6f5a-0b1a-4c2a-9c3d-000000000001")


def _rule(name: str, **fields) -> dict:
    return {"rule_id": str(uuid.uuid5(_NAMESPACE, name)), "plant_id": None, **fields}


RULES = [
    # FEED tree 3.1, "AT-02 pH < 7.5" branch: KOH solvent depleted.
    # Single-sensor, faithfully reproducible as-is.
    _rule(
        "koh_depletion_low_ph_v1",
        expression_type="threshold",
        params={"sensor_id": "pH", "min": 7.5},
        severity="critical",
        diagnosis="Absorber pH below 7.5 - KOH solvent depleted, absorption efficiency compromised",
        suggested_part="KOH solvent dosing pump / KOH tank replenishment",
        cooldown_s=600,
    ),
    # Operational precursor to the above: catches the depletion before pH
    # actually drops, from the KOH loop's own tank level.
    _rule(
        "koh_tank_low_level_v1",
        expression_type="threshold",
        params={"sensor_id": "level_KOH_tank", "min": 15},
        severity="warning",
        diagnosis="KOH tank level below 15% - solvent replenishment needed before pH excursion occurs",
        suggested_part="KOH solvent supply / tank refill",
        cooldown_s=900,
    ),
    # FEED tree 3.1, "AE-02 high" root check on its own, independent of the
    # AT-01 cross-check branch (that branch is NOT implemented - see module
    # docstring). Stack emissions compliance excursion.
    _rule(
        "so2_out_emissions_excursion_v1",
        expression_type="threshold",
        params={"sensor_id": "SO2_out", "max": 200},
        severity="critical",
        diagnosis="Outlet SO2 exceeds 200ppm - emissions excursion, absorption performance degraded",
        suggested_part="Absorber T-101 packing / KOH dosing (see koh_depletion_low_ph rule for a specific cause if pH is also low)",
        cooldown_s=600,
    ),
    # FEED tree 3.1's "AT-01 also high" branch, approximated as an
    # instability signal on AT-01/SO2_in alone (upstream combustion
    # swings) rather than a true AND with AE-02 - the two-sensor bracket
    # itself is not implemented.
    _rule(
        "so2_in_combustion_instability_v1",
        expression_type="rolling_z",
        params={"sensor_id": "SO2_in", "window": 10, "z_threshold": 3},
        severity="warning",
        diagnosis="Inlet SO2 showing abnormal statistical spike - possible upstream combustion instability",
        suggested_part="Boiler combustion tuning / fuel feed check",
        cooldown_s=600,
    ),
    # FEED tree 3.4, "product not cooling" branch, simplified: this
    # platform has no separate coolant-inlet/outlet delta sensor for
    # E-102, only the single process temp_C tag, so this fires on an
    # absolute high-temp threshold rather than a cooling-delta check.
    _rule(
        "product_loop_overtemp_v1",
        expression_type="threshold",
        params={"sensor_id": "temp_C", "max": 60},
        severity="critical",
        diagnosis="Product loop temperature above 60C - E-102 fouling or coolant supply failure suspected",
        suggested_part="E-102 heat exchanger cleaning / coolant supply check",
        cooldown_s=600,
    ),
    # Not from a specific numbered tree - general pump/blockage fault
    # signature (sudden flow discontinuity), single-sensor and legitimate
    # on its own merits given the FEED's emphasis on flow-path diagnostics.
    _rule(
        "flow_abnormal_rate_of_change_v1",
        expression_type="rate_of_change",
        params={"sensor_id": "flow", "max_rate_per_s": 5},
        severity="warning",
        diagnosis="Process flow changing abnormally fast - possible pump fault, valve failure, or line blockage",
        suggested_part="P-101 pump / inline strainer inspection",
        cooldown_s=600,
    ),
]


def main() -> None:
    engine = create_engine(DATABASE_URL, future=True)
    inserted, skipped = 0, 0
    with engine.begin() as conn:
        for rule in RULES:
            result = conn.execute(
                text(
                    """
                    INSERT INTO alarm_rules
                        (rule_id, plant_id, expression_type, params, severity,
                         diagnosis, suggested_part, cooldown_s)
                    VALUES
                        (:rule_id, :plant_id, :expression_type, CAST(:params AS jsonb), :severity,
                         :diagnosis, :suggested_part, :cooldown_s)
                    ON CONFLICT (rule_id) DO NOTHING
                    RETURNING rule_id
                    """
                ),
                {**rule, "params": json.dumps(rule["params"])},
            )
            if result.first() is not None:
                inserted += 1
                print(f"[seed_fault_tree_rules] inserted {rule['rule_id']}")
            else:
                skipped += 1

    print(f"[seed_fault_tree_rules] done: {inserted} inserted, {skipped} already present")


if __name__ == "__main__":
    main()
