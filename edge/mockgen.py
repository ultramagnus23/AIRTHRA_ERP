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

import asyncio
import json
import logging
import math
import random
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Deque, Dict, List, Optional, Tuple

from edge.manifest import SensorSpec
from shared import quality as q

log = logging.getLogger("edge.mockgen")

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


# ---------------------------------------------------------------------------
# Real hardware pollers (swap-in point — see module docstring and daemon.py:459)
# ---------------------------------------------------------------------------
#
# Three sensor buses per the plant BOM: two RS-485/Modbus buses
# (RealModbusPoller), one 1-Wire bus of DS18B20 probes on GPIO4
# (RealOneWirePoller), and a PMS7003 dust sensor on UART
# (RealPMS7003Poller). Since daemon.py wants a single sensor_source object,
# CompositeSensorSource (bottom of this section) fans reads out to whichever
# of the three owns a given sensor_id.
#
# None of this is wired into daemon.py yet. To go live:
#   1. Fill in edge/modbus_map.json, edge/onewire_map.json and
#      edge/pms7003_map.json (see the load_*_map functions below) with the
#      real wiring for every sensor_id in the manifest.
#   2. In daemon.py main_async(): replace
#        sensor_source = MockSensorSource(sensors)
#      with something like
#        sensor_source = CompositeSensorSource([
#            RealModbusPoller(modbus_sensors, load_modbus_map(...)),
#            RealOneWirePoller(onewire_sensors, load_onewire_map(...)),
#            RealPMS7003Poller(pms_sensors, load_pms7003_map(...)),
#        ])
#        await sensor_source.start()
#      (splitting `sensors` three ways by which map claims each sensor_id),
#      drop the `if not cfg.mock: raise SystemExit(...)` guard, and call
#      `await sensor_source.close()` during shutdown (finally: block, next
#      to ctx.buffer.close()).
#   3. All three real pollers' read() are async (real I/O blocks; the mock
#      read is instant), so _mock_read()'s sync call in daemon.py:192-197
#      needs to become `await sensor_source.read(sensor_id)` directly
#      instead of wrapping a sync function — the asyncio.wait_for timeout
#      budget around it stays exactly as-is either way.


@dataclass
class ModbusRegisterMap:
    """Wiring for one sensor's Modbus register.

    The Postgres `sensors` table (see edge/manifest.py SensorSpec) only
    carries process metadata (tag/kind/unit/valid range) — it has no wiring
    columns. Rather than a schema migration up front, wiring lives in a
    small local JSON file per bus map below; fold it into a
    `sensors.modbus_config jsonb` column later if/when it needs to be
    editable from the platform UI instead of a file on the Pi.
    """

    bus: str  # e.g. "/dev/ttyUSB0" or "/dev/ttyUSB1" (two RS-485 buses per BOM)
    slave_id: int
    register: int
    register_type: str = "holding"  # "holding" | "input"
    count: int = 1  # 1 = single 16-bit register, 2 = 32-bit value across two
    datatype: str = "int16"  # "int16" | "uint16" | "float32" | "int32"
    scale: float = 1.0
    offset: float = 0.0
    word_order: str = "big"  # only relevant when count == 2


