"""SQLite (WAL mode) buffer used when the MQTT broker is unreachable.

Publisher writes to it (batched inserts) instead of dropping data. Sync
drains it oldest-first in chunks, deleting each chunk only after the
corresponding backfill publish has been QoS1-acknowledged.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import List, Tuple

import aiosqlite

logger = logging.getLogger("edge.buffer")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS buffer (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL CHECK (kind IN ('reading', 'setpoint')),
    payload     TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
"""


class SqliteBuffer:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def open(self) -> None:
        self._conn = await aiosqlite.connect(str(self.db_path))
        await self._conn.execute("PRAGMA journal_mode=WAL;")
        await self._conn.execute("PRAGMA synchronous=NORMAL;")
        await self._conn.executescript(_SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def put_many(self, items: List[Tuple[str, dict, str]]) -> None:
        """items: list of (kind, payload_dict, created_at_iso)."""
        if not items:
            return
        assert self._conn is not None
        await self._conn.executemany(
            "INSERT INTO buffer (kind, payload, created_at) VALUES (?, ?, ?)",
            [(kind, json.dumps(payload), created_at) for kind, payload, created_at in items],
        )
        await self._conn.commit()

    async def peek_chunk(self, limit: int) -> List[Tuple[int, str, dict]]:
        """Oldest-first chunk, NOT deleted yet. Returns (id, kind, payload)."""
        assert self._conn is not None
        cursor = await self._conn.execute(
            "SELECT id, kind, payload FROM buffer ORDER BY id ASC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [(row[0], row[1], json.loads(row[2])) for row in rows]

    async def delete_ids(self, ids: List[int]) -> None:
        if not ids:
            return
        assert self._conn is not None
        qmarks = ",".join("?" for _ in ids)
        await self._conn.execute(f"DELETE FROM buffer WHERE id IN ({qmarks})", ids)
        await self._conn.commit()

    async def count(self) -> int:
        assert self._conn is not None
        cursor = await self._conn.execute("SELECT COUNT(*) FROM buffer")
        row = await cursor.fetchone()
        await cursor.close()
        return int(row[0]) if row else 0
