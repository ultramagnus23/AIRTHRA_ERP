"""Edge daemon configuration.

Loads connection info from .env (repo root) plus CLI overrides. Kept
separate from ingest/config.py deliberately: the edge daemon and the ingest
service are two independent OS processes (per the P1 spec) and should not
share import-time state.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

EDGE_DIR = Path(__file__).resolve().parent
DEFAULT_CACHE_DIR = EDGE_DIR / "cache"
DEFAULT_DATA_DIR = EDGE_DIR / "data"


@dataclass
class EdgeConfig:
    plant_id: str
    mock: bool = True

    # --- Postgres (manifest source) ---
    database_url: str = field(default_factory=lambda: os.environ.get("DATABASE_URL", ""))

    # --- MQTT ---
    mqtt_host: str = field(default_factory=lambda: os.environ.get("MQTT_HOST", "localhost"))
    mqtt_port: int = field(default_factory=lambda: int(os.environ.get("MQTT_DEV_PORT", "1883")))
    mqtt_username: str = field(default_factory=lambda: os.environ.get("MQTT_EDGE_USERNAME", ""))
    mqtt_password: str = field(default_factory=lambda: os.environ.get("MQTT_EDGE_PASSWORD", ""))

    # --- Timing ---
    poll_interval_s: float = 1.0
    publish_interval_s: float = 1.0
    watchdog_interval_s: float = 10.0
    mqtt_reconnect_delay_s: float = 2.0
    read_timeout_s: float = 2.0  # per-read timeout budget (simulated in --mock)

    # --- Sync (backfill drain) ---
    sync_chunk_size: int = 500
    sync_idle_delay_s: float = 1.0  # lower priority than live polling/publishing

    # --- Watchdog thresholds ---
    max_queue_size: int = 20_000
    max_poller_silence_s: float = 5.0
    min_free_disk_bytes: int = 50 * 1024 * 1024  # 50 MiB

    # --- Paths ---
    cache_dir: Path = field(default_factory=lambda: DEFAULT_CACHE_DIR)
    data_dir: Path = field(default_factory=lambda: DEFAULT_DATA_DIR)

    def manifest_cache_path(self) -> Path:
        return self.cache_dir / f"manifest_{self.plant_id}.json"

    def buffer_db_path(self) -> Path:
        return self.data_dir / f"buffer_{self.plant_id}.db"

    def heartbeat_path(self) -> Path:
        return self.data_dir / f"watchdog_{self.plant_id}.heartbeat"

    def stats_path(self) -> Path:
        return self.data_dir / f"stats_{self.plant_id}.json"

    def clock_state_path(self) -> Path:
        """Monotonic clock watermark - see edge/clock.py. Lives in data_dir
        (the persistent SSD) alongside the buffer, deliberately NOT in
        cache_dir: losing it silently disables regression protection."""
        return self.data_dir / f"clock_{self.plant_id}.json"

    def stop_request_path(self) -> Path:
        """Filesystem-based graceful-stop trigger. Windows subprocess
        signaling (SIGTERM/CTRL_BREAK) is unreliable to deliver cleanly into
        an asyncio SelectorEventLoop from a controlling test script, so
        tests/p1_gate.py requests a graceful stop by creating this file
        instead of killing the process outright - see poller_task() in
        daemon.py, which checks for it once per poll cycle and, on seeing
        it, stops generating new readings but leaves publisher/sync running
        until the outbox and SQLite buffer are both fully flushed. This is
        what makes "zero gaps" a meaningful, race-free assertion in the gate
        script instead of an artifact of exactly when the process happened
        to be killed."""
        return self.data_dir / f"stop_{self.plant_id}.request"

    def __post_init__(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
