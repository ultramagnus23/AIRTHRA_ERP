"""Drives a Nextion-protocol serial touchscreen - e.g. the SmartElex
Basic 4.0" HMI display - with live sensor values.

That screen's actual GUI (gauges, text boxes, buttons, an EMERGENCY STOP
button, whatever it ends up being) is designed separately, on a Windows
laptop, in the Nextion/SmartElex Editor, and flashed onto the screen from
an SD card as a `project.tft` file. This module has zero visibility into
that design - it only knows how to WRITE a value into a named component
("t0", "j2", "x3", ...) over the serial wire. Those component names only
exist once someone has actually built the screen's layout in the editor;
there is no way to discover them from the Pi side. They have to be read
off the editor's own component list and typed into edge/hmi_map.json by
hand, same pattern as the other wiring maps (modbus_map.json etc.).

Wiring: the screen needs its own serial connection, separate from any
other UART already in use (e.g. the PMS7003's) - typically a third
USB-to-serial adapter, or the Pi's spare hardware UART if one is free.
It also needs its own 5V/GND power, not powered off the same rail as the
Pi's 3.3V logic - check the display's own manual for current draw before
sharing a supply with anything else. Cross-connect the data lines:
screen's TX to the adapter's RX, screen's RX to the adapter's TX, GND to
GND. Default baud rate out of the box is 9600 unless changed in the
Nextion Editor's screen device settings - HMI_BAUD must match whatever
was actually configured there.

Protocol: every Nextion serial command is an ASCII string terminated by
three 0xFF bytes, e.g. sending b'zsdf.txt="42.5"\\xff\\xff\\xff' sets a text
component named "zsdf" to display "42.5". This module only ever sends
`<component>.txt="<value>"` - it never reads anything back from the
screen (e.g. button presses), since nothing in this system needs to react
to on-screen input yet.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:
    from edge.daemon import Context

logger = logging.getLogger("edge.hmi")

_TERMINATOR = b"\xff\xff\xff"


def load_hmi_map(path: Path) -> Dict[str, str]:
    """{sensor_id: nextion_component_name}, e.g. {"SO2_out": "t0"}. See
    this module's docstring - these names come from the Nextion/SmartElex
    Editor's own component list for whatever screen layout was actually
    designed, and can't be inferred or discovered automatically. Returns
    an empty map (not an error) if the file doesn't exist yet, so a Pi
    with HMI_ENABLED=true but no map filled in yet just sends nothing
    rather than crashing."""
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def _format_value(reading: dict) -> str:
    """Plain text for a Nextion text component - kept short since these
    screens are small (320x480) and a component's box only fits so much.
    A '!' suffix flags anything not GOOD, since the screen has no other
    way to show color/quality state unless the layout itself was designed
    with that in mind (out of scope here - this only writes .txt)."""
    if reading["value"] is None:
        return "---"
    if reading.get("quality_flag", 0) != 0:
        return f"{reading['value']:.1f}!"
    return f"{reading['value']:.1f}"


class NextionDisplay:
    def __init__(self, port: str, baud: int, component_map: Dict[str, str]):
        self.port = port
        self.baud = baud
        self.component_map = component_map
        self._serial = None

    async def open(self) -> None:
        # Imported lazily, same reasoning as edge/mockgen.py's real
        # pollers - importing this module should never require pyserial's
        # backend to be installed/working just to run --mock.
        import serial

        self._serial = await asyncio.to_thread(
            serial.Serial, self.port, self.baud, timeout=1.0
        )

    async def close(self) -> None:
        if self._serial is not None:
            await asyncio.to_thread(self._serial.close)
            self._serial = None

    async def push(self, readings: List[dict]) -> None:
        """readings: the shape edge/local_store.py's latest_per_sensor()
        returns. Sensors with no entry in component_map are silently
        skipped - a small screen has room for a handful of tags, not all
        of them, and hmi_map.json is exactly the list of which ones."""
        if self._serial is None:
            return
        for reading in readings:
            component = self.component_map.get(reading["sensor_id"])
            if component is None:
                continue
            command = f'{component}.txt="{_format_value(reading)}"'.encode("utf-8") + _TERMINATOR
            try:
                await asyncio.to_thread(self._serial.write, command)
            except Exception:
                logger.warning(
                    "hmi: write failed for %s (component %s) - screen may be "
                    "disconnected or powered off",
                    reading["sensor_id"], component,
                )


async def hmi_task(ctx: "Context", component_map: Dict[str, str]) -> None:
    """One of the daemon's background tasks, only started when
    cfg.hmi_enabled is true (see daemon.py). Runs independently of the
    poller/publisher/dashboard - a disconnected or misbehaving screen
    can't block sensor polling or the MQTT/cloud path, it just stops
    getting updates until it's fixed."""
    if not component_map:
        logger.warning(
            "hmi: enabled but edge/hmi_map.json has no entries - nothing will be "
            "sent to the screen until it's filled in with real component names "
            "from the Nextion/SmartElex Editor"
        )

    display = NextionDisplay(ctx.cfg.hmi_port, ctx.cfg.hmi_baud, component_map)
    try:
        await display.open()
    except Exception:
        logger.error(
            "hmi: could not open %s - check the screen is powered, wired, and "
            "that HMI_PORT matches its actual port. HMI output disabled for "
            "this run (sensor polling/MQTT are unaffected).",
            ctx.cfg.hmi_port,
        )
        return

    logger.info("hmi: writing to %s at %d baud, %d mapped component(s)",
                ctx.cfg.hmi_port, ctx.cfg.hmi_baud, len(component_map))
    try:
        while not ctx.shutdown.is_set():
            readings = await ctx.local_store.latest_per_sensor()
            await display.push(readings)
            await asyncio.sleep(1.0)
    finally:
        await display.close()
