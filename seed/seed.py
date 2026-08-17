#!/usr/bin/env python
"""P0 seed script.

Inserts minimal reference data so the rest of the stack (gate script,
future API/frontend work) has something real to point at:

  - 1 row in `company`         (Airthra Research placeholder)
  - 1 row in `plants`          (goa_pilot_01)
  - a sensor manifest for that plant
  - 5 rows in `materials`

Usage:
    python seed/seed.py

Reads DATABASE_URL from the environment / .env (repo root), same as
migrations/env.py. Safe to re-run: every insert is idempotent
(ON CONFLICT DO NOTHING / DO UPDATE on natural keys).
"""
import os
import sys
import uuid

from dotenv import load_dotenv
from passlib.context import CryptContext
from sqlalchemy import create_engine, text

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT, ".env"))

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL is not set (check .env)", file=sys.stderr)
    sys.exit(1)

# Production guard. This script creates a global_admin account with a
# fixed, publicly-documented password AND resets that password on every
# re-run (see the users UPSERT below) - harmless in dev, catastrophic if
# it is ever pointed at a real deployment, whether by a stray env var, a
# copy-pasted command, or a CI job with the wrong DATABASE_URL.
#
# Refuses to run when APP_ENV names a non-dev environment unless the
# operator explicitly opts in with ALLOW_SEED=1, so the failure mode is a
# hard stop rather than a silently reset admin credential.
_APP_ENV = os.environ.get("APP_ENV", "dev").strip().lower()
_NON_DEV_ENVS = {"prod", "production", "staging", "stage", "uat"}
if _APP_ENV in _NON_DEV_ENVS and os.environ.get("ALLOW_SEED") != "1":
    print(
        f"REFUSING TO SEED: APP_ENV={_APP_ENV!r} is not a development environment.\n"
        "This script creates a global_admin with a fixed dev password and resets it on\n"
        "every run. If you genuinely intend to seed this database, re-run with\n"
        "ALLOW_SEED=1 set.",
        file=sys.stderr,
    )
    sys.exit(1)


COMPANY = {
    "name": "Airthra Research Private Limited",
    "address": "Plot 14, Verna Industrial Estate, Verna, Salcete, Goa 403722, India",
    "gstin": "30ABCDE1234F1Z5",
    "state_code": "30",
    "phone": "+91-832-2345678",
    "email": "ops@airthra.example.com",
}

PLANT = {
    "plant_id": "goa_pilot_01",
    "name": "Goa Pilot Plant 01",
    "lat": 15.3800,
    "lon": 73.9600,
    "ambient_climate": "tropical_coastal",
    "boiler_capacity_tpd": 25.0,
    "fuel_type_primary": "coal",
    "commissioning_date": "2026-06-01",
    "timezone_display": "Asia/Kolkata",
}

# tag, kind, unit, min_valid, max_valid
SENSORS = [
    ("SO2_in", "SO2_in", "ppm", 0, 5000),
    ("SO2_out", "SO2_out", "ppm", 0, 500),
    ("pH", "pH", "pH", 0, 14),
    ("temp_C", "temperature", "C", -10, 200),
    ("level_KOH_tank", "level", "%", 0, 100),
    ("level_K2SO3_tank", "level", "%", 0, 100),
    ("flow", "flow", "m3/h", 0, 500),
]

# name, grade, density_kg_m3, rate_per_kg, hsn
MATERIALS = [
    ("MS Plate", "IS2062 Gr B", 7850, 62.5, "7208"),
    ("SS316 Rod", "ASTM A276 316", 8000, 420.0, "7222"),
    ("MS Pipe", "IS1239 Medium", 7850, 68.0, "7305"),
    ("PVC Pipe", "IS4985 Class 3", 1400, 145.0, "3917"),
    ("Gasket Rubber Sheet", "EPDM 3mm", 1200, 210.0, "4008"),
]

# --- P2: users ---
# Dev-only plaintext password, same convention as the other dev-only
# credentials already committed in this repo (.env's MQTT_*_PASSWORD etc):
# only ever used to derive a bcrypt hash below, never stored in plaintext
# in the database.
_DEV_PASSWORD = "Airthra_Dev_2026!"
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# email, DB role (see users.role CHECK constraint), plant_ids (None => no
# user_plants row, i.e. unrestricted per the global_* role semantics)
USERS = [
    ("operator@goa-pilot.airthra.dev", "plant_operator", [PLANT["plant_id"]]),
    ("admin@airthra.dev", "global_admin", None),
]


