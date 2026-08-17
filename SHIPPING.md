# Shipping Plan — single pilot → ~100 plants

Date: 2026-08-17
Companion to [AUDIT.md](AUDIT.md) (which catalogues *what is wrong today*). This document is *what has to be true before this runs 100 industrial sites*, in dependency order.

## A note on "foolproof"

Nothing that touches real boilers, real emissions compliance, and real invoices is foolproof, and any plan that claims otherwise is lying. What this plan targets instead:

- **Failures are loud, never silent.** The codebase already holds this line well (no swallowed exceptions, `quality_flag` never faked, OTS stubs explicitly marked). Preserve it.
- **Failures are contained.** One plant's edge unit dying, one bad rule, one corrupt payload must not degrade the other 99.
- **Failures are recoverable.** Backups that are actually restored, migrations that roll back, deploys that revert.
- **The blast radius of a mistake is bounded by the tenant.** This is the one where the current architecture is weakest — see B2.

---

## Phase 0 — Blockers. No customer can be onboarded until these exist.

These are not hardening items. Without them there is no product at 100 sites.

### 0.1 Real Modbus polling — **not implemented**
`edge/daemon.py:412` and `edge/mockgen.py:6` are explicit: `RealModbusPoller` does not exist, only the mock sinusoidal generator. Every screenshot, KPI, invoice and alarm in this platform today is computed from simulated data.

Needs: real transducer wiring per the FEED register, `pymodbus` RTU client against the actual RS-485 bus layout (register map per tag), 1-Wire bus enumeration for the DS18B20 strings, SPI for the MAX31865 PT100s, ADS1115 for the 4–20 mA loops, HX711 for the load cells. This is a hardware-in-the-loop project, not a coding task — it cannot be completed without physical access to a unit.

**Until this lands, everything downstream is unvalidated against reality.**

### 0.2 There is no way to onboard a plant or a user
Verified: no `INSERT INTO plants` or `INSERT INTO users` exists anywhere under `api/`. Plants, sensors and users exist *only* because `seed/seed.py` created them. Adding customer #2 today means running a Python script against the production database by hand — and that same script unconditionally resets the `global_admin` password every run.

Needs: an authenticated admin surface for tenant lifecycle — create plant, define its sensor manifest, create/invite users, scope them to plants, deactivate. Plus the corresponding API routers with `global_admin` gates, and an audit trail of who onboarded what.

This is the single largest *software* gap for a 100-tenant business.

### 0.3 Device provisioning is placeholder
`scripts/provision_pi.py:339-359` hardcodes the WireGuard server endpoint, public key, and a fixed `10.100.0.0` device IP. Provisioning 100 Raspberry Pis needs: per-device key generation, IP allocation from a pool, per-device MQTT TLS certificates (the current `scripts/mosquitto_add_user.sh` adds one user at a time by hand), enrollment tracking, and a revocation path for a stolen or decommissioned unit.

### 0.4 Password reset / credential lifecycle
No forgot-password flow, no password change endpoint, no way to rotate a compromised user credential without a DB write. At 100 sites with multiple operators each, this becomes a daily support burden immediately.

---

## Phase A — Security hardening (safe to do now, no external decisions needed)

Full findings in [AUDIT.md §2](AUDIT.md). Ordered by exposure:

| # | Item | Why it matters at 100 tenants |
|---|---|---|
| A1 | Rate-limit `/auth/login` | Internet-facing auth with zero throttling; bcrypt cost is the only brake |
| A2 | MinIO bucket → private + presigned URLs | Every tenant's PO PDFs, drawings, invoices are currently world-readable by key |
| A3 | Bind Postgres/MinIO/MQTT-plaintext to localhost | Compose publishes to `0.0.0.0`; fatal on a cloud VM |
| A4 | CORS origin from env, not hardcoded | Hardcoded `localhost:3000` — a prod deploy either breaks or gets "fixed" with `*` |
| A5 | Field length/format validation | No `max_length` anywhere; unbounded request bodies |
| A6 | `secrets.compare_digest` for webhook secret | Timing side-channel on the Grafana shared secret |
| A7 | Production guard on `seed/seed.py` | Fixed admin password, silently reset on every run |
| A8 | Dependency audit in CI (`pip-audit`, `npm audit`) | No supply-chain monitoring at all today |

---

## Phase B — Scale to 100 plants

### B1 — Worker N+1 queries (**measured, real**)
`workers/alarm_engine.py:run_once` evaluates every rule against every plant, and each `(rule, plant)` pair issues its own queries:

- `_active_alarm` → 1 query, `_last_cleared_at` → 1 query, evaluator → 1+ queries
- the frozen-sensor rule has no `sensor_id`, so it calls `_plant_sensor_ids` then `_readings_since` **per sensor** — 8 queries per plant on its own

