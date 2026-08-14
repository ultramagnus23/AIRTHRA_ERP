"""Ingest service configuration.

Independent of edge/config.py on purpose - the ingest service is a
separate OS process per the P1 spec.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _global_role_dsn() -> str:
    """Builds an asyncpg DSN using the airthra_global (BYPASSRLS) role,
    reusing DATABASE_URL for host/port/db. The ingest service writes across
    every plant (readings, dead_letter_readings, setpoint_changes) so it
    authenticates as the global service role rather than a tenant-scoped
    one - same pattern the P0 gate script uses for admin-level access.
    """
    base = os.environ.get("DATABASE_URL", "")
    if not base:
        return ""
    url = make_url(base)
    role = os.environ.get("PG_GLOBAL_ROLE", "airthra_global")
    password = os.environ.get("PG_GLOBAL_PASSWORD", "change_me_dev_only_global")
    url = url.set(username=role, password=password, drivername="postgresql")
    return url.render_as_string(hide_password=False)


@dataclass
class IngestConfig:
    # --- Postgres ---
    dsn: str = field(default_factory=_global_role_dsn)
    manifest_refresh_s: float = 30.0

    # --- MQTT ---
    mqtt_host: str = field(default_factory=lambda: os.environ.get("MQTT_HOST", "localhost"))
    mqtt_port: int = field(default_factory=lambda: int(os.environ.get("MQTT_DEV_PORT", "1883")))
    mqtt_username: str = field(default_factory=lambda: os.environ.get("MQTT_INGEST_USERNAME", ""))
    mqtt_password: str = field(default_factory=lambda: os.environ.get("MQTT_INGEST_PASSWORD", ""))
    mqtt_reconnect_delay_s: float = 2.0

    readings_topic: str = "plants/+/readings"
    backfill_topic: str = "plants/+/backfill"
    setpoints_topic: str = "plants/+/setpoints"
