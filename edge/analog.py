"""Generic 4-20mA current-loop-to-engineering-unit conversion.

This is a pure, hardware-independent utility - it has no idea which
physical device (if any) actually produces a 4-20mA signal on this plant,
because that depends on the Waveshare analog module's own register
scaling behavior, which is still unconfirmed (see edge/modbus_map.json's
_comment_o2 - we don't have that module's datasheet yet). It may turn out
the module already returns a pre-scaled engineering value in its holding
register, in which case this conversion is unnecessary for the O2 sensor
specifically. This module exists so the conversion is ready, tested, and
correct the moment a raw-current register is confirmed - not to claim any
specific sensor uses it yet.

Standard 4-20mA convention: 4.0mA = engineering_min, 20.0mA =
engineering_max, linear in between. Fault conditions (open circuit,
short circuit, out-of-range) are reported via a quality flag rather than
silently clamped into a plausible-looking number - a clamped fault value
is indistinguishable from a real reading at the far end of range, which
defeats the entire point of fault detection on a current loop.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from shared import quality as q

# Thresholds per the common 4-20mA convention (e.g. NAMUR NE43): a small
# margin below 4mA and above 20mA is normal sensor tolerance, not a fault.
# Genuinely near 0mA or far above 20mA indicates a wiring problem, not a
# process value.
UNDER_RANGE_MA = 3.6
OVER_RANGE_MA = 21.0
OPEN_CIRCUIT_MA = 0.1  # at/near 0mA - loop is broken, not "reading zero"
SHORT_CIRCUIT_MA = 22.0  # well past even the over-range fault band


@dataclass
class AnalogReading:
    engineering_value: Optional[float]
    quality_flag: int
    raw_ma: float


def convert_4_20ma(
    current_ma: float,
    engineering_min: float,
    engineering_max: float,
) -> AnalogReading:
    """Converts a raw loop current (mA) to an engineering-unit value using
    the standard linear 4-20mA mapping, with fault detection. Does NOT
    clamp out-of-range or fault currents into a plausible-looking
    in-range value - engineering_value is None whenever the current
    itself indicates a hardware fault (open/short circuit), since a
    number there would look like a real reading."""
    if current_ma <= OPEN_CIRCUIT_MA:
        return AnalogReading(None, q.COMM_ERROR, current_ma)
    if current_ma >= SHORT_CIRCUIT_MA:
        return AnalogReading(None, q.COMM_ERROR, current_ma)

    engineering_value = engineering_min + (
        (current_ma - 4.0) / 16.0
    ) * (engineering_max - engineering_min)

    if current_ma < UNDER_RANGE_MA or current_ma > OVER_RANGE_MA:
        # Still a real, computed value (not None) - the loop is
        # electrically fine, the PROCESS value is just outside the
        # sensor's rated span. Flagged, not hidden.
        return AnalogReading(engineering_value, q.OUT_OF_RANGE, current_ma)

    return AnalogReading(engineering_value, q.GOOD, current_ma)