At 7 rules × 100 plants this is roughly **2,600 round trips every 10-second cycle (~260 q/s)** purely for alarm evaluation. `workers/kpi_worker.py:149` has the same shape — `compute_for_plant` does one `_latest_reading` per sensor, ~700 queries per cycle at 100 plants.

Fix: replace per-plant/per-sensor lookups with set-based queries (one `DISTINCT ON (plant_id, sensor_id)` latest-reading query for the whole fleet per cycle, one active-alarm query keyed by `(rule_id, plant_id)`), then evaluate in memory. Turns thousands of round trips into single digits.

### B2 — RLS gap on `readings` / `kpis` is a 100-tenant liability
These two hypertables have **no row-level security** (documented trade-off against TimescaleDB compression, `api/db.py`). The API-layer `require_plant_access` check is the *only* thing preventing cross-tenant sensor data leakage — every other table has RLS as a second net. One future router that forgets the call leaks another customer's emissions data.

Options, in order of preference:
1. Re-test whether current TimescaleDB still refuses RLS + columnstore together (this was true at build time; may have changed).
2. If not: move compression to a continuous aggregate and keep RLS on the raw hypertable.
3. If neither: enforce with a CI check that greps every router touching `readings`/`kpis` for a `require_plant_access` call, plus a cross-tenant 403 regression test. This is the weakest option and should be treated as temporary.

### B3 — Connection pooling is at defaults
`api/db.py` sets `pool_pre_ping` but no `pool_size`/`max_overflow` — SQLAlchemy defaults to 5+10 per engine, 30 total across the tenant and global engines. Needs to be env-configurable and sized against expected concurrency, with PgBouncer in front once the API runs more than one replica.

### B4 — Ingest throughput
`ingest/service.py` already batches via `executemany` — good. At 100 plants × 7 sensors × 1 Hz that is ~700 msg/s through a single asyncio process. Needs load testing, then either partitioned consumers by plant range or a queue in front. Do not pre-optimise; measure first.

### B5 — Worker singletons
`kpi_worker`, `alarm_engine`, `billing_worker`, `archive_worker` are all single-process loops with no leader election. Two copies running double-writes alarms and invoices. Before running more than one instance: advisory locks or a scheduler with a locking backend.

### B6 — Time-series retention economics
100 plants × 7 sensors × 1 Hz ≈ 22 billion rows/year uncompressed. Compression and retention policies exist in the initial migration; they need to be validated against real cardinality and a real cost target, and continuous aggregates need to serve the history UI rather than raw scans.

---

## Phase C — Correctness (needs sign-off, not code)

| Item | Status |
|---|---|
| Alarm thresholds contradict the FEED register — `SO2_out` fires at 200 ppm vs the register's **50 ppm compliance trip** | [AUDIT.md §1.1](AUDIT.md), unresolved, **highest priority in this phase** |
| KOH/K2SO3 level sensors: register works in litres, platform stores percent | Unresolved, needs a units decision |
| Billing constants (SO2 rate, K2SO3/SO2 mass ratio, gap handling) are documented placeholders | `workers/billing_worker.py:31-36` |
| OTS blockchain anchoring falls back to a labelled stub proof on network failure | `workers/archive_worker.py:190-225` — confirm downstream consumers check the `is_real` flag |
| Two-sensor bracket alarms (removal efficiency) unimplementable — engine reads `readings` only, not `kpis` | Extend the engine to evaluate KPI values |

---

## Phase D — Operations

- **CI/CD**: no `.github/` exists. The P0–P7 gate scripts are genuine acceptance tests that nothing runs automatically. Wire them to a service-container Postgres.
- **Backups**: `scripts/restore_drill.py` exists (good instinct — a restore drill, not just a backup). Needs scheduling, offsite storage, and a documented RPO/RTO.
- **Observability**: no platform-level monitoring. At 100 sites you need per-edge-unit liveness, worker heartbeat, queue depth, and alerting on the alerting system itself.
- **Per-tenant SLA reporting**: uptime and data-completeness per plant, since billing depends on captured data.
- **Runbooks**: what an on-call engineer does when an edge unit goes dark, when the alarm engine falls behind, when a bad invoice is issued.
- **Production Caddyfile**: current config is `tls internal` (dev CA) only.

---

## Suggested execution order

1. **Phase A** in full — cheap, safe, no dependencies. *(in progress)*
2. **B1** worker N+1 — the clearest scale win, self-contained. *(in progress)*
3. **D/CI** — so everything after this is regression-tested.
4. **0.2 tenant onboarding** — the biggest software blocker; gates commercial rollout.
5. **B2 RLS** — before real multi-tenant data exists, not after.
6. **Phase C** — with process-engineering sign-off.
7. **0.1 Modbus / 0.3 provisioning** — hardware-gated, run in parallel with the above.
