"""Sensor manifest loading.

The "real" source of truth for a plant's sensor manifest will eventually be
an HTTP call to the platform API (P2+). That API does not exist yet, so for
P1 we read the manifest directly from Postgres `sensors` — but behind a
small `ManifestSource` interface so swapping in an `HttpManifestSource`
later is a one-line change in daemon.py, not a rewrite.

Every successful fetch is cached to a local JSON file
(edge/cache/manifest_<plant_id>.json) so the daemon can still boot (in
degraded/mock mode) even if Postgres/the API is completely unreachable -
e.g. a device that boots before the network is up.
"""
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger("edge.manifest")


@dataclass
class SensorSpec:
    plant_id: str
    sensor_id: str
    tag: str
    kind: str
    unit: str
    min_valid: Optional[float]
    max_valid: Optional[float]
    # 'modbus' | 'onewire' | 'pms7003' | 'unconfirmed' | None (see
    # migrations/versions/0015_sensor_interface.py). None/'unconfirmed'
    # means this sensor is tracked in the manifest but not yet claimed by
    # any real poller - e.g. the ASAIR O2 sensor pending a bus decision.
    interface: Optional[str] = None


class ManifestSource(ABC):
    """Swappable manifest provider. Implement `fetch()` against whatever the
    current source of truth is (Postgres today, an HTTP API later)."""

    @abstractmethod
    def fetch(self, plant_id: str) -> List[SensorSpec]:
        ...


class PostgresManifestSource(ManifestSource):
    """Reads the sensor manifest straight from Postgres `sensors`.

    Uses a plain synchronous psycopg connection deliberately: this call
    happens once at daemon startup (and optionally on periodic refresh), not
    on the hot polling path, so there's no need to drag the async driver in
    here.
    """

    def __init__(self, database_url: str):
        self.database_url = database_url

    def fetch(self, plant_id: str) -> List[SensorSpec]:
        from sqlalchemy import create_engine, text

        engine = create_engine(self.database_url, future=True)
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text(
                        """
                        SELECT plant_id, sensor_id, tag, kind, unit, min_valid, max_valid, interface
                        FROM sensors WHERE plant_id = :p ORDER BY sensor_id
                        """
                    ),
                    {"p": plant_id},
                ).mappings().all()
        finally:
            engine.dispose()
        return [SensorSpec(**dict(r)) for r in rows]


# Placeholder for the future swap-in described above. Not implemented in
# P1 (no such API exists yet) - included so the intended shape is explicit.
class HttpManifestSource(ManifestSource):
    def __init__(self, base_url: str):
        self.base_url = base_url

    def fetch(self, plant_id: str) -> List[SensorSpec]:
        raise NotImplementedError(
            "HttpManifestSource is a P2+ placeholder; the platform API does "
            "not exist yet. Use PostgresManifestSource for now."
        )


def load_manifest(
    plant_id: str, source: ManifestSource, cache_path: Path
) -> List[SensorSpec]:
    """Fetch the manifest from `source`, caching on success. Falls back to
    the local cache (if any) when `source` raises, so the daemon can still
    boot without Postgres/API connectivity. Raises only if both the live
    fetch AND the cache are unavailable - there is nothing to poll then."""
    try:
        sensors = source.fetch(plant_id)
        if not sensors:
            raise RuntimeError(f"manifest fetch for {plant_id!r} returned zero sensors")
        cache_path.write_text(
            json.dumps([asdict(s) for s in sensors], indent=2), encoding="utf-8"
        )
        logger.info("manifest: loaded %d sensors for %s from source, cached to %s",
                     len(sensors), plant_id, cache_path)
        return sensors
    except Exception as exc:  # noqa: BLE001 - deliberately broad: any source failure -> fall back
        logger.warning("manifest: live fetch failed (%s), falling back to cache %s", exc, cache_path)
        if cache_path.exists():
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            sensors = [SensorSpec(**d) for d in data]
            logger.info("manifest: loaded %d sensors for %s from cache", len(sensors), plant_id)
            return sensors
        raise RuntimeError(
            f"manifest unavailable for {plant_id!r}: live source failed ({exc}) "
            f"and no local cache at {cache_path}"
        ) from exc
