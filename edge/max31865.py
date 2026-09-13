"""Real MAX31865 SPI RTD amplifier driver for the two PT100 probes
(TE-08 FFE feed temp, TE-09 FFE lean solvent temp) - wiring confirmed
2026-09-13 from the Delhi engineer's schematic, Sheet 5:

  VIN -> 3.3V (Pin 1)       GND -> Pin 9
  SCK -> Pin 23 (SPI SCLK)  SDI -> Pin 19 (SPI MOSI)   SDO -> Pin 21 (SPI MISO)
  Board 1 (TE-08) CS -> Pin 24 (SPI CE0, /dev/spidev0.0)
  Board 2 (TE-09) CS -> Pin 26 (SPI CE1, /dev/spidev0.1)

Uses `spidev` (Linux SPI userspace driver) - Pi/Linux-only, not
installable on this Windows dev machine, so only the resistance->
temperature math and fault-byte decoding below are unit-tested (see
tests/edge_unit_gate.py); the actual SPI transaction has NOT been
exercised against real hardware in this session.

NOT YET CONFIRMED, do not guess further than what's below: the
reference resistor value (R_REF) on these specific boards - 430 ohm is
the common default for PT100 3-wire MAX31865 breakouts, used here as a
placeholder default, but the actual value should be read off the board
(printed near the resistor, or measured) and set per-probe in
edge/max31865_map.json rather than trusted blindly.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from edge.manifest import SensorSpec
from shared import quality as q

if TYPE_CHECKING:
    pass

log = logging.getLogger("edge.max31865")

# --- Register map (MAX31865 datasheet) ---
_REG_CONFIG = 0x00
_REG_RTD_MSB = 0x01
_REG_FAULT_STATUS = 0x07
_WRITE_BIT = 0x80

# Config byte written once at startup: Vbias on (bit7), 1-shot off /
# auto-conversion mode off (bit6=0, using normally-on Vbias + manual
# 1-shot per read instead - simpler and avoids self-heating between
# reads), 3-wire (bit4=1 - THESE PROBES ARE "Class A, SS316, 2m" per the
# BOM but wire count (2/3/4-wire) isn't stated; 3-wire is the common
# industrial default and what this assumes - TODO confirm against the
# actual probe/board wiring if readings look consistently offset),
# fault detection cycle bits left default, 50/60Hz filter bit0=0 (60Hz).
_CONFIG_BYTE = 0b10010000

# Callendar-Van Dusen coefficients for standard PT100 (IEC 60751, alpha
# = 0.00385). The quadratic solved below is exact for T >= 0 degC; below
# 0 degC IEC 60751 adds a cubic correction term this does NOT include,
# so sub-zero readings here are a close approximation, not exact - these
# probes' expected range (stripper feed/solvent) is well above 0 degC in
# normal operation, so this is unlikely to matter, but is worth knowing.
_CVD_A = 3.9083e-3
_CVD_B = -5.775e-7


def resistance_to_celsius(ohms: float, r0: float = 100.0) -> float:
    """PT100 resistance (ohms) -> temperature (degC) via the Callendar-Van
    Dusen quadratic, T >= 0 branch. r0 is the RTD's nominal resistance at
    0 degC (100.0 for PT100, the standard here per the BOM)."""
    discriminant = _CVD_A ** 2 - 4 * _CVD_B * (1 - ohms / r0)
    return (-_CVD_A + discriminant ** 0.5) / (2 * _CVD_B)


def raw_to_resistance(raw15: int, r_ref: float) -> float:
    """raw15: the 15-bit RTD ADC code (register value with the fault bit
    already stripped). Standard MAX31865 formula: R_RTD = (ADC * R_REF) / 32768."""
    return (raw15 * r_ref) / 32768.0


# Fault Status register bit -> human description (MAX31865 datasheet,
# Table 4). All faults map to shared.quality.COMM_ERROR (not a distinct
# SENSOR_FAULT code) since the current `readings.quality_flag` CHECK
# constraint only has 5 values (good/comm_error/out_of_range/frozen/
# imputed) - adding a dedicated fault-quality vocabulary needs its own
# migration, deliberately not rushed in here. The human-readable fault
# description is still logged, so nothing is lost except a dedicated
# quality-code distinction in the database.
_FAULT_BITS = {
    0x80: "RTD High Threshold exceeded",
    0x40: "RTD Low Threshold exceeded",
    0x20: "REFIN- > 0.85x VBIAS (reference resistor fault/open)",
    0x10: "REFIN- < 0.85x VBIAS (FORCE- open)",
    0x08: "RTDIN- < 0.85x VBIAS (RTD open circuit)",
    0x04: "Overvoltage/undervoltage fault",
}


def decode_faults(fault_byte: int) -> List[str]:
    return [desc for bit, desc in _FAULT_BITS.items() if fault_byte & bit]


class MAX31865ProbeMap:
    def __init__(self, cs: int, r_ref: float = 430.0, r0: float = 100.0):
        self.cs = cs  # 0 = CE0 (/dev/spidev0.0), 1 = CE1 (/dev/spidev0.1)
        self.r_ref = r_ref
        self.r0 = r0


def load_max31865_map(path: Path) -> Dict[str, MAX31865ProbeMap]:
    """{sensor_id: {"cs": 0, "r_ref": 430.0}} - cs is which of the Pi's
    two hardware chip-selects the board's CS pin is wired to (0=CE0=pin24,
    1=CE1=pin26, per this module's docstring). r_ref/r0 are optional,
    defaulting to the common 430 ohm reference / PT100 100 ohm nominal."""
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        sensor_id: MAX31865ProbeMap(**cfg)
        for sensor_id, cfg in data.items()
        if not sensor_id.startswith("_")
    }


class RealMAX31865Poller:
    """Matches the CompositeSensorSource poller interface (sensor_ids(),
    async read(), close()) - see edge/mockgen.py's real pollers for the
    same shape. One spidev.SpiDev handle per configured chip-select,
    opened lazily on first use."""

    def __init__(self, sensors: List[SensorSpec], probe_map: Dict[str, MAX31865ProbeMap]):
        self._sensors = {s.sensor_id: s for s in sensors}
        self._map = probe_map
        missing = set(self._sensors) - set(self._map)
        if missing:
            raise ValueError(f"no MAX31865 mapping for sensors: {sorted(missing)}")
        self._spi_handles: Dict[int, object] = {}

    def sensor_ids(self) -> List[str]:
        return list(self._sensors.keys())

    async def _handle_for(self, cs: int):
        if cs not in self._spi_handles:
            import spidev  # Linux-only, lazy import - see module docstring

            spi = spidev.SpiDev()
            await asyncio.to_thread(spi.open, 0, cs)
            spi.max_speed_hz = 500_000
            spi.mode = 0b01  # MAX31865 requires SPI mode 1 (CPOL=0, CPHA=1)
            await asyncio.to_thread(spi.xfer2, [_WRITE_BIT | _REG_CONFIG, _CONFIG_BYTE])
            self._spi_handles[cs] = spi
        return self._spi_handles[cs]

    async def read(self, sensor_id: str) -> Tuple[Optional[float], int]:
        spec = self._sensors[sensor_id]
        probe = self._map[sensor_id]

        try:
            spi = await self._handle_for(probe.cs)
        except Exception:
            log.warning("max31865: could not open SPI CE%d for %s", probe.cs, sensor_id)
            return None, q.COMM_ERROR

        try:
            # Read RTD MSB+LSB (2 bytes) starting at 0x01, then fault
            # status (0x07) as a separate transaction - matches the
            # datasheet's recommended read sequence.
            rtd_bytes = await asyncio.to_thread(spi.xfer2, [_REG_RTD_MSB, 0x00, 0x00])
            fault_byte = (await asyncio.to_thread(spi.xfer2, [_REG_FAULT_STATUS, 0x00]))[1]
        except Exception:
            log.warning("max31865: SPI transaction failed for %s (CE%d)", sensor_id, probe.cs)
            return None, q.COMM_ERROR

        raw16 = (rtd_bytes[1] << 8) | rtd_bytes[2]
        fault_bit_set = raw16 & 0x0001
        raw15 = raw16 >> 1

        if fault_bit_set or fault_byte:
            faults = decode_faults(fault_byte) or ["fault bit set, no status bits (transient?)"]
            log.warning("max31865: fault on %s (CE%d): %s", sensor_id, probe.cs, "; ".join(faults))
            return None, q.COMM_ERROR

        ohms = raw_to_resistance(raw15, probe.r_ref)
        try:
            value = resistance_to_celsius(ohms, probe.r0)
        except ValueError:
            # Negative discriminant - resistance outside anything a real
            # PT100 could report (wiring/r_ref misconfiguration).
            log.warning("max31865: resistance %.2f ohm for %s is not a valid PT100 value "
                        "(check r_ref/r0 in edge/max31865_map.json)", ohms, sensor_id)
            return None, q.COMM_ERROR

        if spec.min_valid is not None and value < spec.min_valid:
            return value, q.OUT_OF_RANGE
        if spec.max_valid is not None and value > spec.max_valid:
            return value, q.OUT_OF_RANGE
        return value, q.GOOD

    async def close(self) -> None:
        for spi in self._spi_handles.values():
            try:
                spi.close()
            except Exception:
                pass
