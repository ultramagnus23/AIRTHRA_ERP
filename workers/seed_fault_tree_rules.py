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

Numeric thresholds below are transcribed from the FEED instrument
register (see AUDIT.md #1.1/#1.2) wherever the register specifies one.
Two exceptions, both explicit: `flow` has no register entry at all
(platform's own rate-of-change signature), and the two tank-level trips
are litres in the register but percent in this platform's storage -
converted here assuming each tote is a 1000L IBC (documented for the
K2SO3 tote via its `location` field in frontend/lib/types.ts; the KOH
tote's exact rated capacity isn't recorded anywhere in this codebase, so
that one specific number is an assumption, not a transcription - flagged
in AUDIT.md #1.2 rather than presented as sourced).

Idempotent and re-runnable as a retune: deterministic uuid5(rule_id) off
the same fixed namespace, `ON CONFLICT (rule_id) DO UPDATE` - editing a
rule's params/severity/etc. here and re-running the script pushes the
change to an already-seeded DB, it does not require a fresh database.
Rule *names* (and therefore rule_ids) are never renamed once seeded, even
when a rule's meaning changes (e.g. product_loop_overtemp_v1 below is now
the warning tier of a two-tier scheme, not the original single tier) -
`alarms.rule_id` has a FK to `alarm_rules.rule_id`, so a rule that has
ever fired can be retuned in place but not deleted/renamed without
breaking that history.

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
    # FEED tree 3.1, "AT-02 pH < 8.0" branch: KOH solvent depleted.
    # Single-sensor, faithfully reproducible as-is. Threshold matches the
    # FEED register verbatim (AUDIT.md #1.1 originally seeded 7.5, half a
    # pH unit late - corrected here).
    _rule(
        "koh_depletion_low_ph_v1",
        expression_type="threshold",
        params={"sensor_id": "pH", "min": 8.0},
        severity="critical",
        diagnosis="Absorber pH below 8.0 - KOH solvent depleted, absorption efficiency compromised",
        suggested_part="KOH solvent dosing pump / KOH tank replenishment",
        cooldown_s=600,
    ),
    # Operational precursor to the above: catches the depletion before pH
    # actually drops, from the KOH loop's own tank level. 15% assumes a
    # 1000L KOH tote against the register's <150L trip - see module
    # docstring and AUDIT.md #1.2 for why that capacity is an assumption,
    # not a transcription.
    _rule(
        "koh_tank_low_level_v1",
        expression_type="threshold",
        params={"sensor_id": "level_KOH_tank", "min": 15},
        severity="warning",
        diagnosis="KOH tank level below 15% (~150L of an assumed 1000L tote) - solvent replenishment needed before pH excursion occurs",
        suggested_part="KOH solvent supply / tank refill",
        cooldown_s=900,
    ),
    # FEED tree 3.1, "AE-02 high" root check on its own, independent of the
    # AT-01 cross-check branch (that branch is NOT implemented - see module
    # docstring). Stack emissions compliance excursion. Threshold matches
    # the FEED register's trip verbatim (AUDIT.md #1.1 originally seeded
    # 200ppm - 4x too loose against the real 50ppm compliance trip -
    # corrected here).
    _rule(
        "so2_out_emissions_excursion_v1",
        expression_type="threshold",
        params={"sensor_id": "SO2_out", "max": 50},
        severity="critical",
        diagnosis="Outlet SO2 exceeds 50ppm - emissions excursion, absorption performance degraded",
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
    # NEW: the register's absolute AT-01 trip (>2000ppm), distinct from the
    # statistical spike rule above - a sustained high reading with no
    # spike shape would previously raise nothing at all (AUDIT.md #1.1).
    _rule(
        "so2_in_high_absolute_v1",
        expression_type="threshold",
        params={"sensor_id": "SO2_in", "max": 2000},
        severity="critical",
        diagnosis="Inlet SO2 above 2000ppm - high boiler sulfur load, sustained excursion",
        suggested_part="Boiler fuel sulfur content / feed rate check",
        cooldown_s=600,
    ),
    # FEED tree 3.4, "product not cooling" branch, simplified: this
    # platform has no separate coolant-inlet/outlet delta sensor for
    # E-102, only the single process temp_C tag, so this fires on an
    # absolute high-temp threshold rather than a cooling-delta check.
    # Retuned to the top of the register's normal band (AUDIT.md #1.1/#1.2)
    # and paired with a new critical hard-trip tier below. Kept as the
    # SAME rule name/id as the original single-tier rule (rather than
    # renamed) because historical alarms in the `alarms` table already
    # reference this rule_id via a FK - renaming would mean deleting a
    # row still referenced by real alarm history, which Postgres (rightly)
    # refuses. This alarm is advisory only - it does not itself drive the
    # bypass damper; if that interlock exists at the PLC/edge layer it is
    # independent of and in addition to this rule.
    _rule(
        "product_loop_overtemp_v1",
        expression_type="threshold",
        params={"sensor_id": "temp_C", "max": 65},
        severity="warning",
        diagnosis="Product loop temperature above 65C - top of normal band, watch for E-102 fouling",
        suggested_part="E-102 heat exchanger cleaning / coolant supply check",
        cooldown_s=600,
    ),
    _rule(
        "product_loop_overtemp_hard_trip_v1",
        expression_type="threshold",
        params={"sensor_id": "temp_C", "max": 70},
        severity="critical",
        diagnosis="Product loop temperature at/above 70C - register HARD TRIP threshold, bypass damper interlock expected",
        suggested_part="E-102 heat exchanger cleaning / coolant supply check - verify bypass damper actuated",
        cooldown_s=600,
    ),
    # NEW: register's K2SO3 tote changeout trip (>900L), previously
    # unimplemented (AUDIT.md #1.1 - "no rule"). 90% assumes the 1000L
    # tote capacity already documented in this tag's `location` field in
    # frontend/lib/types.ts.
    _rule(
        "k2so3_tank_full_v1",
        expression_type="threshold",
        params={"sensor_id": "level_K2SO3_tank", "max": 90},
        severity="warning",
        diagnosis="K2SO3 product tank at/above 90% (~900L of a 1000L tote) - due for changeout",
        suggested_part="Driver dispatch / tote changeout",
        cooldown_s=900,
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
    inserted, updated = 0, 0
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
                    ON CONFLICT (rule_id) DO UPDATE SET
                        expression_type = EXCLUDED.expression_type,
                        params = EXCLUDED.params,
                        severity = EXCLUDED.severity,
                        diagnosis = EXCLUDED.diagnosis,
                        suggested_part = EXCLUDED.suggested_part,
                        cooldown_s = EXCLUDED.cooldown_s
                    RETURNING rule_id, (xmax = 0) AS was_insert
                    """
                ),
                {**rule, "params": json.dumps(rule["params"])},
            )
            row = result.first()
            if row is not None and row.was_insert:
                inserted += 1
                print(f"[seed_fault_tree_rules] inserted {rule['rule_id']}")
            else:
                updated += 1

    print(f"[seed_fault_tree_rules] done: {inserted} inserted, {updated} synced (already present)")


if __name__ == "__main__":
    main()
