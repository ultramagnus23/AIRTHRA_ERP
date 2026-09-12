"""Per-device health tracking, separate from local_store.py's per-reading
history and the watchdog's aggregate daemon-level stats (edge/config.py's
stats_path()). This answers a different question than either of those:
"is THIS specific sensor currently healthy", independent of whether the
daemon as a whole is healthy - a daemon can be perfectly healthy while
one Modbus device has been unreachable for an hour.

Not persisted to disk - this is in-memory, process-lifetime state,
reset on every daemon restart. That's a deliberate scope limit: the
question this answers is "right now", not "historically" (local_store.py
already answers the historical question, per-reading).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from shared import quality as q


@dataclass
class DeviceHealth:
    sensor_id: str
    last_seen_monotonic: Optional[float] = None  # last read attempt of any kind
    last_good_monotonic: Optional[float] = None  # last GOOD read specifically
    last_error: Optional[str] = None
    error_count: int = 0
    consecutive_failures: int = 0
    read_count: int = 0

    def as_dict(self, now: float) -> dict:
        online = self.last_good_monotonic is not None and (now - self.last_good_monotonic) < 30.0
        return {
            "sensor_id": self.sensor_id,
            "online": online,
            "last_seen_s_ago": None if self.last_seen_monotonic is None else round(now - self.last_seen_monotonic, 1),
            "last_good_s_ago": None if self.last_good_monotonic is None else round(now - self.last_good_monotonic, 1),
            "last_error": self.last_error,
            "error_count": self.error_count,
            "consecutive_failures": self.consecutive_failures,
            "read_count": self.read_count,
        }


class DeviceHealthTracker:
    """One instance shared across the daemon's lifetime (see daemon.py's
    Context). record() is called once per sensor per poll cycle from
    _poll_once() - cheap, in-memory, no I/O."""

    def __init__(self) -> None:
        self._devices: Dict[str, DeviceHealth] = {}

    def record(self, sensor_id: str, quality_flag: int, error: Optional[str] = None) -> None:
        now = time.monotonic()
        dev = self._devices.setdefault(sensor_id, DeviceHealth(sensor_id=sensor_id))
        dev.last_seen_monotonic = now
        dev.read_count += 1
        if quality_flag == q.GOOD:
            dev.last_good_monotonic = now
            dev.consecutive_failures = 0
        else:
            dev.consecutive_failures += 1
            dev.error_count += 1
            dev.last_error = error or q.label(quality_flag)

    def snapshot(self) -> List[dict]:
        now = time.monotonic()
        return [dev.as_dict(now) for dev in sorted(self._devices.values(), key=lambda d: d.sensor_id)]
