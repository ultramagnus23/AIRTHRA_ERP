#!/usr/bin/env python
"""Airthra ingest service (P1).

Independent asyncio process that:
  - Subscribes to plants/+/readings, plants/+/backfill and plants/+/setpoints
    on the MQTT broker.
  - Validates each incoming reading against the `sensors` manifest in
    Postgres (known plant_id/sensor_id, value within range when the value
    wasn't already flagged by the edge daemon).
  - Bulk-inserts into `readings` with INSERT ... ON CONFLICT
    (plant_id, sensor_id, ts) DO NOTHING for idempotency.
  - Rejected/invalid payloads go to `dead_letter_readings` (added in
    migrations/versions/0002_dead_letter.py).
  - setpoint_changes messages are validated + idempotently inserted too
    (app-level dedupe on (plant_id, device, register, ts), since that
    table's PK is a uuid surrogate key with no natural-key unique
    constraint).

Usage:
    python ingest/service.py

Reads Postgres/MQTT connection info from .env (repo root).
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import aiomqtt  # noqa: E402
import asyncpg  # noqa: E402

from ingest.config import IngestConfig  # noqa: E402
from shared import quality as q  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)-16s %(message)s",
)
log = logging.getLogger("ingest.service")


class Manifest:
    """In-memory cache of {(plant_id, sensor_id): (min_valid, max_valid)},
    refreshed periodically from Postgres. Also tracks known plant_ids so
    setpoint messages (which reference a plant but not a sensor) can be
    validated."""

    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool
        self._sensors: Dict[Tuple[str, str], Tuple[Optional[float], Optional[float]]] = {}
        self._plants: set = set()

    async def refresh(self) -> None:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT plant_id, sensor_id, min_valid, max_valid FROM sensors")
            plant_rows = await conn.fetch("SELECT plant_id FROM plants")
        self._sensors = {(r["plant_id"], r["sensor_id"]): (r["min_valid"], r["max_valid"]) for r in rows}
        self._plants = {r["plant_id"] for r in plant_rows}
        log.info("manifest: refreshed (%d sensors, %d plants)", len(self._sensors), len(self._plants))

    def known_sensor(self, plant_id: str, sensor_id: str) -> bool:
        return (plant_id, sensor_id) in self._sensors

    def known_plant(self, plant_id: str) -> bool:
        return plant_id in self._plants

    def bounds(self, plant_id: str, sensor_id: str) -> Tuple[Optional[float], Optional[float]]:
        return self._sensors.get((plant_id, sensor_id), (None, None))


class Store:
    """Postgres access: idempotent bulk inserts + dead-lettering."""

    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def insert_readings(self, rows: List[dict]) -> int:
        """rows: valid reading dicts (already validated). Returns count
        attempted (not necessarily inserted - ON CONFLICT DO NOTHING makes
        duplicates silently no-op, which is the idempotency contract)."""
        if not rows:
            return 0
        records = [
            (r["plant_id"], r["sensor_id"], r["_ts_dt"], r["value"], q.to_db_enum(r["quality_flag"]))
            for r in rows
        ]
        async with self._pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO readings (plant_id, sensor_id, ts, value, quality_flag)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (plant_id, sensor_id, ts) DO NOTHING
                """,
                records,
            )
        return len(records)

    async def insert_dead_letter(self, plant_id: Optional[str], sensor_id: Optional[str],
                                  ts: Optional[datetime], raw_payload: dict, reason: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO dead_letter_readings (plant_id, sensor_id, ts, raw_payload, reason)
                VALUES ($1, $2, $3, $4::jsonb, $5)
                """,
                plant_id, sensor_id, ts, json.dumps(raw_payload), reason,
            )

    async def insert_setpoint_change(self, change: dict) -> bool:
        """Application-level idempotent insert on (plant_id, device,
        register, ts) - setpoint_changes.id is a uuid surrogate key with no
        natural-key unique constraint, so we dedupe here instead of relying
        on ON CONFLICT. Returns True if inserted, False if it was already
        present (duplicate, silently skipped - same idempotency contract as
        readings). Runs inside a transaction to close the check-then-insert
        race (safe here since this is a single ingest process / connection
        at a time)."""
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                existing = await conn.fetchval(
                    """
                    SELECT 1 FROM setpoint_changes
                    WHERE plant_id = $1 AND device = $2 AND register = $3 AND ts = $4
                    """,
                    change["plant_id"], change["device"], change["register"], change["_ts_dt"],
                )
                if existing:
                    return False
                await conn.execute(
                    """
                    INSERT INTO setpoint_changes (plant_id, device, register, old_value, new_value, ts, source)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    change["plant_id"], change["device"], change["register"],
                    change.get("old_value"), change.get("new_value"), change["_ts_dt"], change["source"],
                )
                return True


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _parse_ts(raw) -> Optional[datetime]:
    if not isinstance(raw, str):
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def validate_reading(payload: dict, manifest: Manifest) -> Tuple[bool, str]:
    """Returns (ok, reason). reason is '' when ok."""
    if not isinstance(payload, dict):
        return False, "payload_not_object"
    plant_id, sensor_id = payload.get("plant_id"), payload.get("sensor_id")
    if not plant_id or not sensor_id:
        return False, "missing_plant_or_sensor_id"
    if not manifest.known_sensor(plant_id, sensor_id):
        return False, "unknown_sensor"

    ts_dt = _parse_ts(payload.get("ts"))
    if ts_dt is None:
        return False, "invalid_ts"
    payload["_ts_dt"] = ts_dt

    flag = payload.get("quality_flag")
    if not isinstance(flag, int) or flag not in (q.GOOD, q.COMM_ERROR, q.OUT_OF_RANGE, q.FROZEN, q.IMPUTED):
        return False, "invalid_quality_flag"

    value = payload.get("value")
    if value is not None and not isinstance(value, (int, float)):
        return False, "non_numeric_value"

    # Only enforce the sensor's [min_valid, max_valid] range for readings the
    # edge daemon itself claims are good - anything already flagged (comm
    # error/out-of-range/frozen) is expected to look "wrong" and is exactly
    # what quality_flag exists to communicate; range-checking it again would
    # just reject legitimate fault telemetry.
    if flag == q.GOOD and value is not None:
        lo, hi = manifest.bounds(plant_id, sensor_id)
        if lo is not None and value < lo:
            return False, "value_below_min_valid"
        if hi is not None and value > hi:
            return False, "value_above_max_valid"

    return True, ""


