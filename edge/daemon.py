#!/usr/bin/env python
"""Airthra edge daemon (P1).

Single asyncio process, four concurrent tasks:
  - Poller:    reads the sensor manifest (real mode: Modbus: not built here,
               no field hardware; --mock mode: sinusoidal generator with
               injected faults) and produces (plant_id, sensor_id, ts, value,
               quality_flag) readings + occasional VFD setpoint changes.
  - Publisher: batches readings every ~1s, publishes to MQTT
               plants/{plant_id}/readings at QoS 1. On broker loss, buffers
               to a local SQLite WAL file instead of dropping data.
  - Sync:      when the broker reconnects, drains the SQLite buffer
               oldest-first in chunks of 500 to plants/{plant_id}/backfill,
               deleting each chunk only after it's QoS1-acknowledged.
  - Watchdog:  every 10s checks poller/publisher/queue/disk health and
               writes a heartbeat pulse file if (and only if) everything
               looks healthy.

Usage:
    python edge/daemon.py --mock --plant-id goa_pilot_01

Reads Postgres/MQTT connection info from .env (repo root). See
edge/config.py for all tunables.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import aiomqtt  # noqa: E402

from edge.buffer import SqliteBuffer  # noqa: E402
from edge.clock import ClockGate  # noqa: E402
from edge.config import EdgeConfig  # noqa: E402
from edge.manifest import PostgresManifestSource, load_manifest  # noqa: E402
from edge.mockgen import (  # noqa: E402
    CompositeSensorSource,
    MockSensorSource,
    MockSetpointSource,
    RealModbusPoller,
    RealOneWirePoller,
    RealPMS7003Poller,
    load_modbus_map,
    load_onewire_map,
    load_pms7003_map,
)
from shared import quality as q  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)-16s %(message)s",
)
log = logging.getLogger("edge.daemon")


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Context:
    """Shared state between the four tasks."""

    def __init__(self, cfg: EdgeConfig):
        self.cfg = cfg
        self.outbox: asyncio.Queue = asyncio.Queue()
        self.buffer = SqliteBuffer(cfg.buffer_db_path())
        self.clock = ClockGate(cfg.clock_state_path())
        self.connected = asyncio.Event()
        self.shutdown = asyncio.Event()
        self.mqtt_client: Optional[aiomqtt.Client] = None
        self.mqtt_lock = asyncio.Lock()

        # Watchdog inputs, updated by other tasks.
        self.last_poll_monotonic: float = time.monotonic()
        self.publisher_last_heartbeat: float = time.monotonic()
        self.sync_drained_total: int = 0
        self.readings_published_total: int = 0
        self.readings_buffered_total: int = 0
        # Total readings the Poller has ever generated (pushed to outbox).
        # This is the "expected count" the gate script uses to assert zero
        # gaps: every generated reading is valid-by-construction (known
        # sensor, in-range-or-flagged value, well-formed ts), so it should
        # always end up in Postgres exactly once, whether it went out live
        # or via the SQLite buffer + backfill drain.
        self.readings_generated_total: int = 0
        # Cycles skipped because the clock could not be trusted. Non-zero
        # here means a unit is alive but deliberately not producing data -
        # a fundamentally different (and more urgent) condition than a
        # unit that is simply offline, so it is surfaced separately.
        self.readings_dropped_bad_clock: int = 0

    def write_stats(self) -> None:
        stats = {
            "generated_total": self.readings_generated_total,
            "published_total": self.readings_published_total,
            "buffered_total": self.readings_buffered_total,
            "drained_total": self.sync_drained_total,
            "dropped_bad_clock": self.readings_dropped_bad_clock,
            "clock_watermark": (
                self.clock.watermark.isoformat() if self.clock.watermark else None
            ),
            "outbox_qsize": self.outbox.qsize(),
            "connected": self.connected.is_set(),
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        try:
            self.cfg.stats_path().write_text(json.dumps(stats), encoding="utf-8")
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Poller
# ---------------------------------------------------------------------------

async def poller_task(ctx: Context, sensor_source, setpoint_source: MockSetpointSource) -> None:
    cfg = ctx.cfg
    stop_path = cfg.stop_request_path()
    log.info("poller: started (%s, %d sensors, interval=%.1fs)",
              "mock" if cfg.mock else "real", len(sensor_source.sensor_ids()), cfg.poll_interval_s)
    while not ctx.shutdown.is_set():
        if stop_path.exists():
            log.info("poller: graceful stop requested (%s) - no more readings will be generated", stop_path)
            try:
                stop_path.unlink()
            except OSError:
                pass
            return

        cycle_start = time.monotonic()
        now = datetime.now(timezone.utc)

        # Re-check every cycle, not just at boot: NTP can step the clock
        # backwards at any moment, and a reading minted during that window
        # would collide with history already written. Skipping a cycle
        # loses one sample; emitting a mis-timestamped one corrupts the
        # billing baseline durably.
        clock_status = ctx.clock.check(now)
        if not clock_status.ok:
            log.error("poller: skipping cycle - %s", clock_status)
            ctx.readings_dropped_bad_clock += 1
            await asyncio.sleep(cfg.poll_interval_s)
            continue
        ctx.clock.observe(now)

        try:
            await asyncio.wait_for(_poll_once(ctx, sensor_source, setpoint_source, now), timeout=cfg.read_timeout_s * 5)
        except asyncio.TimeoutError:
            log.error("poller: cycle exceeded read timeout budget, skipping this cycle")

        ctx.last_poll_monotonic = time.monotonic()

        elapsed = time.monotonic() - cycle_start
        await asyncio.sleep(max(0.0, cfg.poll_interval_s - elapsed))


async def _poll_once(ctx: Context, sensor_source, setpoint_source: MockSetpointSource, now: datetime) -> None:
    cfg = ctx.cfg
    ts_iso = now.isoformat()
    for sensor_id in sensor_source.sensor_ids():
        # Each individual read is wrapped in a timeout budget: real Modbus/
        # serial reads can hang, --mock reads are instant either way.
        try:
            value, flag = await asyncio.wait_for(
                _read_one(sensor_source, sensor_id), timeout=cfg.read_timeout_s
            )
        except asyncio.TimeoutError:
            value, flag = None, q.COMM_ERROR

        reading = {
            "plant_id": cfg.plant_id,
            "sensor_id": sensor_id,
            "ts": ts_iso,
            "value": value,
            "quality_flag": flag,
        }
        ctx.outbox.put_nowait(("reading", reading))
        ctx.readings_generated_total += 1

    for change in setpoint_source.poll():
        change["plant_id"] = cfg.plant_id
        change["ts"] = ts_iso
        ctx.outbox.put_nowait(("setpoint", change))

    ctx.write_stats()


async def _read_one(sensor_source, sensor_id: str):
    # MockSensorSource.read() is a plain sync call (no I/O to await);
    # CompositeSensorSource.read() (real Modbus/1-Wire/PMS7003) is a
    # coroutine function since it does real, potentially-blocking I/O. This
    # dispatches to whichever shape sensor_source actually has so the
    # asyncio.wait_for timeout wrapper above works identically either way.
    result = sensor_source.read(sensor_id)
    if asyncio.iscoroutine(result):
        return await result
    return result


# ---------------------------------------------------------------------------
# Publisher
# ---------------------------------------------------------------------------

def _build_tls_params(cfg: EdgeConfig) -> Optional["aiomqtt.TLSParameters"]:
    """None when TLS is off (plaintext, e.g. local same-host dev against
    the 1883 listener) - aiomqtt.Client treats tls_params=None as "don't
    use TLS". When on, ca_certs is required (EdgeConfig.__post_init__
    already enforced that) so the client verifies it's actually talking to
    the real broker rather than trusting the self-signed cert blindly.
    certfile/keyfile are only set if both are present, for a future mTLS
    upgrade (mosquitto.conf's require_certificate is false today, so the
    broker doesn't ask for these yet - see EdgeConfig's mqtt_use_tls docstring)."""
    if not cfg.mqtt_use_tls:
        return None
    return aiomqtt.TLSParameters(
        ca_certs=cfg.mqtt_ca_cert_path,
        certfile=cfg.mqtt_client_cert_path or None,
        keyfile=cfg.mqtt_client_key_path or None,
    )


async def publisher_task(ctx: Context) -> None:
    cfg = ctx.cfg
    while not ctx.shutdown.is_set():
        try:
            log.info("publisher: connecting to %s://%s:%d as %s",
                      "mqtts" if cfg.mqtt_use_tls else "mqtt",
                      cfg.mqtt_host, cfg.mqtt_port, cfg.mqtt_username)
            async with aiomqtt.Client(
                hostname=cfg.mqtt_host,
                port=cfg.mqtt_port,
                username=cfg.mqtt_username or None,
                password=cfg.mqtt_password or None,
                identifier=f"edge-{cfg.plant_id}",
                tls_params=_build_tls_params(cfg),
                tls_insecure=cfg.mqtt_tls_insecure if cfg.mqtt_use_tls else None,
            ) as client:
                ctx.mqtt_client = client
                ctx.connected.set()
                log.info("publisher: connected")
                await _publish_loop(ctx, client)
        except aiomqtt.MqttError as exc:
            ctx.connected.clear()
            ctx.mqtt_client = None
            log.warning("publisher: mqtt connection lost/failed (%s); buffering, retrying in %.1fs",
                        exc, cfg.mqtt_reconnect_delay_s)
            await asyncio.sleep(cfg.mqtt_reconnect_delay_s)
        except Exception as exc:  # noqa: BLE001 - never let publisher die silently
            ctx.connected.clear()
            ctx.mqtt_client = None
            log.error("publisher: unexpected error (%s); retrying in %.1fs", exc, cfg.mqtt_reconnect_delay_s)
            await asyncio.sleep(cfg.mqtt_reconnect_delay_s)

    if ctx.mqtt_client is not None:
        ctx.connected.clear()


async def _publish_loop(ctx: Context, client: aiomqtt.Client) -> None:
    cfg = ctx.cfg
    while not ctx.shutdown.is_set():
        cycle_start = time.monotonic()
        ctx.publisher_last_heartbeat = time.monotonic()

        readings, setpoints = _drain_outbox(ctx)

        if readings:
            try:
                async with ctx.mqtt_lock:
                    await client.publish(
                        f"plants/{cfg.plant_id}/readings",
                        payload=json.dumps(readings),
                        qos=1,
                    )
                ctx.readings_published_total += len(readings)
            except aiomqtt.MqttError:
                # Connection is down - buffer everything drained this cycle
                # (readings AND any setpoints, since we won't get a chance to
                # try the setpoints publish below) and let the outer
                # reconnect loop take over. Nothing drained from the outbox
                # this cycle is lost.
                now_iso = utcnow_iso()
                await ctx.buffer.put_many(
                    [("reading", r, now_iso) for r in readings]
                    + [("setpoint", sp, now_iso) for sp in setpoints]
                )
                ctx.readings_buffered_total += len(readings)
                raise  # let the outer reconnect loop handle it

        for i, sp in enumerate(setpoints):
            try:
                async with ctx.mqtt_lock:
                    await client.publish(
                        f"plants/{cfg.plant_id}/setpoints",
                        payload=json.dumps(sp),
                        qos=1,
                    )
            except aiomqtt.MqttError:
                # This one plus every remaining not-yet-sent setpoint in this
                # cycle's batch goes to the buffer - the connection is down.
                now_iso = utcnow_iso()
                await ctx.buffer.put_many([("setpoint", s, now_iso) for s in setpoints[i:]])
                raise

        elapsed = time.monotonic() - cycle_start
        await asyncio.sleep(max(0.0, cfg.publish_interval_s - elapsed))
        ctx.publisher_last_heartbeat = time.monotonic()


def _drain_outbox(ctx: Context):
    readings, setpoints = [], []
    while True:
        try:
            kind, payload = ctx.outbox.get_nowait()
        except asyncio.QueueEmpty:
            break
        if kind == "reading":
            readings.append(payload)
        else:
            setpoints.append(payload)
    return readings, setpoints


# ---------------------------------------------------------------------------
# Sync (backfill drain)
# ---------------------------------------------------------------------------

async def sync_task(ctx: Context) -> None:
    cfg = ctx.cfg
    # This task must NEVER die silently (per the "no silent failures" rule) -
    # an un-awaited task exception would just vanish until process exit, and
    # buffered data would be stranded on disk forever with nothing draining
    # it. Every iteration is wrapped so any unexpected error is logged with
    # a full traceback and the loop keeps going instead of dying quietly.
    while not ctx.shutdown.is_set():
        try:
            await _sync_once(ctx)
        except aiomqtt.MqttError as exc:
            log.warning("sync: backfill publish failed (%s); leaving chunk buffered, will retry", exc)
            await asyncio.sleep(cfg.mqtt_reconnect_delay_s)
        except Exception:  # noqa: BLE001
            log.exception("sync: unexpected error in drain loop; retrying")
            await asyncio.sleep(cfg.sync_idle_delay_s)


async def _sync_once(ctx: Context) -> None:
    cfg = ctx.cfg
    if not ctx.connected.is_set() or ctx.mqtt_client is None:
        await asyncio.sleep(cfg.sync_idle_delay_s)
        return

    pending = await ctx.buffer.count()
    if pending == 0:
        await asyncio.sleep(cfg.sync_idle_delay_s)
        return

    chunk = await ctx.buffer.peek_chunk(cfg.sync_chunk_size)
    if not chunk:
        await asyncio.sleep(cfg.sync_idle_delay_s)
        return

    envelope = [{"kind": kind, "data": payload} for (_id, kind, payload) in chunk]
    ids = [row_id for (row_id, _kind, _payload) in chunk]

    # Re-check right before use, not just at the top of this function: the
    # two awaits above (buffer.count/peek_chunk) both yield control, and the
    # publisher task can disconnect (clearing mqtt_client back to None) in
    # that window. Caught this exact race via the broad except in
    # sync_task() during gate testing - fixing it here properly rather than
    # relying solely on that safety net.
    client = ctx.mqtt_client
    if client is None or not ctx.connected.is_set():
        return
    async with ctx.mqtt_lock:
        await client.publish(
            f"plants/{cfg.plant_id}/backfill",
            payload=json.dumps(envelope),
            qos=1,
        )
    # Only delete after the QoS1 puback (client.publish awaited above does
    # not return until the broker acknowledges it - see aiomqtt.Client.
    # publish, which awaits the on_publish callback).
    await ctx.buffer.delete_ids(ids)
    ctx.sync_drained_total += len(ids)
    ctx.write_stats()
    log.info("sync: drained %d buffered item(s) to backfill (%d remaining)",
              len(ids), pending - len(ids))

    # Lower priority than live polling/publishing: yield generously between
    # chunks instead of racing straight into the next one.
    await asyncio.sleep(0.05)


# ---------------------------------------------------------------------------
# Watchdog
# ---------------------------------------------------------------------------

async def watchdog_task(ctx: Context) -> None:
    cfg = ctx.cfg
    heartbeat_path = cfg.heartbeat_path()
    while not ctx.shutdown.is_set():
        await asyncio.sleep(cfg.watchdog_interval_s)
        try:
            await _watchdog_check(ctx, heartbeat_path)
        except Exception:  # noqa: BLE001 - the watchdog must never die silently either
            log.exception("watchdog: unexpected error during health check")


async def _watchdog_check(ctx: Context, heartbeat_path: Path) -> None:
    cfg = ctx.cfg
    reasons = []

    poller_age = time.monotonic() - ctx.last_poll_monotonic
    if poller_age > cfg.max_poller_silence_s + cfg.watchdog_interval_s:
        reasons.append(f"poller silent for {poller_age:.1f}s (limit {cfg.max_poller_silence_s:.1f}s)")

    queue_size = ctx.outbox.qsize()
    buffered = await ctx.buffer.count()
    total_pending = queue_size + buffered
    if total_pending > cfg.max_queue_size:
        reasons.append(f"pending items {total_pending} exceeds max_queue_size {cfg.max_queue_size}")

    try:
        free_bytes = shutil.disk_usage(cfg.data_dir).free
    except OSError as exc:
        free_bytes = 0
        reasons.append(f"disk_usage check failed: {exc}")
    if free_bytes < cfg.min_free_disk_bytes:
        reasons.append(f"free disk {free_bytes} bytes below minimum {cfg.min_free_disk_bytes}")

    publisher_age = time.monotonic() - ctx.publisher_last_heartbeat
    publisher_ok = ctx.connected.is_set() or buffered >= 0  # buffering counts as "alive"
    if publisher_age > cfg.watchdog_interval_s * 3:
        publisher_ok = False
        reasons.append(f"publisher heartbeat stale ({publisher_age:.1f}s)")

    if not reasons and publisher_ok:
        heartbeat_path.write_text(utcnow_iso(), encoding="utf-8")
        log.info("watchdog: pulse ok (queue=%d buffered=%d free_disk=%dMB connected=%s)",
                  queue_size, buffered, free_bytes // (1024 * 1024), ctx.connected.is_set())
    else:
        log.error("watchdog: UNHEALTHY, withholding pulse: %s", "; ".join(reasons) or "publisher not alive/buffering")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _build_real_sensor_source(cfg: EdgeConfig, sensors) -> CompositeSensorSource:
    """Assembles the real (non-mock) sensor source: loads the three wiring
    maps, splits the manifest three ways by which map claims each
    sensor_id, and fans them out via CompositeSensorSource so the rest of
    the daemon still only ever sees one sensor_source object - exactly
    like it does with MockSensorSource today."""
    modbus_map = load_modbus_map(cfg.modbus_map_path())
    onewire_map = load_onewire_map(cfg.onewire_map_path())
    pms7003_map = load_pms7003_map(cfg.pms7003_map_path())

    modbus_sensors = [s for s in sensors if s.sensor_id in modbus_map]
    onewire_sensors = [s for s in sensors if s.sensor_id in onewire_map]
    pms_sensors = [s for s in sensors if s.sensor_id in pms7003_map]

    claimed = {s.sensor_id for s in modbus_sensors + onewire_sensors + pms_sensors}
    unclaimed = [s for s in sensors if s.sensor_id not in claimed]

    # A sensor tracked in the manifest with interface unset/'unconfirmed'
    # (e.g. the ASAIR O2 sensor - see seed/seed.py) is expected to be
    # unclaimed until its physical bus is decided. Skip it with a loud
    # warning rather than treating it the same as a real sensor that's
    # simply missing from its wiring map by mistake.
    skipped = [s.sensor_id for s in unclaimed if s.interface in (None, "unconfirmed")]
    if skipped:
        log.warning(
            "real sensor source: skipping sensor(s) with unconfirmed interface "
            "(not polled until resolved): %s", skipped,
        )

    misconfigured = [s.sensor_id for s in unclaimed if s.interface not in (None, "unconfirmed")]
    if misconfigured:
        raise SystemExit(
            f"real mode: sensor(s) {misconfigured} declare a real interface in the "
            "`sensors` table but have no entry in the matching wiring map - add them "
            "to edge/modbus_map.json, edge/onewire_map.json or edge/pms7003_map.json "
            "before starting the daemon without --mock."
        )

    log.info(
        "real sensor source: %d modbus, %d 1-wire, %d pms7003, %d unconfirmed (skipped)",
        len(modbus_sensors), len(onewire_sensors), len(pms_sensors), len(skipped),
    )

    return CompositeSensorSource([
        RealModbusPoller(modbus_sensors, modbus_map),
        RealOneWirePoller(onewire_sensors, onewire_map),
        RealPMS7003Poller(pms_sensors, pms7003_map),
    ])


async def main_async(cfg: EdgeConfig) -> None:
    log.info("edge daemon starting: plant_id=%s mock=%s", cfg.plant_id, cfg.mock)

    # Clock gate FIRST, before the manifest load and long before any
    # reading is produced. A Pi has no battery-backed RTC: after a power
    # cut it can boot to 1970, and because this daemon buffers to SQLite
    # and backfills on reconnect, timestamps minted with a wrong clock are
    # durable - they outlive the outage and get replayed into `readings`.
    # Blocking here is the only point at which that is cheap to stop.
    # See edge/clock.py for the three checks and the RTC hardware note.
    clock = ClockGate(cfg.clock_state_path())
    status = clock.check()
    if not status.ok:
        log.error("clock: %s", status)
        log.error(
            "clock: refusing to emit readings with an untrusted clock. Fit a DS3231 "
            "I2C RTC module, or restore NTP, then restart. Waiting for the clock to "
            "become valid rather than exiting, so the unit self-heals when 4G returns."
        )
    backoff = 5.0
    while not status.ok:
        await asyncio.sleep(backoff)
        backoff = min(backoff * 1.5, 300.0)
        status = clock.check()
        if status.ok:
            log.info("clock: recovered - %s", status)
    log.info("clock: %s", status)

    source = PostgresManifestSource(cfg.database_url)
    sensors = load_manifest(cfg.plant_id, source, cfg.manifest_cache_path())
    log.info("manifest: %s", ", ".join(s.sensor_id for s in sensors))

    setpoint_source = MockSetpointSource()

    if cfg.mock:
        sensor_source = MockSensorSource(sensors)
    else:
        sensor_source = _build_real_sensor_source(cfg, sensors)
        await sensor_source.start()

    ctx = Context(cfg)
    await ctx.buffer.open()

    loop = asyncio.get_running_loop()

    poller = loop.create_task(poller_task(ctx, sensor_source, setpoint_source), name="poller")
    publisher = loop.create_task(publisher_task(ctx), name="publisher")
    sync = loop.create_task(sync_task(ctx), name="sync")
    watchdog = loop.create_task(watchdog_task(ctx), name="watchdog")
    background = [publisher, sync, watchdog]

    try:
        await poller  # returns on ctx.shutdown OR a graceful stop-file request
        if not ctx.shutdown.is_set():
            await _wait_for_flush(ctx)
    except asyncio.CancelledError:
        pass
    finally:
        ctx.shutdown.set()
        for t in background:
            t.cancel()
        await asyncio.gather(*background, return_exceptions=True)
        await ctx.buffer.close()
        if not cfg.mock:
            await sensor_source.close()


async def _wait_for_flush(ctx: Context, timeout: float = 30.0) -> None:
    """After a graceful stop request, block until every reading/setpoint the
    Poller ever generated has either been published live or drained from the
    SQLite buffer via backfill - i.e. outbox empty AND buffer empty. Bounded
    by `timeout` so a genuinely stuck publisher can't hang shutdown forever
    (logged loudly if it happens, since that would mean data is stranded)."""
    deadline = time.monotonic() + timeout
    consecutive_empty = 0
    while time.monotonic() < deadline:
        buffered = await ctx.buffer.count()
        if ctx.outbox.qsize() == 0 and buffered == 0:
            consecutive_empty += 1
            # Require two consecutive empty checks (250ms apart) rather than
            # trusting a single snapshot - the publisher can be mid-flight
            # (already pulled items off the outbox, not yet published nor
            # buffered) for a brief window, which would otherwise look
            # falsely "empty" here.
            if consecutive_empty >= 2:
                log.info("flush: outbox and buffer both empty, safe to shut down")
                return
        else:
            consecutive_empty = 0
        await asyncio.sleep(0.25)
    buffered = await ctx.buffer.count()
    log.error("flush: TIMED OUT waiting for drain (outbox=%d buffer=%d) - shutting down anyway",
               ctx.outbox.qsize(), buffered)


def parse_args(argv=None) -> EdgeConfig:
    parser = argparse.ArgumentParser(description="Airthra edge daemon")
    parser.add_argument("--plant-id", required=True)
    parser.add_argument("--mock", action="store_true", help="Use the mock sinusoidal generator instead of real Modbus polling")
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--publish-interval", type=float, default=1.0)
    args = parser.parse_args(argv)

    cfg = EdgeConfig(plant_id=args.plant_id, mock=args.mock)
    cfg.poll_interval_s = args.poll_interval
    cfg.publish_interval_s = args.publish_interval
    return cfg


def main() -> None:
    # WINDOWS QUIRK: paho-mqtt (used under the hood by aiomqtt) registers
    # raw sockets with add_reader()/add_writer(), which asyncio's default
    # ProactorEventLoop on Windows does not implement (NotImplementedError).
    # The fix is the SelectorEventLoop policy, same as documented in
    # aiomqtt's own Windows notes.
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    cfg = parse_args()
    try:
        asyncio.run(main_async(cfg))
    except KeyboardInterrupt:
        log.info("edge daemon: shutdown requested")


if __name__ == "__main__":
    main()