def load_modbus_map(path: Path) -> Dict[str, ModbusRegisterMap]:
    """Loads {sensor_id: ModbusRegisterMap} from a JSON file shaped like:
    {
      "SO2_out_01": {"bus": "/dev/ttyUSB0", "slave_id": 3, "register": 40001,
                      "register_type": "holding", "datatype": "float32",
                      "count": 2, "scale": 1.0},
      "temp_reactor_01": {"bus": "/dev/ttyUSB1", "slave_id": 1, "register": 0,
                           "datatype": "int16", "scale": 0.1}
    }
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        sensor_id: ModbusRegisterMap(**cfg)
        for sensor_id, cfg in data.items()
        if not sensor_id.startswith("_")
    }


class RealModbusPoller:
    """Real-hardware equivalent of MockSensorSource: same (value,
    quality_flag) return shape (see shared/quality.py), so daemon.py's
    Poller task doesn't care which one is wired in.

    One AsyncModbusSerialClient per RS-485 bus, opened lazily and reused
    across reads — reconnecting per read would blow the ~1s poll cycle
    budget once both buses' sensors are counted.
    """

    def __init__(
        self,
        sensors: List[SensorSpec],
        register_map: Dict[str, ModbusRegisterMap],
        baudrate: int = 9600,
    ):
        self._sensors = {s.sensor_id: s for s in sensors}
        self._map = register_map
        missing = set(self._sensors) - set(self._map)
        if missing:
            raise ValueError(f"no Modbus register mapping for sensors: {sorted(missing)}")
        self._baudrate = baudrate
        self._clients: Dict[str, object] = {}
        self._bus_locks: Dict[str, asyncio.Lock] = {}

    def sensor_ids(self) -> List[str]:
        return list(self._sensors.keys())

    async def _client_for(self, bus: str):
        # Imported lazily so importing this module (e.g. for --mock runs)
        # never requires pymodbus's serial backend to be installed/working.
        from pymodbus.client import AsyncModbusSerialClient

        if bus not in self._clients:
            self._clients[bus] = AsyncModbusSerialClient(
                bus, baudrate=self._baudrate, timeout=1.0
            )
            self._bus_locks[bus] = asyncio.Lock()
        client = self._clients[bus]
        if not client.connected:
            await client.connect()
        return client

    async def read(self, sensor_id: str) -> Tuple[Optional[float], int]:
        """Async — real serial I/O blocks, unlike MockSensorSource.read().
        Callers must await this directly rather than wrapping it as sync."""
        reg = self._map[sensor_id]
        spec = self._sensors[sensor_id]

        try:
            client = await self._client_for(reg.bus)
        except Exception:
            log.warning("modbus: connect failed for bus %s (sensor %s)", reg.bus, sensor_id)
            return None, q.COMM_ERROR

        async with self._bus_locks[reg.bus]:
            try:
                if reg.register_type == "holding":
                    result = await client.read_holding_registers(
                        reg.register, count=reg.count, slave=reg.slave_id
                    )
                else:
                    result = await client.read_input_registers(
                        reg.register, count=reg.count, slave=reg.slave_id
                    )
            except Exception:
                log.warning("modbus: read failed for %s (bus=%s slave=%d reg=%d)",
                            sensor_id, reg.bus, reg.slave_id, reg.register)
                return None, q.COMM_ERROR

        if result.isError():
            return None, q.COMM_ERROR

        try:
            raw = self._decode(result.registers, reg)
        except Exception:
            log.warning("modbus: decode failed for %s (raw=%r)", sensor_id, result.registers)
            return None, q.COMM_ERROR

        value = raw * reg.scale + reg.offset

        if spec.min_valid is not None and value < spec.min_valid:
            return value, q.OUT_OF_RANGE
        if spec.max_valid is not None and value > spec.max_valid:
            return value, q.OUT_OF_RANGE
        return value, q.GOOD

    @staticmethod
    def _decode(registers: List[int], reg: ModbusRegisterMap) -> float:
        if reg.count == 1:
            return float(registers[0])

        from pymodbus.client.mixin import ModbusClientMixin

        datatype = {
            "float32": ModbusClientMixin.DATATYPE.FLOAT32,
            "int32": ModbusClientMixin.DATATYPE.INT32,
            "uint32": ModbusClientMixin.DATATYPE.UINT32,
        }.get(reg.datatype)
        if datatype is None:
            raise ValueError(f"unsupported multi-register datatype: {reg.datatype!r}")
        return ModbusClientMixin.convert_from_registers(
            registers, datatype, word_order=reg.word_order
        )

    async def close(self) -> None:
        for client in self._clients.values():
            client.close()


# ---------------------------------------------------------------------------
# RealOneWirePoller — DS18B20 probes on the Pi's 1-Wire bus
# ---------------------------------------------------------------------------


@dataclass
class OneWireDeviceMap:
    """Wiring for one DS18B20 probe."""

    device_id: str  # ROM id as it appears under /sys/bus/w1/devices, e.g. "28-000005e3d3ff"


def load_onewire_map(path: Path) -> Dict[str, OneWireDeviceMap]:
    """Loads {sensor_id: OneWireDeviceMap} from a JSON file shaped like:
    {"temp_reactor_01": {"device_id": "28-000005e3d3ff"}, ...}
    Find each probe's ROM id with `ls /sys/bus/w1/devices` after enabling
    the w1-gpio/w1-therm overlays (dtoverlay=w1-gpio in /boot/config.txt,
    GPIO4 by default) — DS18B20s have no address pins, so with 15 of them
    on one bus, ROM id is the only way to tell which probe is which; label
    physically as you wire each one and read its id before moving to the next.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        sensor_id: OneWireDeviceMap(**cfg)
        for sensor_id, cfg in data.items()
        if not sensor_id.startswith("_")
    }