def validate_setpoint(payload: dict, manifest: Manifest) -> Tuple[bool, str]:
    if not isinstance(payload, dict):
        return False, "payload_not_object"
    plant_id = payload.get("plant_id")
    if not plant_id or not manifest.known_plant(plant_id):
        return False, "unknown_plant"
    if not payload.get("device") or not payload.get("register"):
        return False, "missing_device_or_register"
    if payload.get("source") not in ("manual_panel", "api"):
        return False, "invalid_source"
    ts_dt = _parse_ts(payload.get("ts"))
    if ts_dt is None:
        return False, "invalid_ts"
    payload["_ts_dt"] = ts_dt
    return True, ""


# ---------------------------------------------------------------------------
# Message handling
# ---------------------------------------------------------------------------

class Stats:
    def __init__(self):
        self.readings_ok = 0
        self.readings_dead = 0
        self.setpoints_ok = 0
        self.setpoints_dup = 0
        self.setpoints_dead = 0

    def __str__(self):
        return (f"readings_ok={self.readings_ok} readings_dead={self.readings_dead} "
                f"setpoints_ok={self.setpoints_ok} setpoints_dup={self.setpoints_dup} "
                f"setpoints_dead={self.setpoints_dead}")


async def handle_reading_batch(store: Store, manifest: Manifest, stats: Stats, readings: List[dict]) -> None:
    valid, dead = [], []
    for r in readings:
        ok, reason = validate_reading(r, manifest)
        (valid if ok else dead).append((r, reason))

    if valid:
        await store.insert_readings([r for r, _ in valid])
        stats.readings_ok += len(valid)
    for r, reason in dead:
        await store.insert_dead_letter(
            r.get("plant_id"), r.get("sensor_id"), r.get("_ts_dt"), _strip_internal(r), reason
        )
        stats.readings_dead += 1
        log.warning("dead-letter reading: %s (%s)", reason, {k: v for k, v in r.items() if not k.startswith("_")})


