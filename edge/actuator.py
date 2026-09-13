"""Real Modbus coil control for the 12V 8-Ch Relay Module (slave 0x02),
per the Delhi engineer's schematic (Sheets 3 & 6, confirmed 2026-09-13).

This is intentionally a THIN, direct write-coil wrapper - not the full
actuator abstraction (permission checks, interlocks, state machine,
confirmation readback) that a production commissioning mode would need.
Building that safely needs plant-specific interlock logic that doesn't
exist yet. This module exists so "toggle Relay 1" (the Delhi engineer's
own bench-test checklist item 5) is actually possible today, without
pretending more safety infrastructure exists than really does. Do not
wire this into any automated control loop or unauthenticated API route -
see the original hardware-integration plan's Phase 13/37 for why.

Protocol: Modbus function code 0x05 (write single coil), matching what
the schematic specifies for this module.

RELAY MAP (Sheet 6 - confirmed 2026-09-13):
  Relay 1 (coil 0): Solenoid 1 (CEMS gas/air switching), NO, 12V
  Relay 2 (coil 1): Solenoid 2 (CEMS gas/air switching), NO, 12V
  Relay 3 (coil 2): CEMS micro vacuum pump, NO, 12V
  Relay 4 (coil 3): V-101 damper holding electromagnet, **NC** - THIS IS
                    THE PLANT'S FAIL-SAFE, READ BEFORE TOUCHING IT:
                      ON  (coil=True)  -> relay energized  -> magnet HOLDS -> damper stays CLOSED
                      OFF (coil=False) -> relay de-energized -> magnet DROPS -> damper OPENS
                    A power loss, a Pi crash, or a dropped Modbus
                    connection all leave this relay de-energized, which
                    OPENS the damper - the physically safe state by
                    design. Never command this coil as a casual test
                    without knowing what closing the damper does to the
                    process at that exact moment - see main()'s
                    --yes-i-know-this-is-the-damper gate below.
  Relay 5 (coil 4): 230V KOH solenoid, NO
  Relay 6 (coil 5): 3-phase contactor coil (motor start permissive), NO
  Coils 6-7: unused/spare on this build.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")
logger = logging.getLogger("edge.actuator")

RELAY_SLAVE_ID = 0x02

# name -> (coil, is_safety_critical)
RELAY_MAP = {
    "relay1_solenoid1": (0, False),
    "relay2_solenoid2": (1, False),
    "relay3_cems_pump": (2, False),
    "relay4_damper_magnet": (3, True),  # NC fail-safe - see module docstring above
    "relay5_koh_solenoid": (4, False),
    "relay6_contactor": (5, False),
}


async def set_relay(bus: str, coil: int, state: bool, baud: int = 9600, timeout: float = 2.0) -> bool:
    """Writes a single coil on the relay module. Returns True if the
    write was acknowledged, False on any communication failure - never
    raises, since a failed actuator write must be handled by the caller
    as "the command did not happen", not crash the process."""
    client = None
    try:
        # Constructing the client can itself raise (e.g. pyserial
        # missing) - inside the try, same fix as test_real_pollers.py's
        # ping function, for the same reason.
        from pymodbus.client import AsyncModbusSerialClient

        client = AsyncModbusSerialClient(bus, baudrate=baud, timeout=timeout)
        connected = await asyncio.wait_for(client.connect(), timeout=timeout)
        if not connected:
            logger.error("actuator: could not connect to relay module on %s", bus)
            return False
        result = await asyncio.wait_for(
            client.write_coil(coil, state, slave=RELAY_SLAVE_ID), timeout=timeout
        )
        if result.isError():
            logger.error("actuator: write_coil(%d, %s) rejected by relay module: %s", coil, state, result)
            return False
        logger.info("actuator: coil %d set to %s (relay module slave 0x%02X on %s)",
                    coil, state, RELAY_SLAVE_ID, bus)
        return True
    except Exception:
        logger.exception("actuator: write_coil(%d, %s) failed", coil, state)
        return False
    finally:
        if client is not None:
            client.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Toggle one relay on the 12V 8-Ch Modbus Relay Module (bench-test tool, "
                     "not a production control interface - see this module's docstring)"
    )
    parser.add_argument("relay", choices=sorted(RELAY_MAP.keys()), help="which relay to command")
    parser.add_argument("state", choices=["on", "off"], help="desired state")
    parser.add_argument("--bus", default="/dev/ttyUSB0", help="RS-485 serial port (default: /dev/ttyUSB0)")
    parser.add_argument(
        "--yes-i-know-this-is-the-damper",
        action="store_true",
        help="required to command relay4_damper_magnet - see this module's docstring for what ON/OFF actually do",
    )
    args = parser.parse_args()

    coil, is_critical = RELAY_MAP[args.relay]
    if is_critical and not args.yes_i_know_this_is_the_damper:
        print(
            f"REFUSING: {args.relay} is the damper's fail-safe relay (NC wiring - see "
            f"edge/actuator.py's docstring for exactly what ON/OFF do to the physical damper). "
            f"Re-run with --yes-i-know-this-is-the-damper if you actually mean to command it."
        )
        sys.exit(1)

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    ok = asyncio.run(set_relay(args.bus, coil, args.state == "on"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
