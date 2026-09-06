#!/usr/bin/env python
"""Dry-run wiring check for the real sensor pollers (edge/mockgen.py).

Run this once edge/modbus_map.json / edge/onewire_map.json /
edge/pms7003_map.json have been filled in with real values, BEFORE
attempting a full `python edge/daemon.py --plant-id ... ` (real, non-mock)
run. It builds the same CompositeSensorSource daemon.py would, attempts one
read of every sensor in the manifest, and prints a table of what's reachable
vs erroring - so a wiring mistake shows up in a few seconds instead of only
surfacing once the daemon is also juggling MQTT/buffering/backfill.

This does NOT touch MQTT, the SQLite buffer, or publish anything - it only
reads the Postgres sensor manifest and talks to the physical buses.

Usage:
    python edge/test_real_pollers.py --plant-id goa_pilot_01
    python edge/test_real_pollers.py --plant-id goa_pilot_01 --timeout 3.0
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from edge.config import EdgeConfig  # noqa: E402
from edge.manifest import PostgresManifestSource, load_manifest  # noqa: E402
from edge.mockgen import (  # noqa: E402
    RealModbusPoller,
    RealOneWirePoller,
    RealPMS7003Poller,
    load_modbus_map,
    load_onewire_map,
    load_pms7003_map,
)
from shared import quality as q  # noqa: E402

_STATUS_LABELS = {
    q.GOOD: "GOOD",
    q.COMM_ERROR: "COMM_ERROR",
    q.OUT_OF_RANGE: "OUT_OF_RANGE",
    q.FROZEN: "FROZEN/STUCK",
}

# Devices confirmed by physical DIP-switch/config address as of 2026-09-06 -
# not sensors in the manifest (the relay module isn't one at all), so they
# need their own reachability check independent of modbus_map.json/the
# sensor-based flow above. "Ping" here means: does ANYTHING answer at this
# slave ID, on either RS-485 bus - not "is register X readable", since we
# don't have register maps for any of these yet either.
MODBUS_PING_TARGETS = [
    ("Waveshare 8-Ch Analog Module", 0x01),
    ("12V Modbus Relay Module", 0x02),
    ("Sangbay SO2 (High)", 0x03),
    ("Sangbay SO2 (Low)", 0x04),
]
MODBUS_PING_BUSES = ["/dev/ttyUSB0", "/dev/ttyUSB1"]


def _load_map_or_empty(loader, path: Path, label: str) -> dict:
    if not path.exists():
        print(f"  ! {label} map not found at {path} - treating as empty (0 sensors on this bus)")
        return {}
    try:
        return loader(path)
    except Exception as exc:  # noqa: BLE001 - report and continue, don't abort the whole run
        print(f"  ! {label} map at {path} failed to parse: {exc}")
        return {}


async def _ping_slave_on_bus(bus: str, slave_id: int, timeout: float) -> str:
    """Tries a minimal read (holding register 0) against one slave_id on
    one bus. Returns one of: "found" (got real data back - device present
    AND register 0 happens to be defined), "found (no reg 0)" (the bus
    round-trip completed and the device sent back a Modbus exception
    response, e.g. illegal data address - the device IS there and
    answering, it just doesn't have anything at register 0, which is
    expected since we don't have real register maps yet), or "no response"
    (timeout/connect failure - nothing at this address on this bus)."""
    client = None
    try:
        # Constructing the client (not just connecting) can itself raise -
        # e.g. pyserial missing, or an obviously malformed port string -
        # so it has to be inside the try, not before it, or exactly the
        # kind of environment problem this ping is meant to surface
        # gracefully instead crashes the whole script.
        from pymodbus.client import AsyncModbusSerialClient

        client = AsyncModbusSerialClient(bus, baudrate=9600, timeout=timeout)
        connected = await asyncio.wait_for(client.connect(), timeout=timeout)
        if not connected:
            return "no response"
        result = await asyncio.wait_for(
            client.read_holding_registers(0, count=1, slave=slave_id), timeout=timeout
        )
        if result.isError():
            # A real Modbus exception response (e.g. illegal data address)
            # still means something answered - that's a meaningfully
            # different outcome from silence, hence the separate label.
            return "found (no reg 0)"
        return "found"
    except Exception:
        return "no response"
    finally:
        if client is not None:
            client.close()


async def ping_modbus_devices(timeout: float) -> None:
    print("Pinging fixed-address Modbus devices (both buses, register 0 as a probe) ...")
    print(f"{'device':<32} {'slave_id':<10} {'/dev/ttyUSB0':<16} {'/dev/ttyUSB1':<16}")
    print("-" * 78)
    for name, slave_id in MODBUS_PING_TARGETS:
        row = [name, f"0x{slave_id:02X}"]
        for bus in MODBUS_PING_BUSES:
            row.append(await _ping_slave_on_bus(bus, slave_id, timeout))
        found_on = [b for b, r in zip(MODBUS_PING_BUSES, row[2:]) if r.startswith("found")]
        if len(found_on) > 1:
            print(f"  ! {name}: responded on MORE THAN ONE bus ({found_on}) - check for a wiring "
                  f"short between the two RS-485 buses, or a duplicate slave_id elsewhere.")
        print(f"{row[0]:<32} {row[1]:<10} {row[2]:<16} {row[3]:<16}")
    print()


async def _read_with_timing(source, sensor_id: str, timeout: float):
    start = time.monotonic()
    try:
        value, flag = await asyncio.wait_for(source.read(sensor_id), timeout=timeout)
        return value, flag, None, time.monotonic() - start
    except asyncio.TimeoutError:
        return None, None, f"timed out after {timeout:.1f}s", time.monotonic() - start
    except Exception as exc:  # noqa: BLE001 - a crashing poller is exactly what this script checks for
        return None, None, f"{type(exc).__name__}: {exc}", time.monotonic() - start


async def main_async(plant_id: str, timeout: float) -> int:
    cfg = EdgeConfig(plant_id=plant_id, mock=False)

    await ping_modbus_devices(timeout)

    print(f"Loading manifest for plant_id={plant_id!r} ...")
    sensors = load_manifest(plant_id, PostgresManifestSource(cfg.database_url), cfg.manifest_cache_path())
    print(f"  {len(sensors)} sensor(s) in manifest\n")

    print("Loading wiring maps ...")
    modbus_map = _load_map_or_empty(load_modbus_map, cfg.modbus_map_path(), "modbus")
    onewire_map = _load_map_or_empty(load_onewire_map, cfg.onewire_map_path(), "onewire")
    pms7003_map = _load_map_or_empty(load_pms7003_map, cfg.pms7003_map_path(), "pms7003")
    print()

    modbus_sensors = [s for s in sensors if s.sensor_id in modbus_map]
    onewire_sensors = [s for s in sensors if s.sensor_id in onewire_map]
    pms_sensors = [s for s in sensors if s.sensor_id in pms7003_map]
    claimed = {s.sensor_id for s in modbus_sensors + onewire_sensors + pms_sensors}
    unclaimed = [s for s in sensors if s.sensor_id not in claimed]
    unconfirmed = [s.sensor_id for s in unclaimed if s.interface in (None, "unconfirmed")]
    misconfigured = [s.sensor_id for s in unclaimed if s.interface not in (None, "unconfirmed")]

    if unconfirmed:
        print(f"SKIPPING (interface unconfirmed, not an error): {unconfirmed}\n")
    if misconfigured:
        print(f"WIRING GAP - declares a real interface but missing from its map: {misconfigured}\n")

    results = []

    if modbus_sensors:
        poller = RealModbusPoller(modbus_sensors, modbus_map)
        for s in modbus_sensors:
            value, flag, error, elapsed = await _read_with_timing(poller, s.sensor_id, timeout)
            physical = f"{modbus_map[s.sensor_id].bus} @0x{modbus_map[s.sensor_id].slave_id:02X}"
            results.append(("modbus", physical, s, value, flag, error, elapsed))
        await poller.close()

    if onewire_sensors:
        poller = RealOneWirePoller(onewire_sensors, onewire_map)
        for s in onewire_sensors:
            value, flag, error, elapsed = await _read_with_timing(poller, s.sensor_id, timeout)
            results.append(("onewire", poller.bus_for(s.sensor_id), s, value, flag, error, elapsed))
        await poller.close()

    if pms_sensors:
        poller = RealPMS7003Poller(pms_sensors, pms7003_map)
        await poller.start()
        # PMS7003 is a background stream, not request/response - give the
        # reader task(s) a moment to land at least one frame before reading,
        # otherwise every sensor reports COMM_ERROR ("nothing cached yet")
        # even on perfectly good wiring.
        await asyncio.sleep(min(timeout, 2.0))
        for s in pms_sensors:
            value, flag, error, elapsed = await _read_with_timing(poller, s.sensor_id, timeout)
            results.append(("pms7003", pms7003_map[s.sensor_id].device, s, value, flag, error, elapsed))
        await poller.close()

    print(f"{'sensor_id':<20} {'kind':<9} {'physical':<26} {'status':<14} {'value':>10}   {'notes'}")
    print("-" * 106)
    good = 0
    bus_tally: dict = {}  # onewire bus label -> [good, total] - fault isolation, at a glance
    for kind, physical, spec, value, flag, error, elapsed in results:
        if error is not None:
            status, value_str, note = "EXCEPTION", "-", error
        else:
            status = _STATUS_LABELS.get(flag, f"unknown({flag})")
            value_str = "-" if value is None else f"{value:.3f}"
            note = f"{elapsed * 1000:.0f}ms"
            if status == "GOOD":
                good += 1
        print(f"{spec.sensor_id:<20} {kind:<9} {physical:<26} {status:<14} {value_str:>10}   {note}")
        if kind == "onewire":
            tally = bus_tally.setdefault(physical, [0, 0])
            tally[1] += 1
            if error is None and flag == q.GOOD:
                tally[0] += 1

    print("-" * 106)
    print(f"{good}/{len(results)} sensor(s) read GOOD "
          f"({len(unconfirmed)} skipped as unconfirmed, {len(misconfigured)} wiring gap(s))")

    if bus_tally:
        print()
        print("1-Wire bus summary (this is the point of the 3-bus split: a whole")
        print("bus reading 0/N usually means that bus's wiring, not 15 dead probes):")
        for bus, (bus_good, bus_total) in sorted(bus_tally.items()):
            flag_note = "  <-- check this bus's wiring/pull-up resistor" if bus_good == 0 else ""
            print(f"  {bus:<20} {bus_good}/{bus_total} good{flag_note}")

    # Non-zero exit whenever there's something a human should look at before
    # trusting a full daemon run, so this is CI/script-friendly.
    return 1 if (misconfigured or good < len(results)) else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Dry-run check of the real sensor pollers")
    parser.add_argument("--plant-id", required=True)
    parser.add_argument("--timeout", type=float, default=2.0, help="per-sensor read timeout, seconds")
    args = parser.parse_args()

    # Same Windows quirk as edge/daemon.py: raw-socket-registering serial
    # backends don't work under the default ProactorEventLoop.
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    exit_code = asyncio.run(main_async(args.plant_id, args.timeout))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