async def handle_setpoint(store: Store, manifest: Manifest, stats: Stats, sp: dict) -> None:
    ok, reason = validate_setpoint(sp, manifest)
    if not ok:
        await store.insert_dead_letter(sp.get("plant_id"), None, None, _strip_internal(sp), reason)
        stats.setpoints_dead += 1
        log.warning("dead-letter setpoint: %s (%s)", reason, {k: v for k, v in sp.items() if not k.startswith("_")})
        return
    inserted = await store.insert_setpoint_change(sp)
    if inserted:
        stats.setpoints_ok += 1
    else:
        stats.setpoints_dup += 1


def _strip_internal(d: dict) -> dict:
    return {k: v for k, v in d.items() if not k.startswith("_")}


async def handle_message(store: Store, manifest: Manifest, stats: Stats, topic: str, raw_payload: bytes) -> None:
    try:
        body = json.loads(raw_payload)
    except (json.JSONDecodeError, UnicodeDecodeError):
        await store.insert_dead_letter(None, None, None, {"raw": raw_payload.decode("utf-8", "replace")}, "invalid_json")
        return

    parts = topic.split("/")
    kind_from_topic = parts[2] if len(parts) >= 3 else ""

    if kind_from_topic == "readings":
        readings = body if isinstance(body, list) else [body]
        await handle_reading_batch(store, manifest, stats, readings)
    elif kind_from_topic == "setpoints":
        await handle_setpoint(store, manifest, stats, body)
    elif kind_from_topic == "backfill":
        envelope = body if isinstance(body, list) else [body]
        readings = [item["data"] for item in envelope if isinstance(item, dict) and item.get("kind") == "reading"]
        setpoints = [item["data"] for item in envelope if isinstance(item, dict) and item.get("kind") == "setpoint"]
        if readings:
            await handle_reading_batch(store, manifest, stats, readings)
        for sp in setpoints:
            await handle_setpoint(store, manifest, stats, sp)
    else:
        await store.insert_dead_letter(None, None, None, {"topic": topic, "body": body}, "unrecognized_topic")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def manifest_refresh_loop(manifest: Manifest, interval_s: float, shutdown: asyncio.Event) -> None:
    while not shutdown.is_set():
        try:
            await manifest.refresh()
        except Exception as exc:  # noqa: BLE001
            log.error("manifest: refresh failed (%s), keeping previous manifest", exc)
        await asyncio.sleep(interval_s)


async def main_async(cfg: IngestConfig) -> None:
    log.info("ingest service starting")
    pool = await asyncpg.create_pool(dsn=cfg.dsn, min_size=1, max_size=5)
    manifest = Manifest(pool)
    await manifest.refresh()
    store = Store(pool)
    stats = Stats()
    shutdown = asyncio.Event()

    refresh_task = asyncio.create_task(manifest_refresh_loop(manifest, cfg.manifest_refresh_s, shutdown))

    try:
        while True:
            try:
                async with aiomqtt.Client(
                    hostname=cfg.mqtt_host,
                    port=cfg.mqtt_port,
                    username=cfg.mqtt_username or None,
                    password=cfg.mqtt_password or None,
                    identifier="ingest-service",
                ) as client:
                    log.info("connected to mqtt://%s:%d, subscribing", cfg.mqtt_host, cfg.mqtt_port)
                    await client.subscribe(cfg.readings_topic, qos=1)
                    await client.subscribe(cfg.backfill_topic, qos=1)
                    await client.subscribe(cfg.setpoints_topic, qos=1)
                    async for message in client.messages:
                        await handle_message(store, manifest, stats, str(message.topic), message.payload)
                        if (stats.readings_ok + stats.readings_dead) % 50 == 0:
                            log.info("ingest stats: %s", stats)
            except aiomqtt.MqttError as exc:
                log.warning("mqtt connection lost/failed (%s), retrying in %.1fs", exc, cfg.mqtt_reconnect_delay_s)
                await asyncio.sleep(cfg.mqtt_reconnect_delay_s)
    finally:
        shutdown.set()
        refresh_task.cancel()
        await asyncio.gather(refresh_task, return_exceptions=True)
        await pool.close()


def main() -> None:
    # WINDOWS QUIRK: see edge/daemon.py's main() for why this is required -
    # paho-mqtt (under aiomqtt) needs add_reader()/add_writer(), which the
    # default ProactorEventLoop on Windows does not implement.
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    cfg = IngestConfig()
    try:
        asyncio.run(main_async(cfg))
    except KeyboardInterrupt:
        log.info("ingest service: shutdown requested")


if __name__ == "__main__":
    main()
