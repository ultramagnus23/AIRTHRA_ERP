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


def _load_map_or_empty(loader, path: Path, label: str) -> dict:
    if not path.exists():
        print(f"  ! {label} map not found at {path} - treating as empty (0 sensors on this bus)")
        return {}
    try:
        return loader(path)
    except Exception as exc:  # noqa: BLE001 - report and continue, don't abort the whole run
        print(f"  ! {label} map at {path} failed to parse: {exc}")
        return {}


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
            results.append(("modbus", s, value, flag, error, elapsed))
        await poller.close()

    if onewire_sensors:
        poller = RealOneWirePoller(onewire_sensors, onewire_map)
        for s in onewire_sensors:
            value, flag, error, elapsed = await _read_with_timing(poller, s.sensor_id, timeout)
            results.append(("onewire", s, value, flag, error, elapsed))
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
            results.append(("pms7003", s, value, flag, error, elapsed))
        await poller.close()

    print(f"{'sensor_id':<20} {'bus':<9} {'status':<14} {'value':>10}   {'notes'}")
    print("-" * 80)
    good = 0
    for bus, spec, value, flag, error, elapsed in results:
        if error is not None:
            status, value_str, note = "EXCEPTION", "-", error
        else:
            status = _STATUS_LABELS.get(flag, f"unknown({flag})")
            value_str = "-" if value is None else f"{value:.3f}"
            note = f"{elapsed * 1000:.0f}ms"
            if status == "GOOD":
                good += 1
        print(f"{spec.sensor_id:<20} {bus:<9} {status:<14} {value_str:>10}   {note}")

    print("-" * 80)
    print(f"{good}/{len(results)} sensor(s) read GOOD "
          f"({len(unconfirmed)} skipped as unconfirmed, {len(misconfigured)} wiring gap(s))")

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
