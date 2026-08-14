"""--mock data generation: realistic sinusoidal process values per sensor
kind, plus injected faults (dropouts / spikes / frozen values) and a couple
of simulated VFD setpoint registers.

This stands in for the real Modbus poll path (pymodbus) until there is
actual hardware to talk to. `RealModbusPoller` (not implemented - no field
hardware in this environment) would produce the exact same
`(value, quality_flag)` shape so daemon.py's Poller task doesn't care which
one is wired in.
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from edge.manifest import SensorSpec
from shared import quality as q

# baseline, amplitude, noise-stddev, oscillation-period(s), by sensor `kind`
_PROFILES: Dict[str, Tuple[float, float, float, float]] = {
    "SO2_in": (1500.0, 400.0, 30.0, 240.0),
    "SO2_out": (120.0, 40.0, 5.0, 240.0),
    "pH": (7.0, 0.6, 0.05, 300.0),
    "temperature": (55.0, 8.0, 0.5, 180.0),
    "level": (60.0, 15.0, 1.0, 360.0),
    "flow": (250.0, 50.0, 5.0, 120.0),
}
_DEFAULT_PROFILE = (100.0, 20.0, 2.0, 200.0)

# Fault injection probabilities, evaluated per read per sensor.
DROPOUT_PROB = 0.03
SPIKE_PROB = 0.02
FREEZE_START_PROB = 0.004
FREEZE_MIN_S, FREEZE_MAX_S = 15.0, 45.0


@dataclass
class _SensorState:
    phase: float
    frozen_until: Optional[float] = None
    frozen_value: Optional[float] = None
    last_good_value: Optional[float] = None


class MockSensorSource:
    """Generates realistic values + injected faults for one plant's sensor
    manifest. Deterministic-ish (seeded) so gate-script runs are reproducible
    enough to reason about, but not literally deterministic across time
    since it's driven by wall-clock time.
    """

    def __init__(self, sensors: List[SensorSpec], seed: Optional[int] = None):
        self._sensors = {s.sensor_id: s for s in sensors}
        self._rng = random.Random(seed)
        self._state: Dict[str, _SensorState] = {
            s.sensor_id: _SensorState(phase=self._rng.uniform(0, 2 * math.pi))
            for s in sensors
        }
        self._start = time.time()

    def sensor_ids(self) -> List[str]:
        return list(self._sensors.keys())

    def read(self, sensor_id: str, now: Optional[float] = None) -> Tuple[Optional[float], int]:
        """Returns (value, quality_flag_int). value is None only on a
        comm-error read (nothing came back), matching what a real Modbus
        timeout would look like."""
        now = now if now is not None else time.time()
        spec = self._sensors[sensor_id]
        st = self._state[sensor_id]
        baseline, amp, noise, period = _PROFILES.get(spec.kind, _DEFAULT_PROFILE)

        # Currently frozen: hold the stuck value until frozen_until elapses.
        if st.frozen_until is not None:
            if now < st.frozen_until:
                return st.frozen_value, q.FROZEN
            st.frozen_until = None
            st.frozen_value = None

        clean_value = baseline + amp * math.sin(2 * math.pi * (now - self._start) / period + st.phase)
        clean_value += self._rng.gauss(0, noise)
        st.last_good_value = clean_value

        roll = self._rng.random()
        if roll < DROPOUT_PROB:
            return None, q.COMM_ERROR
        roll -= DROPOUT_PROB
        if roll < SPIKE_PROB:
            spike = 9999.0 if self._rng.random() < 0.8 else -9999.0
            return spike, q.OUT_OF_RANGE
        roll -= SPIKE_PROB
        if roll < FREEZE_START_PROB:
            st.frozen_until = now + self._rng.uniform(FREEZE_MIN_S, FREEZE_MAX_S)
            st.frozen_value = clean_value
            return clean_value, q.FROZEN

        return clean_value, q.GOOD


# ---------------------------------------------------------------------------
# Simulated VFD setpoint registers
# ---------------------------------------------------------------------------

SETPOINT_CHANGE_PROB = 0.01  # per poll cycle, per register


@dataclass
class _SetpointReg:
    device: str
    register: str
    value: float
    step: float
    lo: float
    hi: float


class MockSetpointSource:
    """Simulates a couple of VFD speed setpoints that occasionally get
    nudged by "the API" (source='api' per spec - i.e. not a manual panel
    edit). Emits a change event only when the value actually deltas."""

    def __init__(self, seed: Optional[int] = None):
        self._rng = random.Random(seed)
        self._regs = [
            _SetpointReg("VFD1", "speed_hz", value=45.0, step=2.5, lo=20.0, hi=60.0),
            _SetpointReg("VFD2", "speed_hz", value=38.0, step=2.5, lo=20.0, hi=60.0),
        ]

    def poll(self) -> List[dict]:
        """Returns zero or more setpoint-change dicts for this poll cycle."""
        changes = []
        for reg in self._regs:
            if self._rng.random() >= SETPOINT_CHANGE_PROB:
                continue
            old = reg.value
            delta = reg.step * self._rng.choice([-1, 1])
            new = max(reg.lo, min(reg.hi, old + delta))
            if new == old:
                continue
            reg.value = new
            changes.append(
                {
                    "device": reg.device,
                    "register": reg.register,
                    "old_value": f"{old:.2f}",
                    "new_value": f"{new:.2f}",
                    "source": "api",
                }
            )
        return changes