# Consecutive identical readings before a DS18B20 probe is flagged FROZEN
# rather than GOOD. DS18B20 has no internal "value didn't update" signal
# like a Modbus comm timeout would - a wire that's shorted, a probe that's
# died mid-bus, or a kernel driver returning a stale cached conversion all
# look identical to a real, stable temperature unless we watch for a run of
# exact repeats. 5 reads (~5 poll cycles at the default 1s interval) is long
# enough that a genuinely stable process value would still just look GOOD
# most of the time (real process temperatures drift by noise/quantization
# almost every cycle), while a stuck sensor gets caught within a few seconds.
ONEWIRE_FREEZE_STUCK_READS = 5


@dataclass
class _OneWireState:
    history: Deque[float] = field(default_factory=lambda: deque(maxlen=ONEWIRE_FREEZE_STUCK_READS))


class RealOneWirePoller:
    """Real-hardware equivalent of MockSensorSource for DS18B20 probes. Same
    (value, quality_flag) shape (see shared/quality.py).

    Reads straight from the kernel's sysfs interface
    (/sys/bus/w1/devices/<rom_id>/w1_slave) rather than a third-party
    library — the w1-therm driver already does the temperature conversion,
    so there's nothing a library adds here except a dependency. Each read
    triggers a fresh ~750ms conversion in the kernel driver, which blocks,
    so it's pushed into a thread via asyncio.to_thread to avoid stalling the
    event loop the Modbus/PMS7003 pollers share.
    """

    def __init__(
        self,
        sensors: List[SensorSpec],
        device_map: Dict[str, OneWireDeviceMap],
        w1_base_dir: Path = Path("/sys/bus/w1/devices"),
    ):
        self._sensors = {s.sensor_id: s for s in sensors}
        self._map = device_map
        missing = set(self._sensors) - set(self._map)
        if missing:
            raise ValueError(f"no 1-Wire device mapping for sensors: {sorted(missing)}")
        self._w1_base = w1_base_dir
        self._state: Dict[str, _OneWireState] = {sid: _OneWireState() for sid in self._sensors}

    def sensor_ids(self) -> List[str]:
        return list(self._sensors.keys())

    async def read(self, sensor_id: str) -> Tuple[Optional[float], int]:
        spec = self._sensors[sensor_id]
        device_id = self._map[sensor_id].device_id

        try:
            value = await asyncio.to_thread(self._read_sync, device_id)
        except FileNotFoundError:
            # The device's sysfs entry doesn't exist at all - wrong/typo'd
            # ROM id in onewire_map.json, the probe fell off the bus, or the
            # w1-gpio/w1-therm overlays aren't loaded yet.
            log.warning("onewire: device %s not found for %s (bad ROM id, or probe offline)",
                        device_id, sensor_id)
            return None, q.COMM_ERROR
        except Exception:
            log.warning("onewire: read failed for %s (device=%s)", sensor_id, device_id)
            return None, q.COMM_ERROR

        if value is None:
            # CRC failed or the sysfs file was malformed - a real read
            # happened but produced garbage, same signal as a comm timeout.
            return None, q.COMM_ERROR

        if spec.min_valid is not None and value < spec.min_valid:
            return value, q.OUT_OF_RANGE
        if spec.max_valid is not None and value > spec.max_valid:
            return value, q.OUT_OF_RANGE

        st = self._state[sensor_id]
        st.history.append(value)
        if len(st.history) == st.history.maxlen and len(set(st.history)) == 1:
            return value, q.FROZEN
        return value, q.GOOD

    def _read_sync(self, device_id: str) -> Optional[float]:
        raw = (self._w1_base / device_id / "w1_slave").read_text(encoding="ascii")
        lines = raw.strip().splitlines()
        # First line ends "YES" only if the CRC check passed - "NO" means a
        # corrupted read (bus noise, loose wiring on a 15-probe daisy chain).
        if len(lines) < 2 or not lines[0].strip().endswith("YES"):
            return None
        idx = lines[1].find("t=")
        if idx == -1:
            return None
        millidegrees = int(lines[1][idx + 2:])
        return millidegrees / 1000.0

    async def close(self) -> None:
        pass  # nothing to release - stateless sysfs reads


