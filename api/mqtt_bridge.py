"""Background MQTT subscriber that fans out `plants/{plant_id}/readings`
messages to connected WebSocket clients scoped to that plant.

Runs as a single background task for the whole app (started in the
FastAPI lifespan, api/main.py). If the broker is unreachable (e.g. P1's
mosquitto container isn't up yet, or is mid-restart), this retries with
backoff and never crashes the API - the WS endpoint itself still works
correctly, it will just have nothing to fan out until a broker connection
is established and P1's ingest/edge path starts publishing.
"""
from __future__ import annotations

import asyncio
import logging

import aiomqtt
from fastapi import WebSocket

from . import config

log = logging.getLogger("airthra.mqtt_bridge")


class ConnectionRegistry:
    def __init__(self) -> None:
        self._by_plant: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def register(self, plant_id: str, ws: WebSocket) -> None:
        async with self._lock:
            self._by_plant.setdefault(plant_id, set()).add(ws)

    async def unregister(self, plant_id: str, ws: WebSocket) -> None:
        async with self._lock:
            conns = self._by_plant.get(plant_id)
            if conns is not None:
                conns.discard(ws)
                if not conns:
                    self._by_plant.pop(plant_id, None)

    async def connections_for(self, plant_id: str) -> list[WebSocket]:
        async with self._lock:
            return list(self._by_plant.get(plant_id, ()))


registry = ConnectionRegistry()


def _plant_id_from_topic(topic: str) -> str | None:
    # plants/{plant_id}/readings
    parts = topic.split("/")
    if len(parts) == 3 and parts[0] == "plants" and parts[2] == "readings":
        return parts[1]
    return None


async def run_forever(stop_event: asyncio.Event) -> None:
    """Reconnect loop; returns only when stop_event is set."""
    backoff = 1.0
    while not stop_event.is_set():
        try:
            async with aiomqtt.Client(
                hostname=config.MQTT_HOST,
                port=config.MQTT_DEV_PORT,
                username=config.MQTT_USERNAME,
                password=config.MQTT_PASSWORD,
                identifier="airthra-api-ws-bridge",
            ) as client:
                await client.subscribe(config.MQTT_READINGS_TOPIC_FILTER)
                log.info("mqtt_bridge: connected, subscribed to %s", config.MQTT_READINGS_TOPIC_FILTER)
                backoff = 1.0
                async for message in client.messages:
                    if stop_event.is_set():
                        return
                    topic = str(message.topic)
                    plant_id = _plant_id_from_topic(topic)
                    if plant_id is None:
                        continue
                    payload = message.payload
                    if isinstance(payload, (bytes, bytearray)):
                        payload = payload.decode("utf-8", errors="replace")
                    for ws in await registry.connections_for(plant_id):
                        try:
                            await ws.send_text(payload)
                        except Exception:
                            # Client likely disconnected; the WS handler's
                            # own receive loop will notice and unregister.
                            pass
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # broker down, auth failure, network blip, ...
            log.warning("mqtt_bridge: connection error (%s), retrying in %.1fs", exc, backoff)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=backoff)
            except asyncio.TimeoutError:
                pass
            backoff = min(backoff * 2, 30.0)
