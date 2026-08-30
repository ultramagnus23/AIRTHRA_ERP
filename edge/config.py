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


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _default_mqtt_port() -> int:
    # TLS (8883) is the only listener docker-compose.yml exposes publicly -
    # the plaintext dev listener (1883) is bound to 127.0.0.1 on the
    # broker host on purpose (see that file's comments), so a remote Pi
    # can only ever reach 8883. Defaulting the port to match MQTT_USE_TLS
    # means a device only has to flip one env var to go from local-network
    # plaintext testing to a real TLS connection to the VPS.
    if _env_bool("MQTT_USE_TLS"):
        return int(os.environ.get("MQTT_TLS_PORT", "8883"))
    return int(os.environ.get("MQTT_DEV_PORT", "1883"))


@dataclass
class EdgeConfig:
    plant_id: str
    mock: bool = True

    # --- Postgres (manifest source) ---
    database_url: str = field(default_factory=lambda: os.environ.get("DATABASE_URL", ""))

    # --- MQTT ---
    mqtt_host: str = field(default_factory=lambda: os.environ.get("MQTT_HOST", "localhost"))
    mqtt_port: int = field(default_factory=_default_mqtt_port)
    mqtt_username: str = field(default_factory=lambda: os.environ.get("MQTT_EDGE_USERNAME", ""))
    mqtt_password: str = field(default_factory=lambda: os.environ.get("MQTT_EDGE_PASSWORD", ""))

    # --- MQTT TLS ---
    # docker/mosquitto/mosquitto.conf's 8883 listener authenticates the
    # BROKER to the device via the CA cert below (encrypts the transport,
    # proves you're talking to the real broker) and authenticates the
    # DEVICE to the broker via the existing username/password above
    # (require_certificate is false in that config - no client cert
    # required yet). mqtt_client_cert_path/mqtt_client_key_path exist so a
    # future switch to full mTLS (require_certificate true, per-device
    # certs) is a config change, not a code change.
    mqtt_use_tls: bool = field(default_factory=lambda: _env_bool("MQTT_USE_TLS"))
    mqtt_ca_cert_path: str = field(default_factory=lambda: os.environ.get("MQTT_CA_CERT_PATH", ""))
    mqtt_client_cert_path: str = field(default_factory=lambda: os.environ.get("MQTT_CLIENT_CERT_PATH", ""))
    mqtt_client_key_path: str = field(default_factory=lambda: os.environ.get("MQTT_CLIENT_KEY_PATH", ""))
    # Skips server hostname verification against the cert's CN/SAN - only
    # useful when connecting via a bare IP or a hostname that doesn't match
    # what docker/mosquitto/gen_certs.sh signed the dev cert for. Leave off
    # (default) whenever the hostname is right; turning it on silently
    # reduces TLS to "encrypted" without "verified who I'm talking to".
    mqtt_tls_insecure: bool = field(default_factory=lambda: _env_bool("MQTT_TLS_INSECURE"))

    # --- Local debug store + dashboard (edge/local_store.py, edge/dashboard.py) ---
    # A permanent local reading log, independent of cloud/MQTT reachability,
    # bounded by age rather than growing forever - see local_store.py's
    # docstring for why this is a different thing from the SqliteBuffer
    # outbox above. dashboard_task serves a live view of it on this port.
    local_retention_days: float = field(
        default_factory=lambda: float(os.environ.get("LOCAL_RETENTION_DAYS", "7"))
    )
    dashboard_port: int = field(default_factory=lambda: int(os.environ.get("DASHBOARD_PORT", "8080")))

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

    # --- Real-hardware wiring maps (edge/mockgen.py RealModbusPoller etc.) ---
    # Not per-plant: one Pi runs one plant's daemon, and these describe the
    # physical wiring of *that* Pi, so they live at a fixed repo path rather
    # than being keyed by plant_id like the manifest cache above.
    def modbus_map_path(self) -> Path:
        return EDGE_DIR / "modbus_map.json"

    def onewire_map_path(self) -> Path:
        return EDGE_DIR / "onewire_map.json"

    def pms7003_map_path(self) -> Path:
        return EDGE_DIR / "pms7003_map.json"

    def buffer_db_path(self) -> Path:
        return self.data_dir / f"buffer_{self.plant_id}.db"

    def local_store_db_path(self) -> Path:
        return self.data_dir / f"local_readings_{self.plant_id}.db"

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

        # Fail at startup, not several MqttError retries into
        # publisher_task()'s reconnect loop, where "connection failed"
        # gives no hint that the real problem is a missing/wrong cert path.
        if self.mqtt_use_tls and not self.mqtt_ca_cert_path:
            raise SystemExit(
                "MQTT_USE_TLS is set but MQTT_CA_CERT_PATH is not. The dev/pilot "
                "broker uses a self-signed CA (docker/mosquitto/gen_certs.sh) that "
                "isn't in the system trust store, so TLS verification will always "
                "fail without it. Set MQTT_CA_CERT_PATH to that CA's ca.crt."
            )
        if bool(self.mqtt_client_cert_path) != bool(self.mqtt_client_key_path):
            raise SystemExit(
                "MQTT_CLIENT_CERT_PATH and MQTT_CLIENT_KEY_PATH must be set together "
                "(or both left unset) - a client cert without its private key, or "
                "vice versa, can't be used for mTLS."
            )