# ---------------------------------------------------------------------------
# RealPMS7003Poller — dust/PM sensor on UART
# ---------------------------------------------------------------------------


@dataclass
class PMS7003Channel:
    """Wiring for one PM metric read off a PMS7003 unit."""

    device: str  # serial port, e.g. "/dev/ttyAMA0" or "/dev/ttyUSB2"
    metric: str  # "pm1_0" | "pm2_5" | "pm10" (atmospheric-environment values)


def load_pms7003_map(path: Path) -> Dict[str, PMS7003Channel]:
    """Loads {sensor_id: PMS7003Channel} from a JSON file shaped like:
    {"pm2_5_stack": {"device": "/dev/ttyAMA0", "metric": "pm2_5"}, ...}
    One PMS7003 unit produces several metrics, so several sensor_ids in the
    manifest can point at the same `device` with a different `metric`.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        sensor_id: PMS7003Channel(**cfg)
        for sensor_id, cfg in data.items()
        if not sensor_id.startswith("_")
    }


class RealPMS7003Poller:
    """Real-hardware equivalent of MockSensorSource for PMS7003 dust
    sensors. Same (value, quality_flag) shape (see shared/quality.py).

    Unlike Modbus/1-Wire, the PMS7003 is not request/response: in its
    default active mode it pushes a 32-byte frame over UART roughly once a
    second, unprompted. So a background task per physical device
    continuously drains the serial buffer and caches the latest parsed
    frame; read() just serves whatever's cached (or COMM_ERROR if it's gone
    stale), rather than blocking the poll cycle on a fresh frame.

    Call `await start()` once after construction (spawns the background
    reader tasks) and `await close()` on shutdown.
    """

    _HEADER = b"\x42\x4d"
    _FRAME_LEN = 32
    # Byte offsets of the "atmospheric environment" PM concentrations
    # within the 32-byte frame (bytes 0-3 are header+length, so these start
    # at byte 10) - the CF=1 "standard particle" fields at bytes 4-9 are the
    # other common choice; atmospheric is what's normally reported as
    # ambient PM1.0/2.5/10 for air-quality purposes.
    _METRIC_OFFSETS = {"pm1_0": 10, "pm2_5": 12, "pm10": 14}

    def __init__(
        self,
        sensors: List[SensorSpec],
        channel_map: Dict[str, PMS7003Channel],
        baudrate: int = 9600,
        stale_after_s: float = 5.0,
    ):
        self._sensors = {s.sensor_id: s for s in sensors}
        self._map = channel_map
        missing = set(self._sensors) - set(self._map)
        if missing:
            raise ValueError(f"no PMS7003 channel mapping for sensors: {sorted(missing)}")
        for sensor_id, ch in self._map.items():
            if ch.metric not in self._METRIC_OFFSETS:
                raise ValueError(f"unknown PMS7003 metric {ch.metric!r} for {sensor_id}")
        self._baudrate = baudrate
        self._stale_after_s = stale_after_s
        # device -> (metrics dict, time.monotonic() at read)
        self._latest: Dict[str, Tuple[Dict[str, float], float]] = {}
        self._tasks: Dict[str, asyncio.Task] = {}
        self._serials: Dict[str, object] = {}

    def sensor_ids(self) -> List[str]:
        return list(self._sensors.keys())

    async def start(self) -> None:
        for device in {ch.device for ch in self._map.values()}:
            self._tasks[device] = asyncio.create_task(
                self._reader_loop(device), name=f"pms7003-{device}"
            )

    async def read(self, sensor_id: str) -> Tuple[Optional[float], int]:
        spec = self._sensors[sensor_id]
        ch = self._map[sensor_id]
        cached = self._latest.get(ch.device)
        if cached is None:
            return None, q.COMM_ERROR

        metrics, read_at = cached
        if time.monotonic() - read_at > self._stale_after_s:
            return None, q.COMM_ERROR

        value = metrics.get(ch.metric)
        if value is None:
            return None, q.COMM_ERROR
        if spec.min_valid is not None and value < spec.min_valid:
            return value, q.OUT_OF_RANGE
        if spec.max_valid is not None and value > spec.max_valid:
            return value, q.OUT_OF_RANGE
        return value, q.GOOD

    async def _reader_loop(self, device: str) -> None:
        while True:
            try:
                # Imported inside the loop/try, not at module or method top -
                # a missing pyserial install (or a bad port) should degrade
                # this device to permanent COMM_ERROR via the reconnect-retry
                # path below, not crash the task with an unretrieved
                # exception that silently stops readings forever.
                import serial  # pyserial - blocking API, everything below runs via to_thread

                ser = await asyncio.to_thread(serial.Serial, device, self._baudrate, timeout=2.0)
                self._serials[device] = ser
                try:
                    while True:
                        frame = await asyncio.to_thread(self._read_frame_sync, ser)
                        if frame is None:
                            continue  # resync attempt failed this iteration; keep trying
                        metrics = self._parse_frame(frame)
                        if metrics is not None:
                            self._latest[device] = (metrics, time.monotonic())
                finally:
                    ser.close()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.warning("pms7003: serial error on %s, reconnecting in 2s", device)
                await asyncio.sleep(2.0)

    @classmethod
    def _read_frame_sync(cls, ser) -> Optional[bytes]:
        # UART is a raw byte stream, not frame-aligned - scan one byte at a
        # time for the two header bytes before trusting the next 30 as a frame.
        first = ser.read(1)
        if first != cls._HEADER[0:1]:
            return None
        second = ser.read(1)
        if second != cls._HEADER[1:2]:
            return None
        rest = ser.read(cls._FRAME_LEN - 2)
        if len(rest) != cls._FRAME_LEN - 2:
            return None  # read timed out mid-frame
        return first + second + rest

    @classmethod
    def _parse_frame(cls, frame: bytes) -> Optional[Dict[str, float]]:
        checksum = sum(frame[:30])
        frame_checksum = (frame[30] << 8) | frame[31]
        if checksum != frame_checksum:
            return None  # corrupted frame - drop it, next one arrives in ~1s
        return {
            metric: float((frame[offset] << 8) | frame[offset + 1])
            for metric, offset in cls._METRIC_OFFSETS.items()
        }

    async def close(self) -> None:
        for task in self._tasks.values():
            task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        for ser in self._serials.values():
            ser.close()


# ---------------------------------------------------------------------------
# CompositeSensorSource — fans reads out across the three real pollers
# ---------------------------------------------------------------------------


class CompositeSensorSource:
    """Combines RealModbusPoller / RealOneWirePoller / RealPMS7003Poller (or
    any mix of objects exposing the same sensor_ids()/read() interface) into
    the single sensor_source daemon.py's Poller task expects - each
    sensor_id is claimed by exactly one underlying poller, decided once at
    construction time.
    """

    def __init__(self, pollers: List[object]):
        self._by_sensor: Dict[str, object] = {}
        for poller in pollers:
            for sensor_id in poller.sensor_ids():
                if sensor_id in self._by_sensor:
                    raise ValueError(f"sensor_id {sensor_id!r} claimed by more than one poller")
                self._by_sensor[sensor_id] = poller
        self._pollers = pollers

    def sensor_ids(self) -> List[str]:
        return list(self._by_sensor.keys())

    async def read(self, sensor_id: str) -> Tuple[Optional[float], int]:
        return await self._by_sensor[sensor_id].read(sensor_id)

    async def start(self) -> None:
        for poller in self._pollers:
            start = getattr(poller, "start", None)
            if start is not None:
                await start()

    async def close(self) -> None:
        for poller in self._pollers:
            close = getattr(poller, "close", None)
            if close is not None:
                await close()
