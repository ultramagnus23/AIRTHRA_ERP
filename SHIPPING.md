# Shipping Plan — Airthra Platform

Last consolidated: 2026-08-17
Companion to [AUDIT.md](AUDIT.md) (security/completeness findings) and [INDUSTRIAL_READINESS.md](INDUSTRIAL_READINESS.md) (response to the client's industrial-IoT review). This document is the single source of truth for what has shipped, what's still open, and why — superseding the earlier draft-plan/status-update split that had grown redundant (and briefly self-contradictory: an earlier revision listed tenant onboarding as both "blocked" and "done").

## A note on "foolproof"

Nothing that touches real boilers, real emissions compliance, and real invoices is foolproof, and any plan that claims otherwise is lying. What this plan targets instead:

- **Failures are loud, never silent.** No swallowed exceptions, `quality_flag` never faked, OTS stubs explicitly marked, QC never inferred from sensor data. Preserved throughout everything below.
- **Failures are contained.** One plant's edge unit dying, one bad rule, one corrupt payload must not degrade the other 99.
- **Failures are recoverable.** Backups that are actually restored, migrations that roll back, deploys that revert.
- **The blast radius of a mistake is bounded by the tenant.** The one place this is still weak — see *RLS on readings/kpis* below.

---

## 1. Done, verified live

Everything in this section was tested against the running stack, not just typechecked — migration round-trips (`upgrade → downgrade → upgrade` against live data), curl against every guard/rejection path, and browser verification (real form fills, real file uploads, real clicks) for anything user-facing. Details and exact evidence live in the git history; this is the index.

### Security (full findings: [AUDIT.md §2](AUDIT.md))

| Item | Evidence |
|---|---|
| Login rate limiting | Per-IP + per-email limiter (`api/ratelimit.py`); verified 5 failures → `429` + `Retry-After`, unrelated accounts unaffected |
| MinIO bucket → private + presigned URLs | Verified anonymous GET `403` (was `200`), presigned GET `200`. Wired into every consumer added after: invoices, documents, CoA PDFs |
| Infra ports bound to loopback | Postgres/MinIO/Grafana/MQTT-plaintext on `127.0.0.1`; MQTT TLS/WS deliberately left public for remote edge units |
| CORS from env, not hardcoded | `CORS_ALLOWED_ORIGINS`; wildcard unsupported by design (credentialed CORS + `*` is a real footgun) |
| Field length/format validation | `Field(max_length=...)` on request bodies; verified oversized login body → `422` |
| `secrets.compare_digest` for webhook secret | Timing-safe comparison on the Grafana shared secret |
| Production guard on `seed/seed.py` | Refuses to run when `APP_ENV` names a non-dev environment unless `ALLOW_SEED=1` — verified both the refusal and the normal dev path |
| Dependency audit in CI | `pip-audit` / `npm audit`, advisory (doesn't block PRs on a fresh transitive CVE) |
| DB connection pool sizing | Env-tunable (`DB_POOL_SIZE`/`DB_POOL_MAX_OVERFLOW`) instead of SQLAlchemy defaults |

### Scale

| Item | Evidence |
|---|---|
| Alarm engine N+1 queries | Was ~2,900 queries/10s cycle at 100 plants (measured). `FleetSnapshot` loads the whole fleet in 4 queries; evaluators read from memory. Measured after: **6 queries/cycle, flat in plant count** |
| KPI worker N+1 queries | Same fix, one `DISTINCT ON` query instead of one round trip per (plant, sensor) |

### Operations / CI

| Item | Evidence |
|---|---|
| CI pipeline (`.github/workflows/ci.yml`) | Frontend typecheck/lint/build; backend against a real TimescaleDB service container — migration idempotency *and* reversibility, seed idempotency, P0 RLS gate, both workers run clean, a regression test pinning the edge clock gate |

### Edge / data integrity ([INDUSTRIAL_READINESS.md](INDUSTRIAL_READINESS.md) has the full point-by-point response to the client's review)

| Item | Evidence |
|---|---|
| Edge clock trust gate (`edge/clock.py`) | The Pi has no RTC and can boot to 1970 after a power cut; because the daemon buffers-and-backfills, a wrong-clock timestamp was previously durable enough to overwrite real history. Now gated on a sanity floor + a disk-persisted monotonic watermark + NTP/RTC verification. Verified all 6 cases: epoch boot rejected, backwards jump rejected, small NTP slew tolerated, watermark survives restart |
| ML ground-truth events | Ten one-tap operator actions (`QuickEventBar.tsx`) replacing a free-text form that couldn't serve as training labels; verified a real click writes a structured, tagged row |
| `quality_flag` calibration/purge states | Corrected an earlier wrong claim (see git history for the correction) — the real gap was narrower than first reported; `calibration`/`purge` added to close it |

### Commercial / ERP modules (enterprise spec, all ten core modules now covered in some real form)

| Module | What shipped |
|---|---|
| **Tenant onboarding** | `POST /admin/plants` (atomic plant + sensor manifest), `POST /admin/users` (invite-token flow — no human ever transmits a real password), `audit_log` on every mutation. Full loop proven live through the browser: create plant → create user → invite link → fresh unauthenticated tab accepts it → signs in → lands correctly scoped; cross-tenant access to another plant correctly `403`s. `seed/seed.py` is no longer the only way to add a customer |
| **Contract-driven billing** | The hardcoded global `SO2_RATE_PER_KG` env var is gone. Every plant bills against its own `contracts` row (base fee + usage rate + uptime-gated bonus/penalty); a plant with no contract is honestly skipped, never billed at a guessed rate. Verified live, including a real negative-total SLA-penalty case computed correctly from the seeded terms |
| **Document management** | Generic `documents` table (`entity_type`, `entity_id`) instead of a bespoke column pair per table; one upload/list/delete API and one reusable panel wired into two unrelated entity kinds (plants, contracts) to prove the design generalizes. First genuine user-file-upload endpoint in the codebase — surfaced a real missing dependency (`python-multipart`) via the import error |
| **Engineering Change Management** | Formal request → reason → approval → new revision (`bom_change_requests`), additive to the existing (already-correct) release-immutability. Caught a real routing bug before shipping: a new endpoint would have been silently unreachable because FastAPI matches routes in registration order — fixed and documented inline so it can't silently regress |
| **Offtake** | The chemical product each plant produces (K2SO3) had no tracking at all — the existing `qc_records` table only covers hardware fabrication QC. New `product_batches`/`buyers` with a DB-CHECK-enforced lifecycle (produced → QC → allocated → dispatched) and a real Certificate of Analysis PDF generator. QC status can only ever be set by a named human, never inferred from sensor data. Verified by downloading a genuine PDF through a presigned link |
| **CRM / lead pipeline** | Deliberately one table, not a department, per the spec's own scope guidance. A lead can only be marked "won" by pointing at a real `plants` row (the same row tenant onboarding creates) — closing the lead → contract → deployed-skid loop as one traceable chain instead of two systems that coincidentally mention customers |
| Fleet & Telemetry, Chemical Ops, Supply Chain/Logistics, Asset Intelligence, Customer Platform | Pre-existing from earlier phases of this build (P0–P7) — telemetry ingestion, fleet dashboard, materials/inventory, logistics trips, alarm engine, BOM/fabrication/QC, client dashboard |

### UI

| Item | Evidence |
|---|---|
| Motion vocabulary | Re-extracted airthra.com's actual computed styles rather than working from memory; adopted the brand's easing curves verbatim, cut its marketing-hero durations to interface speed (140ms). Staggered entrances, live-data pulse, reduced-motion respected throughout |
| Live page instrument register | Tiles grouped by subsystem with FEED register tag IDs, mounting/purpose on hover, trip thresholds as reference text, honest "N of 40 tags wired up" coverage line |

---

## 2. Open — hardware-gated (cannot be completed without physical access)

- **Real Modbus polling.** `edge/daemon.py`/`edge/mockgen.py` are explicit: only the mock generator exists. Every reading, KPI, alarm, and invoice in this platform today is computed from simulated data. This is a hardware-in-the-loop project, not a coding task.
- **DS3231 RTC modules.** The clock trust gate (above) makes a missing RTC *loud* instead of silently corrupting data, but software cannot invent the correct time — the hardware purchase is still required per unit.
- **Device provisioning.** `scripts/provision_pi.py` hardcodes WireGuard server details and a fixed device IP. Real fleet provisioning needs per-device key generation, IP allocation from a pool, per-device MQTT TLS certs, and a revocation path — see the next section for the Tailscale recommendation this depends on.

## 3. Open — needs an external account or infrastructure decision

- **Tailscale (or equivalent) for zero-trust remote access.** Recommended over hand-rolled WireGuard specifically because revocation (a stolen or decommissioned unit) is the hard part at fleet scale, not the tunnel itself. Needs an account and a decision, not code.
- **Self-service password reset.** The *invite* half is built (a new user sets their own password via a one-time token). Forgot-password for an *existing* user needs the same token machinery reused as a reset flow, plus an actual email-sending path — invite links today are hand-copied by an admin, which doesn't scale to self-service. The missing piece is delivery infrastructure, not the token design.
- **Production TLS / Caddyfile.** Current config is `tls internal` (a local dev CA). A real deployment needs a separate Caddyfile with a real ACME/Let's Encrypt directive.
- **Hosting target.** Per the earlier discussion in this session: a private, invite-only deployment is the safe next step once the above is settled — not a public listen-on-the-internet deployment while the rate limiter is still single-process and there's no real payment/production credential rotation story.

## 4. Open — needs process-engineering sign-off, not a code change

- **Alarm thresholds contradict the FEED instrument register.** `SO2_out` fires at 200 ppm; the register's actual compliance trip is 50 ppm. The frontend's reference display was corrected to the register's values; the *live alarm rules* were deliberately left untouched — retuning a safety/compliance trip point is not a decision to make unilaterally. See [AUDIT.md §1.1](AUDIT.md).
- **KOH/K2SO3 level units.** The FEED register works in litres; the platform stores percent. Not converted — needs a decision on which is the source of truth.
- **Billing/process constants.** SO2-to-K2SO3 mass ratio, contract performance-bonus/penalty thresholds seeded as illustrative pilot defaults — need real negotiated/measured values before being relied on commercially.
- **Contract mid-month proration.** A contract's coverage is checked against the *first day* of the billing period, so a contract effective mid-month doesn't retroactively bill that partial month. No proration logic exists — this is a scope decision (build proration, or always backdate `effective_from`), not a bug.

## 5. Open — deliberately not built, and why

- **ML predictive maintenance / predictive logistics / "optimization."** No real historical data exists to train on — everything in this database is seed fixtures or a few hours of mock sensor readings. A model "trained" on that would produce numbers that look like predictions but aren't, on a platform whose entire design principle is never faking data. What *is* real: rule-based predictive maintenance (the alarm engine — the deterministic approach the spec itself calls acceptable) and deterministic predictive logistics (burn-rate/days-remaining, already built).
- **Full GL/AR/AP accounting.** Out of proportion to build from scratch alongside everything else this session; the spec itself suggests integrating an external accounting system rather than reproducing Tally/Odoo.
- **HazOp / formal EHS workflows.** Not started.
- **Offline-capable field app.** Not started.

## 6. Architecture notes carried forward (real engineering work, not yet started)

- **RLS gap on `readings`/`kpis`.** These two hypertables have no row-level security (a documented trade-off against TimescaleDB compression). The API-layer `require_plant_access` check is the *only* thing preventing cross-tenant sensor data leakage on these two tables — every other table has RLS as a second net. Options in order of preference: (1) re-test whether the current TimescaleDB version still refuses RLS + columnstore together, (2) move compression to a continuous aggregate and keep RLS on the raw hypertable, (3) failing both, a CI check that greps every router touching these tables for the access check, plus a cross-tenant regression test — the weakest option, temporary only.
- **Worker singletons.** `kpi_worker`, `alarm_engine`, `billing_worker`, `archive_worker` are single-process loops with no leader election. Running more than one instance double-writes alarms/invoices. Needs advisory locks or a scheduler with a locking backend before scaling workers horizontally.
- **Ingest throughput at 100 plants.** `ingest/service.py` already batches via `executemany`. At 100 plants × 7 sensors × 1 Hz that's ~700 msg/s through a single asyncio process — needs load testing before assuming it holds, then partitioned consumers or a queue in front if it doesn't.
- **Time-series retention economics.** 100 plants × 7 sensors × 1 Hz ≈ 22 billion rows/year uncompressed. Compression/retention policies exist from the initial migration but need validation against real cardinality and a real cost target.
- **Buffer load test.** The edge daemon's SQLite store-and-forward buffer is architecturally sound (verified working live this session) but its behaviour under a genuinely long outage, and under a full disk, has not been soak-tested — can't be faked, needs a real long-running test.
- **Archive worker scheduling.** `workers/archive_worker.py` does real OpenTimestamps anchoring with atomic upload verification, but nothing invokes it on a schedule — needs one systemd timer (or equivalent), deploy-target dependent.

---

## Suggested execution order from here

1. **RLS on readings/kpis** (§6) — before more real multi-tenant data accumulates, not after.
2. **Tailscale + device provisioning** (§3, §2) — unblocks real fleet rollout once an account exists.
3. **Process-engineering sign-off** (§4) — alarm thresholds and unit decisions should not wait on code; they're the highest-consequence open items.
4. **Self-service password reset** (§3) — once there's an email-sending path, cheap to finish.
5. **Worker leader election / archive scheduling** (§6) — before running more than one instance of anything.
6. **Real Modbus / RTC hardware** (§2) — hardware-gated, run in parallel with everything above.
