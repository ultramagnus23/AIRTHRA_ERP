#!/usr/bin/env python
"""Edge daemon unit-logic gate.

Pure-logic checks for edge/ code that needs zero hardware, zero network,
and zero database - the 4-20mA conversion math, its fault-detection
thresholds, and the HARDWARE_MODE/mock resolution rules. These are exactly
the pieces that are cheap to get wrong silently (an off-by-one in a
threshold, a clamp where a fault should have been reported instead), so
they get real assertions instead of only being exercised implicitly by
whichever sensors happen to be wired up.

This does NOT replace edge/test_real_pollers.py, which is a physical
wiring check against actual hardware - this is the opposite: logic that
must be correct with NO hardware attached at all.

Prints a clear PASS/FAIL per check and exits non-zero if anything fails.
Run from the repo root: `python tests/edge_unit_gate.py`
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from edge.analog import convert_4_20ma  # noqa: E402
from shared import quality as q  # noqa: E402

results = []  # (name, bool)


def check(name: str, condition: bool) -> None:
    results.append((name, condition))
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")


# --- 4-20mA conversion: the documented linear mapping ---
r = convert_4_20ma(4.0, 0.0, 100.0)
check("4.0mA -> engineering_min (0.0) exactly", r.engineering_value == 0.0 and r.quality_flag == q.GOOD)

r = convert_4_20ma(20.0, 0.0, 100.0)
check("20.0mA -> engineering_max (100.0) exactly", r.engineering_value == 100.0 and r.quality_flag == q.GOOD)

r = convert_4_20ma(12.0, 0.0, 100.0)
check("12.0mA (midpoint) -> 50.0 exactly", r.engineering_value == 50.0 and r.quality_flag == q.GOOD)

r = convert_4_20ma(4.0, 1.0, 25.0)
check("non-zero engineering_min respected (4.0mA -> 1.0)", r.engineering_value == 1.0)

r = convert_4_20ma(20.0, 1.0, 25.0)
check("non-zero engineering_min respected (20.0mA -> 25.0)", r.engineering_value == 25.0)

# --- Fault detection: must NOT silently clamp into a plausible value ---
r = convert_4_20ma(0.0, 0.0, 100.0)
check("0.0mA (open circuit) -> engineering_value is None, not clamped to min",
      r.engineering_value is None and r.quality_flag == q.COMM_ERROR)

r = convert_4_20ma(25.0, 0.0, 100.0)
check("25.0mA (short circuit) -> engineering_value is None, not clamped to max",
      r.engineering_value is None and r.quality_flag == q.COMM_ERROR)

r = convert_4_20ma(3.0, 0.0, 100.0)
check("3.0mA (under-range, not open) -> real computed value, flagged OUT_OF_RANGE",
      r.engineering_value is not None and r.quality_flag == q.OUT_OF_RANGE)

r = convert_4_20ma(21.5, 0.0, 100.0)
check("21.5mA (over-range, not short) -> real computed value, flagged OUT_OF_RANGE",
      r.engineering_value is not None and r.quality_flag == q.OUT_OF_RANGE)

r = convert_4_20ma(3.6, 0.0, 100.0)
check("3.6mA (exactly at under-range boundary) -> GOOD, not flagged", r.quality_flag == q.GOOD)

r = convert_4_20ma(21.0, 0.0, 100.0)
check("21.0mA (exactly at over-range boundary) -> GOOD, not flagged", r.quality_flag == q.GOOD)

# --- HARDWARE_MODE / mock resolution (edge/config.py) ---
os.environ.pop("HARDWARE_MODE", None)
from edge.config import EdgeConfig  # noqa: E402

cfg = EdgeConfig(plant_id="gate_test")
check("default HARDWARE_MODE is 'real'", cfg.hardware_mode == "real")
check("default mock is False (production must attempt real hardware)", cfg.mock is False)

os.environ["HARDWARE_MODE"] = "mock"
cfg2 = EdgeConfig(plant_id="gate_test")
check("HARDWARE_MODE=mock forces mock=True even without --mock", cfg2.mock is True)

os.environ["HARDWARE_MODE"] = "replay"
try:
    EdgeConfig(plant_id="gate_test")
    check("HARDWARE_MODE=replay fails clearly (not silently ignored)", False)
except SystemExit:
    check("HARDWARE_MODE=replay fails clearly (not silently ignored)", True)

os.environ["HARDWARE_MODE"] = "not_a_real_mode"
try:
    EdgeConfig(plant_id="gate_test")
    check("invalid HARDWARE_MODE value fails clearly", False)
except SystemExit:
    check("invalid HARDWARE_MODE value fails clearly", True)

os.environ.pop("HARDWARE_MODE", None)

print()
passed = sum(1 for _, ok in results if ok)
print(f"EDGE UNIT GATE: {'PASS' if passed == len(results) else 'FAIL'} ({passed}/{len(results)} checks passed)")
sys.exit(0 if passed == len(results) else 1)
