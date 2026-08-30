"""Permanent local reading log, separate from edge/buffer.py's SqliteBuffer.

buffer.py exists purely to survive MQTT outages - it holds only
not-yet-published data and empties out once drained. This module is a
different thing: a rolling local history of EVERY reading the poller ever
produces, written unconditionally regardless of MQTT connectivity, so
someone standing at the Pi can see recent values and history without any
network path to the cloud at all. It is redundant with the cloud
Postgres copy by design - a network outage or a cloud-side problem still
leaves a usable local record, and vice versa.

Bounded by age, not row count: old rows past LOCAL_RETENTION_DAYS (see
EdgeConfig) are deleted as new ones arrive, so disk usage stays flat
indefinitely instead of growing forever - the "oldest data gets deleted,
newest data gets kept" rule.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

import aiosqlite

logger = logging.getLogger("edge.local_store")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS local_readings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    plant_id      TEXT NOT NULL,
    sensor_id     TEXT NOT NULL,
    ts            TEXT NOT NULL,
    value         REAL,
    quality_flag  INTEGER NOT NULL,
    -- 'mock' (edge/mockgen.py's simulator) or 'real' (an actual poller
    -- reading physical hardware) - see daemon.py's _poll_once(), which
    -- sets this from cfg.mock. Exists so nobody has to guess, from the
    -- dashboard, whether what they're looking at is simulated or real.
    source        TEXT NOT NULL DEFAULT 'real'
);
CREATE INDEX IF NOT EXISTS idx_local_readings_ts ON local_readings(ts);
CREATE INDEX IF NOT EXISTS idx_local_readings_sensor ON local_readings(sensor_id, id);
"""


class LocalReadingsStore:
    def __init__(self, db_path: Path, retention_days: float = 7.0):
        self.db_path = db_path
        self.retention_days = retention_days
        self._conn: Optional[aiosqlite.Connection] = None

    async def open(self) -> None:
        self._conn = await aiosqlite.connect(str(self.db_path))
        await self._conn.execute("PRAGMA journal_mode=WAL;")
        await self._conn.execute("PRAGMA synchronous=NORMAL;")
        await self._conn.executescript(_SCHEMA)
        await self._conn.commit()
        # Migration for DBs created before the `source` column existed -
        # CREATE TABLE IF NOT EXISTS above is a no-op on an already-existing
        # table, so an ALTER is needed to backfill it on those files.
        cursor = await self._conn.execute("PRAGMA table_info(local_readings)")
        columns = {row[1] for row in await cursor.fetchall()}
        await cursor.close()
        if "source" not in columns:
            await self._conn.execute(
                "ALTER TABLE local_readings ADD COLUMN source TEXT NOT NULL DEFAULT 'real'"
            )
            await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def insert_many(self, readings: List[dict]) -> None:
        """readings: list of {plant_id, sensor_id, ts, value, quality_flag,
        source} dicts - the exact same shape _poll_once() already builds
        for the MQTT outbox, so the caller doesn't need to build anything
        new."""
        if not readings:
            return
        assert self._conn is not None
        await self._conn.executemany(
            "INSERT INTO local_readings (plant_id, sensor_id, ts, value, quality_flag, source) "
            "VALUES (:plant_id, :sensor_id, :ts, :value, :quality_flag, :source)",
            readings,
        )
        # Prune every insert batch (every poll cycle, ~1s) rather than on a
        # separate timer - cheap since it's an indexed range delete, and it
        # means disk usage never has a window where it's unboundedly ahead
        # of the retention window.
        cutoff = (datetime.now(timezone.utc) - timedelta(days=self.retention_days)).isoformat()
        await self._conn.execute("DELETE FROM local_readings WHERE ts < ?", (cutoff,))
        await self._conn.commit()

    async def latest_per_sensor(self) -> List[Dict]:
        """One row per sensor_id: its most recent reading. Powers the local
        dashboard's live table."""
        assert self._conn is not None
        cursor = await self._conn.execute(
            """
            SELECT r.sensor_id, r.ts, r.value, r.quality_flag, r.source
            FROM local_readings r
            INNER JOIN (
                SELECT sensor_id, MAX(id) AS max_id FROM local_readings GROUP BY sensor_id
            ) latest ON r.sensor_id = latest.sensor_id AND r.id = latest.max_id
            ORDER BY r.sensor_id
            """
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [
            {"sensor_id": row[0], "ts": row[1], "value": row[2], "quality_flag": row[3], "source": row[4]}
            for row in rows
        ]

    async def history(self, sensor_id: str, limit: int = 200) -> List[Dict]:
        """Most recent `limit` readings for one sensor, newest first -
        for a debugging person who wants "what did this probe do
        recently" without any cloud/network dependency at all."""
        assert self._conn is not None
        cursor = await self._conn.execute(
            "SELECT ts, value, quality_flag, source FROM local_readings "
            "WHERE sensor_id = ? ORDER BY id DESC LIMIT ?",
            (sensor_id, limit),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [
            {"ts": row[0], "value": row[1], "quality_flag": row[2], "source": row[3]}
            for row in rows
        ]

    async def export_all(self, start: Optional[str] = None, end: Optional[str] = None) -> List[Dict]:
        """Rows currently retained (bounded by retention_days, so this is
        never unbounded regardless of range), oldest first - backs the
        dashboard's "download history" button. start/end are ISO timestamp
        strings (inclusive/exclusive respectively); either or both may be
        omitted to leave that side of the range open."""
        assert self._conn is not None
        clauses = []
        params: List[str] = []
        if start:
            clauses.append("ts >= ?")
            params.append(start)
        if end:
            clauses.append("ts <= ?")
            params.append(end)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        cursor = await self._conn.execute(
            f"SELECT plant_id, sensor_id, ts, value, quality_flag, source "
            f"FROM local_readings {where} ORDER BY id ASC",
            params,
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [
            {
                "plant_id": row[0],
                "sensor_id": row[1],
                "ts": row[2],
                "value": row[3],
                "quality_flag": row[4],
                "source": row[5],
            }
            for row in rows
        ]

    async def count(self) -> int:
        assert self._conn is not None
        cursor = await self._conn.execute("SELECT COUNT(*) FROM local_readings")
        row = await cursor.fetchone()
        await cursor.close()
        return int(row[0]) if row else 0
