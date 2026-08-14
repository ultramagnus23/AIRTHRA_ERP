# Airthra Platform - P0 (Foundations)

Combined Machine Data Platform + ERP for Flue Gas Desulfurization
hardware-as-a-service. This is **P0 only**: infrastructure, database schema,
RLS, seed data, and a gate script. No API endpoints, edge daemon, or
frontend yet (P1+).

This README is meant to work standalone from a fresh `git clone` - if any
step here doesn't work on a clean checkout, that's a bug.

## Prerequisites

- Docker + Docker Compose (v2, `docker compose ...`)
- Python 3.11+
- (optional, for TLS cert generation) `openssl` on PATH - available by
  default in Git Bash / WSL / most Linux images

## 1. Configure environment

```bash
cp .env.example .env
# edit .env if you want non-default dev credentials/ports
```

`.env` is git-ignored. Never put real secrets in `.env.example`.

## 2. Generate Mosquitto dev certs (optional but recommended)

```bash
bash docker/mosquitto/gen_certs.sh
```

Writes a self-signed local CA + server cert to `docker/mosquitto/certs/`
(git-ignored). The TLS listener (`8883`) needs these to start; if you skip
this step, use the **dev-only plaintext listener on `1883`** instead (see
`docker/mosquitto/mosquitto.conf` - comment it out before anything beyond
local dev).

Per-device MQTT credentials live in `docker/mosquitto/passwd`
(mosquitto's own hashed-password format, generated with `mosquitto_passwd`).
The repo ships this file empty. Add a device:

```bash
bash scripts/mosquitto_add_user.sh <device_id> <password>
# or, once mosquitto is already running:
docker compose exec mosquitto mosquitto_passwd -b /mosquitto/config/passwd <device_id> <password>
docker compose restart mosquitto
```

## 3. Start the stack

```bash
docker compose up -d
```

Services: `postgres` (TimescaleDB, 5432), `mosquitto` (8883 TLS / 1883 dev
plaintext / 9001 websockets), `caddy` (80/443, reverse-proxies `/api/*` to
the future `api` service and everything else to the future `frontend`
service), `grafana` (3001, auto-provisioned Postgres datasource), `minio`
(9000 S3 API / 9090 console) plus a one-shot `minio-init` that creates the
`airthra` bucket.

Wait for postgres to be healthy (compose `depends_on: condition:
service_healthy` handles this for `grafana`; check manually otherwise):

```bash
docker compose ps
```

## 4. Python environment

```bash
python -m venv .venv
# Windows:
.venv\Scripts\pip install -r requirements.txt
# macOS/Linux:
source .venv/bin/activate && pip install -r requirements.txt
```

## 5. Run migrations

```bash
# Windows
.venv\Scripts\python -m alembic upgrade head
# macOS/Linux
.venv/bin/python -m alembic upgrade head
```

This creates the full P0 schema (PRD section 4: shared, machine-data
hypertables + continuous aggregates + compression/retention policies, ERP
procurement/engineering, ERP inventory/production/QC, logistics), the
`airthra_tenant` / `airthra_global` Postgres roles, and Row-Level-Security
policies on every plant-scoped table. Details, including exactly which
tables have RLS and why some don't: `migrations/README.md`.

Safe to run repeatedly (`alembic upgrade head` again is a no-op).

## 6. Seed reference data

```bash
.venv\Scripts\python seed\seed.py     # Windows
.venv/bin/python seed/seed.py         # macOS/Linux
```

Inserts: the Airthra company record, plant `goa_pilot_01` (Goa, India),
its sensor manifest (SO2 in/out, pH, temp, KOH/K2SO3 tank levels, flow),
and 5 reference materials (MS plate, SS316 rod, MS pipe, PVC pipe, EPDM
gasket sheet). Safe to re-run - upserts on natural keys, no duplicates.

## 7. Run the P0 gate

```powershell
# PowerShell (primary)
.\tests\p0_gate.ps1
```

```bash
# portable
python tests/p0_gate.py
```

Proves, with clear PASS/FAIL output and a non-zero exit code on failure:

1. `alembic upgrade head` run twice in a row is clean/idempotent.
2. Row-Level Security actually isolates tenants: `airthra_tenant` scoped
   to one plant cannot see another plant's rows; `airthra_global`
   (`BYPASSRLS`) can see everything.

## Repo layout

```
docker-compose.yml          # postgres, mosquitto, caddy, grafana, minio
docker/mosquitto/           # TLS conf, cert-gen script, per-device passwd file
docker/caddy/Caddyfile      # reverse proxy (routes to future api/frontend)
grafana/provisioning/       # auto-provisioned datasource
migrations/                 # Alembic; single P0 migration + README
seed/seed.py                # reference data
tests/p0_gate.ps1 / .py     # gate verification
requirements.txt            # fastapi, sqlalchemy, alembic, psycopg, asyncpg, ...
```

`api/`, `edge/`, `ingest/`, `workers/`, `frontend/` are intentionally empty
in P0 - they're later phases.

## Known deviations / things deliberately kept simple

See `migrations/README.md` for the full, detailed list (RLS mechanism,
TimescaleDB portability shim, `quotations.party_id` not being an FK, and a
handful of status/kind enums the PRD didn't fully specify). Summary:

- TimescaleDB-specific DDL (`create_hypertable`, compression, retention,
  continuous aggregates) is skipped with a `NOTICE` if the `timescaledb`
  extension isn't installed on the target Postgres, so the same migration
  is testable against a plain local Postgres. Against the docker-compose
  stack (`timescale/timescaledb:latest-pg16`) it always runs fully.
- Mosquitto TLS requires certs generated by `docker/mosquitto/gen_certs.sh`
  (self-signed, dev/pilot only) or trusting your own CA; a plaintext
  dev-only listener on `1883` is provided for convenience and is clearly
  marked to be disabled outside local dev.
- Caddy's `api`/`frontend` upstreams don't exist yet (P1+) - Caddy will
  502 on those routes until those services are built; the plain
  `:8080` health route in the Caddyfile works today.
- No API/auth layer yet, so nothing actually sets `app.current_plant_ids`
  in a live request path - that wiring is P1+. The gate script sets it
  directly to prove the Postgres-level mechanism works.
