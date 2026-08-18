"""Clock trust gate for the edge daemon.

THE FAILURE THIS PREVENTS
-------------------------
A Raspberry Pi has no battery-backed real-time clock. When a factory loses
power and the Pi reboots before 4G/NTP comes back, its system clock resets
to the epoch (or to the last-known filesystem time). Every unguarded
`datetime.now(timezone.utc)` then returns a 1970 timestamp, and because
this daemon buffers to SQLite and backfills on reconnect, those corrupt
timestamps are *durable*: they survive the outage and get replayed into
`readings` the moment the link returns.

Two distinct kinds of damage:
  1. Garbage rows dated 1970 (or any wrong year) polluting the series.
  2. Worse - if the clock lands somewhere plausible but in the *past*,
     backfilled rows can collide with and overwrite genuine history,
     silently corrupting the billing and carbon-credit baseline.

So this module refuses to let the daemon emit a single reading until the
clock is demonstrably trustworthy, and then keeps watching it.

WHAT COUNTS AS TRUSTWORTHY
--------------------------
Three independent checks, cheapest first:

  1. Sanity floor. System time must be at or after BUILD_EPOCH (the date
     this code was written). Time cannot legitimately be earlier than the
     software reading it. Catches the 1970 reset outright.

  2. Monotonic watermark. A high-water mark of the newest timestamp this
     daemon has ever emitted is persisted to disk. The clock may never
     jump backwards past it by more than REGRESSION_TOLERANCE_S. This is
     what actually protects existing history from being overwritten, and
     it survives reboots because it is on disk, not in memory.

  3. Synchronisation source. Best-effort confirmation that something
     authoritative set the clock - NTP (`timedatectl`) or a hardware RTC
     (DS3231 on I2C, exposed by the kernel as an `rtc` device). This is
     advisory: on a host where neither can be interrogated we do NOT
     silently assume success, we report `verified=False` with a reason,
     and the caller decides (REQUIRE_SYNC_SOURCE) whether that blocks.

DEPLOYMENT NOTE - the hardware half of this fix
-----------------------------------------------
Software alone cannot invent the correct time. A DS3231 I2C RTC module
with a CR2032 cell (~Rs150) must be fitted to each Pi so the clock is
right at boot even with no network. This module is what makes the
*absence* of that hardware loud instead of silent: without an RTC and
without NTP, the daemon refuses to fabricate data rather than writing
plausible-looking rows at the wrong time.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("edge.clock")

# The clock can never legitimately read earlier than the day this code was
# written. Bump on major releases; never bump to "now" automatically, or
# the check silently weakens every build.
BUILD_EPOCH = datetime(2026, 8, 1, tzinfo=timezone.utc)

# Small backward jumps are normal (NTP slewing, leap-second smearing) and
# must not trip the regression guard. Anything beyond this is a real reset.
REGRESSION_TOLERANCE_S = 120.0

# When True, an unverifiable sync source (no NTP, no RTC) blocks startup.
# Default False so a dev laptop isn't bricked by a missing timedatectl,
# but production images should set EDGE_REQUIRE_SYNC_SOURCE=1.
REQUIRE_SYNC_SOURCE = os.environ.get("EDGE_REQUIRE_SYNC_SOURCE") == "1"


@dataclass
class ClockStatus:
    ok: bool
    reason: str
    synced_via: str | None = None
    watermark: datetime | None = None

    def __str__(self) -> str:
        via = f" (synced via {self.synced_via})" if self.synced_via else ""
        return f"{'OK' if self.ok else 'UNTRUSTED'}: {self.reason}{via}"


def _ntp_synchronised() -> bool | None:
    """True/False from timedatectl, or None if it can't be interrogated
    (not systemd, not Linux, command missing). None means 'unknown', which
    is deliberately distinct from False."""
    if sys.platform == "win32":
        return None
    try:
        out = subprocess.run(
            ["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip().lower() == "yes"


def _rtc_present() -> bool:
    """Whether the kernel exposes a hardware RTC (the DS3231 shows up as
    /dev/rtc0 once the i2c-rtc overlay is enabled)."""
    return any(Path(p).exists() for p in ("/dev/rtc", "/dev/rtc0"))


class ClockGate:
    """Persists a monotonic high-water mark and validates the system clock
    against it. One instance per daemon."""

    def __init__(self, state_path: Path | str):
        self._path = Path(state_path)
        self._watermark: datetime | None = self._load()

    def _load(self) -> datetime | None:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            return datetime.fromisoformat(raw["watermark"])
        except (OSError, ValueError, KeyError):
            # Absent or corrupt watermark is not an error - a first-ever
            # boot has none. It just means check 2 can't contribute yet.
            return None

    def _save(self, ts: datetime) -> None:
        tmp = self._path.with_suffix(".tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps({"watermark": ts.isoformat()}), encoding="utf-8")
            os.replace(tmp, self._path)  # atomic; a torn write can't corrupt it
        except OSError as exc:
            # Never fail a reading because the watermark couldn't persist,
            # but never hide it either - a Pi that can't write this has a
            # failing SSD and its history protection is degraded.
            log.error("clock: could not persist watermark (%s) - history protection degraded", exc)

    @property
    def watermark(self) -> datetime | None:
        return self._watermark

    def check(self, now: datetime | None = None) -> ClockStatus:
        now = now or datetime.now(timezone.utc)

        if now < BUILD_EPOCH:
            return ClockStatus(
                False,
                f"system clock reads {now.isoformat()}, before this software existed "
                f"({BUILD_EPOCH.date()}) - no RTC and no NTP since boot",
                watermark=self._watermark,
            )

        if self._watermark is not None:
            regression = (self._watermark - now).total_seconds()
            if regression > REGRESSION_TOLERANCE_S:
                return ClockStatus(
                    False,
                    f"system clock went backwards {regression:.0f}s past the last emitted "
                    f"reading ({self._watermark.isoformat()}) - writing now would overwrite history",
                    watermark=self._watermark,
                )

        ntp = _ntp_synchronised()
        rtc = _rtc_present()
        if ntp:
            return ClockStatus(True, "clock validated", "ntp", self._watermark)
        if rtc:
            return ClockStatus(True, "clock validated", "hardware rtc", self._watermark)

        reason = "no NTP sync and no hardware RTC detected"
        if REQUIRE_SYNC_SOURCE:
            return ClockStatus(False, reason + " (EDGE_REQUIRE_SYNC_SOURCE=1)", watermark=self._watermark)
        return ClockStatus(
            True,
            f"clock passed sanity+monotonic checks but {reason}",
            "unverified",
            self._watermark,
        )

    def observe(self, ts: datetime) -> None:
        """Record an emitted timestamp, advancing the persisted watermark.
        Only ever moves forward."""
        if self._watermark is None or ts > self._watermark:
            self._watermark = ts
            self._save(ts)
