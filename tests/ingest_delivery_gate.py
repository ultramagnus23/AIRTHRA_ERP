#!/usr/bin/env python
"""Ingest delivery rules, with no broker or database needed.

A message may be acknowledged only once it is stored, or recorded as a dead
letter because it never can be. Run: python tests/ingest_delivery_gate.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import asyncpg  # noqa: E402

from ingest.config import IngestConfig  # noqa: E402
from ingest import service  # noqa: E402

TOPIC = "plants/p/readings"
GOOD = json.dumps([{"plant_id": "p", "sensor_id": "s", "ts": "2026-01-01T00:00:00+00:00",
                    "value": 1.0, "quality_flag": 0}]).encode()


class FakeManifest:
    def known_sensor(self, plant_id, sensor_id):
        return (plant_id, sensor_id) == ("p", "s")

    def bounds(self, plant_id, sensor_id):
        return (None, None)


class FakeStore:
    def __init__(self, insert_error=None, dead_letter_error=None):
        self.insert_error, self.dead_letter_error = insert_error, dead_letter_error
        self.rows, self.dead = [], []

    async def insert_readings(self, rows):
        if self.insert_error:
            raise self.insert_error
        self.rows += rows

    async def insert_dead_letter(self, plant_id, sensor_id, ts, payload, reason):
        if self.dead_letter_error:
            raise self.dead_letter_error
        self.dead.append(reason)


def process(store, payload, topic=TOPIC):
    asyncio.run(service.process_message(store, FakeManifest(), service.Stats(), topic, payload))


def must_stay_unacknowledged(store, payload):
    try:
        process(store, payload)
    except service.StorageUnavailable:
        return
    raise AssertionError("message would have been acknowledged without being stored")


def main():
    store = FakeStore()
    process(store, GOOD)
    assert len(store.rows) == 1 and not store.dead

    # Temporary failures: keep the message.
    for error in (ConnectionRefusedError(), asyncpg.InterfaceError("pool is closed"),
                  asyncpg.CannotConnectNowError("starting up"), asyncio.TimeoutError()):
        must_stay_unacknowledged(FakeStore(insert_error=error), GOOD)

    # Messages that can never be stored: dead-letter, then acknowledge.
    for payload in (b'[{"kind": "reading"}]', b"[1, 2]"):
        store = FakeStore()
        process(store, payload, "plants/p/backfill" if b"kind" in payload else TOPIC)
        assert store.dead == ["unprocessable"], store.dead
    store = FakeStore(insert_error=asyncpg.DataError("bad value"))
    process(store, GOOD)
    assert store.dead == ["unprocessable"]

    # A dead letter that cannot be written is also kept.
    must_stay_unacknowledged(FakeStore(dead_letter_error=ConnectionRefusedError()), b"[1]")

    # The client keeps its session and leaves acknowledging to us.
    async def client_settings():
        client = service.make_client(IngestConfig())
        assert client._client._clean_session is False
        assert client._client._manual_ack is True

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(client_settings())
    print("ingest delivery: all assertions passed")


if __name__ == "__main__":
    main()