def main() -> None:
    engine = create_engine(DATABASE_URL, future=True)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO company (name, address, gstin, state_code, phone, email)
                SELECT :name, :address, :gstin, :state_code, :phone, :email
                WHERE NOT EXISTS (SELECT 1 FROM company)
                """
            ),
            COMPANY,
        )

        conn.execute(
            text(
                """
                INSERT INTO plants (plant_id, name, lat, lon, ambient_climate,
                                     boiler_capacity_tpd, fuel_type_primary,
                                     commissioning_date, timezone_display)
                VALUES (:plant_id, :name, :lat, :lon, :ambient_climate,
                        :boiler_capacity_tpd, :fuel_type_primary,
                        :commissioning_date, :timezone_display)
                ON CONFLICT (plant_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    lat = EXCLUDED.lat,
                    lon = EXCLUDED.lon
                """
            ),
            PLANT,
        )

        for tag, kind, unit, min_valid, max_valid in SENSORS:
            conn.execute(
                text(
                    """
                    INSERT INTO sensors (plant_id, sensor_id, tag, kind, unit, min_valid, max_valid)
                    VALUES (:plant_id, :sensor_id, :tag, :kind, :unit, :min_valid, :max_valid)
                    ON CONFLICT (plant_id, sensor_id) DO UPDATE SET
                        tag = EXCLUDED.tag, kind = EXCLUDED.kind, unit = EXCLUDED.unit,
                        min_valid = EXCLUDED.min_valid, max_valid = EXCLUDED.max_valid
                    """
                ),
                {
                    "plant_id": PLANT["plant_id"],
                    "sensor_id": tag,
                    "tag": tag,
                    "kind": kind,
                    "unit": unit,
                    "min_valid": min_valid,
                    "max_valid": max_valid,
                },
            )

        for name, grade, density, rate, hsn in MATERIALS:
            exists = conn.execute(
                text("SELECT 1 FROM materials WHERE name = :name AND grade = :grade"),
                {"name": name, "grade": grade},
            ).fetchone()
            if not exists:
                conn.execute(
                    text(
                        """
                        INSERT INTO materials (id, name, grade, density_kg_m3, rate_per_kg, hsn)
                        VALUES (:id, :name, :grade, :density, :rate, :hsn)
                        """
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "name": name,
                        "grade": grade,
                        "density": density,
                        "rate": rate,
                        "hsn": hsn,
                    },
                )

        pw_hash = _pwd_context.hash(_DEV_PASSWORD)
        for email, role, plant_ids in USERS:
            existing = conn.execute(
                text("SELECT user_id FROM users WHERE email = :email"), {"email": email}
            ).fetchone()
            if existing:
                user_id = existing[0]
                conn.execute(
                    text("UPDATE users SET pw_hash = :pw_hash, role = :role WHERE user_id = :user_id"),
                    {"pw_hash": pw_hash, "role": role, "user_id": user_id},
                )
            else:
                user_id = str(uuid.uuid4())
                conn.execute(
                    text(
                        """
                        INSERT INTO users (user_id, email, pw_hash, role)
                        VALUES (:user_id, :email, :pw_hash, :role)
                        """
                    ),
                    {"user_id": user_id, "email": email, "pw_hash": pw_hash, "role": role},
                )
            for plant_id in (plant_ids or []):
                conn.execute(
                    text(
                        """
                        INSERT INTO user_plants (user_id, plant_id)
                        VALUES (:user_id, :plant_id)
                        ON CONFLICT (user_id, plant_id) DO NOTHING
                        """
                    ),
                    {"user_id": user_id, "plant_id": plant_id},
                )

    print("Seed complete:")
    print(f"  company:   {COMPANY['name']}")
    print(f"  plant:     {PLANT['plant_id']} ({PLANT['name']})")
    print(f"  sensors:   {len(SENSORS)} for {PLANT['plant_id']}")
    print(f"  materials: {len(MATERIALS)}")
    print(f"  users:     {len(USERS)} (dev password: {_DEV_PASSWORD!r})")


if __name__ == "__main__":
    main()
