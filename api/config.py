"""Environment/config loading for the P2 API.

Reads the same repo-root .env used by migrations/seed (via python-dotenv),
same convention as tests/p0_gate.py and seed/seed.py.
"""
from __future__ import annotations

import os

from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT, ".env"))


def _require(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(
            f"{name} is not set (check .env) - required to start the P2 API"
        )
    return val


# --- Postgres ---
DATABASE_URL = _require("DATABASE_URL")
ASYNC_DATABASE_URL = _require("ASYNC_DATABASE_URL")

PG_TENANT_ROLE = os.environ.get("PG_TENANT_ROLE", "airthra_tenant")
PG_TENANT_PASSWORD = os.environ.get("PG_TENANT_PASSWORD", "change_me_dev_only_tenant")
PG_GLOBAL_ROLE = os.environ.get("PG_GLOBAL_ROLE", "airthra_global")
PG_GLOBAL_PASSWORD = os.environ.get("PG_GLOBAL_PASSWORD", "change_me_dev_only_global")

# --- JWT ---
JWT_SECRET = _require("JWT_SECRET")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.environ.get("JWT_EXPIRE_MINUTES", "480"))

# --- MQTT (live WS fan-out; broker owned/run by P1) ---
MQTT_HOST = os.environ.get("MQTT_HOST", "localhost")
MQTT_DEV_PORT = int(os.environ.get("MQTT_DEV_PORT", "1883"))
# Reuses the ingest service's MQTT credentials for the API's read-only
# subscriber. There is no per-service ACL in docker/mosquitto (only two
# accounts exist: the edge device and ingest_svc; see docker/mosquitto/
# passwd), and mosquitto.conf/passwd are P1-owned, so rather than add a
# third mosquitto account here, the API subscribes using ingest_svc's
# creds - it only ever *subscribes*, never publishes, so this does not
# widen ingest_svc's effective permissions in any observable way.
MQTT_USERNAME = os.environ.get("MQTT_INGEST_USERNAME")
MQTT_PASSWORD = os.environ.get("MQTT_INGEST_PASSWORD")
MQTT_READINGS_TOPIC_FILTER = "plants/+/readings"

# --- API server ---
API_HOST = os.environ.get("API_HOST", "127.0.0.1")
API_PORT = int(os.environ.get("API_PORT", "8000"))

# Comma-separated list of origins allowed to make credentialed browser
# requests. Defaults to the local Next.js dev server so a fresh checkout
# works with no config; a real deployment MUST set CORS_ALLOWED_ORIGINS to
# its own frontend origin. Deliberately parsed as an explicit list rather
# than supporting "*" - allow_credentials=True with a wildcard origin is
# rejected by browsers anyway, and accepting the string would invite
# someone to "fix" a prod CORS error by opening it up completely.
CORS_ALLOWED_ORIGINS = [
    o.strip()
    for o in os.environ.get("CORS_ALLOWED_ORIGINS", "http://localhost:3000").split(",")
    if o.strip()
]
