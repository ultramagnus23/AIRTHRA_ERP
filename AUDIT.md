# Airthra Platform — Audit

Date: 2026-08-17
Scope: full repo at `feature/design-system-and-hardware-bom` (backend `api/`+`workers/`+`edge/`, frontend `frontend/`, infra `docker-compose.yml`+`docker/`, migrations, seed scripts).

This is a point-in-time audit. It covers three things: security posture, the fault-decision-tree alarm rules added this session, and outstanding functional work. Severities follow critical/high/medium/low/info.

---

## 1. Fault decision trees → alarm rules (this session's addition)

FEED Addendum A Rev 2 Section 3 defines fault decision trees against the FEED's full 41-tag instrument list, and most of those trees branch on **two sensors at once** (e.g. tree 3.1: "is outlet SO2 high? → is inlet SO2 *also* high? → branch"). The platform's live sensor manifest has 7 tags (`SO2_in`, `SO2_out`, `pH`, `temp_C`, `level_KOH_tank`, `level_K2SO3_tank`, `flow`), and `workers/alarm_engine.py`'s three expression types (`threshold`, `rolling_z`, `rate_of_change`) each evaluate **one sensor at a time** — there is no two-sensor/bracket comparison evaluator in the current schema.

Rather than fake a bracket check by disguising it as two unrelated rules, [`workers/seed_fault_tree_rules.py`](workers/seed_fault_tree_rules.py) only encodes the sub-conditions that are legitimately single-sensor checks on their own merit, seeded as 6 new global `alarm_rules` (verified live against Postgres — inserted cleanly, idempotent on re-run, and `alarm_engine.py --once` evaluated all 6 with no errors, correctly raising a real alarm off live mock data: `pH=7.29 < min=7.5`):

| Rule | Tree covered | Honest scope note |
|---|---|---|
| `koh_depletion_low_ph` | 3.1, AT-02 pH branch | Faithful single-sensor reproduction |
| `koh_tank_low_level` | operational precursor to above | Not from a numbered tree; standalone tank-level check |
| `so2_out_emissions_excursion` | 3.1 root check (AE-02 high) | Does **not** implement the "is AT-01 also high" branch |
| `so2_in_combustion_instability` | 3.1, "AT-01 also high" branch, approximated | Statistical spike on SO2_in alone, not a true AND with SO2_out |
| `product_loop_overtemp` | 3.4, "product not cooling" | No separate coolant-delta sensor exists; fires on absolute high temp instead |
| `flow_abnormal_rate_of_change` | not a numbered tree | General pump/blockage signature |

**Not implemented, blocked on hardware/schema:**
- Any tree requiring PT-01 (vacuum), VFD-P101 current, DP-101, LE-01, or the other ~34 FEED tags with no corresponding live sensor in this platform.
- True two-sensor bracket comparisons (e.g. "SO2 removal efficiency" as `SO2_out/SO2_in`) — the KPI `so2_removal_efficiency` already computes this ratio in `workers/kpi_worker.py`, but `alarm_rules`/`alarm_engine.py` currently only reads `readings`, not `kpis`. Extending the engine to alarm off KPI values (not just raw readings) would be the correct way to implement the rest of Section 3's trees faithfully — flagged as outstanding work below, not built here.
- **Numeric thresholds used above (pH 7.5, SO2_out 200ppm, temp_C 60°C, flow rate 5/s, KOH tank 15%) are illustrative pilot-plant setpoints, not transcribed from a FEED setpoint table** — no exact alarm-limit table was available at the time. **This has since been superseded — see 1.1.**

### 1.1 Seeded alarm thresholds contradict the FEED instrument register — **[High], unresolved**

The FEED instrument register (the full ~40-tag table with per-tag normal ranges and trip thresholds) does specify exact setpoints, and they disagree with both the seeded alarm rules and the frontend's `SENSOR_MANIFEST`. The frontend manifest has been corrected to the register's values; **the alarm rules have NOT been changed** — retuning live trip points is a process-engineering decision, not a code cleanup.

| Sensor | Register tag | Register normal | Register trip | Seeded rule fires at | Gap |
|---|---|---|---|---|---|
| `SO2_out` | AE-02 | 5–25 ppm | **>50 ppm — TRIP** | >200 ppm | **4× too loose.** Stack could sit at 180 ppm — 3.6× the compliance trip — with nothing raised. Highest-priority item here. |
| `pH` | AT-02 | 8.5–9.5 | <8.0 dose KOH | <7.5 | Fires half a pH unit late |
| `SO2_in` | AT-01 | 200–800 ppm | >2000 ppm | z-score spike only | No absolute high-sulfur alarm exists |
| `temp_C` | TE-01 | 55–65 °C | **≥70 °C — HARD TRIP** | >60 °C | Fires early (nuisance risk), and no hard-trip tier |
| `level_KOH_tank` | LE-03 | 200–1000 L | <150 L | <15 % | **Unit mismatch** — register is litres, platform stores percent |
| `level_K2SO3_tank` | LE-02 | 50–950 L | >900 L | none | No rule; also unit mismatch |
| `flow` | FT-01 | — | — | rate >5/s | Tag not in the register at all; platform's own range |

Two follow-ups needed: (a) retune the six seeded rules to the register's setpoints once a process engineer signs off, and (b) decide the litres-vs-percent question for both level sensors — the platform currently stores percent while the register, the procurement logic, and the tote-changeout trigger all reason in litres. Neither is safe to change unilaterally, so both are left as-is and flagged here.

### 1.2 Retuned to register setpoints — 2026-08-18

Actioned by [`workers/seed_fault_tree_rules.py`](workers/seed_fault_tree_rules.py) (now `ON CONFLICT ... DO UPDATE`, so re-running it pushes retuned params into an already-seeded DB rather than being a no-op):

| Rule | Change |
|---|---|
| `so2_out_emissions_excursion_v1` | 200 ppm → **50 ppm** (register trip, verbatim) |
| `koh_depletion_low_ph_v1` | 7.5 → **8.0** (register trip, verbatim) |
| `so2_in_high_absolute_v1` | **new** — 2000 ppm absolute ceiling (register trip); the existing `so2_in_combustion_instability_v1` z-score rule is kept alongside it, different failure signature |
| `product_loop_overtemp_v1` | retuned in place, 60°C → **65°C**, severity critical → warning (top of normal band), paired with new `product_loop_overtemp_hard_trip_v1` (≥70°C, critical — register's HARD TRIP). Kept the same rule name/id rather than renaming: a real alarm from this rule already exists in the `alarms` table (FK-referenced), so Postgres refuses a delete/rename — retune-in-place was the only safe option. Advisory only; does not itself drive the bypass damper, which is assumed to be a separate PLC/edge interlock if one exists. |
| `k2so3_tank_full_v1` | **new** — 90% (no rule existed before) |
| `koh_tank_low_level_v1` | unchanged numerically (15%) but basis now documented |

Litres-vs-percent (item b) resolved as: keep percent storage everywhere (no schema/ingestion change — `admin_logistics.py`'s procurement forecast already regresses in percent), convert the register's litre trips to percent-equivalents assuming a **1000L IBC tote for both tanks**. For `level_K2SO3_tank` that capacity is sourced from the tag's own `location` field ("1000L product IBC tote"), so 900L → 90% is a straightforward transcription. For `level_KOH_tank` no capacity is recorded anywhere in this codebase — 1000L was an assumption the user made explicitly for this pass, not a sourced fact, and 150L → 15% depends on it. **Still open:** confirm the KOH tote's actual rated capacity against the physical hardware; if it's not 1000L, `koh_tank_low_level_v1`'s `min: 15` needs re-deriving.

---

## 2. Security audit

### 2.1 Secrets management
- **[Info]** `.env` is correctly git-ignored, never committed (`git log --all -- .env` empty).
- **[Low]** `.env.example:51` ships a real-looking 32-byte hex `JWT_SECRET` rather than a placeholder. If a dev copies `.env.example` → `.env` without regenerating it, every such instance shares one signing key. **Fix:** replace with `JWT_SECRET=<generate with 'openssl rand -hex 32'>`.
- **[Info]** All other default creds follow a consistent, self-documenting `change_me_dev_only*` convention.
- **[Medium]** `seed/seed.py:82` hardcodes a fixed dev password (`Airthra_Dev_2026!`) for the seeded `global_admin` account, and the `UPDATE users SET pw_hash=...` path (`seed/seed.py:177-180`) silently **resets** an existing admin's password on every re-run, with no environment guard preventing this from running against a real deployment. **Fix:** add an `ALLOW_SEED=1`-style guard and/or randomize + print the password once instead of a fixed literal.
- **[Medium]** MinIO bucket is provisioned world-readable (`docker-compose.yml:113`, `mc anonymous set download`). Every PO PDF / drawing / quotation uploaded via the ERP is publicly downloadable by anyone who obtains or guesses the object key — no auth check happens at the storage layer. **Fix:** make the bucket private, proxy downloads through an authenticated endpoint or use short-lived pre-signed URLs.

### 2.2 Auth / authorization
- JWT: HS256, secret from env (never hardcoded), 8h default expiry — reasonable for a single-backend monolith.
- Passwords: bcrypt via passlib, default cost factor, malformed-hash `ValueError` handled correctly.
- **RBAC coverage checked across all 28 files in `api/routers/`** — every real router has an auth `Depends(...)` gate (or, for the WebSocket endpoint, an equivalent manual pre-accept check). No missing gate found.
- **[Info/architectural]** `readings`/`kpis` hypertables have **no RLS** (documented trade-off vs. TimescaleDB compression, `api/db.py`) — the API-layer `require_plant_access` check is the *only* control for cross-tenant isolation on those two tables, with no DB-level backstop the way every other RLS-covered table has. Every current call site correctly calls it, but a future router that forgets to would leak cross-tenant sensor data silently. **Fix:** add an automated regression test (extend `tests/p2_gate.py`) asserting 403 on cross-tenant readings/kpis access, and treat any new router touching those tables as needing explicit review for this.
- **[Low]** `admin_logistics.py:205` compares the Grafana webhook shared secret with `!=` instead of `secrets.compare_digest()` — a timing side-channel, low-severity since it's an internal webhook not a login endpoint, but free to fix.

### 2.3 SQL injection
No SQL injection found. All dynamic SQL fragments interpolate only fixed, code-defined identifiers (column-name constants, or Pydantic model field names via `model_dump()`); every actual value is a bound `:param` through SQLAlchemy `text()`.

### 2.4 CORS / network exposure
- CORS (`api/main.py:81-87`) is scoped to a single explicit origin (`http://localhost:3000`), not wildcarded — but hardcoded with no env override, and the code's own comment flags it as dev-only, to be tightened before real deployment.
- **[Medium]** `docker-compose.yml` publishes Postgres, MinIO, and the plaintext MQTT dev port with no explicit bind address, which Docker defaults to `0.0.0.0` — fine on a firewalled dev laptop, a real exposure if this compose file is ever run on a cloud VM without a host firewall. **Fix:** bind infra-only ports to `127.0.0.1:` or drop host publishing entirely for services only consumed by other containers on the compose network.
- Caddy uses `tls internal` (local dev CA) — correct for dev; no production Caddyfile variant exists yet, needed before a real deployment.

### 2.5 Input validation
- **[Low]** No length/format constraints on Pydantic string fields anywhere sampled (e.g. `LoginRequest.email: str` isn't `EmailStr`, ERP `notes`/`name` fields are unbounded). Not exploitable alone, but a real gap for payload-size abuse and data quality. **Fix:** `EmailStr` for email fields, `Field(max_length=...)` on free-text fields.

### 2.6 Dependency hygiene
Python deps are exactly pinned (`==`) in `requirements.txt`; frontend has a committed lockfile. No dependency-audit tooling (`pip-audit`, `npm audit`, Dependabot) wired into CI — worth adding.

### 2.7 Error handling / info leakage
No debug-mode leakage found (no `debug=True`, no global handler echoing raw exceptions to clients). Worth a repo-wide grep for `detail=str(` before shipping, as a habit-forming check rather than because one was found.

### 2.8 Logging
No password/token/secret found in any log statement.

### 2.9 Frontend session handling
Well-designed: JWT lives in an `httpOnly`, `sameSite=lax`, conditionally-`secure` cookie; the frontend never verifies the JWT signature itself (correctly deferred to the backend), and this is explicitly documented in code. No `dangerouslySetInnerHTML`/`eval`/`new Function` found anywhere in `frontend/`.
- **[Info]** The Next.js API proxy (`frontend/app/api/backend/[...path]/route.ts`) forwards to *any* backend path with no route allow-list — safe today because the backend re-validates every request, but worth noting as a single-boundary design choice.

### 2.10 Rate limiting
- **[Medium]** `POST /auth/login` has no rate limiting, no lockout, no backoff — only bcrypt's per-attempt cost throttles brute force. Not yet internet-facing (CORS is localhost-only today), but this is a concrete pre-launch blocker. **Fix:** per-IP/per-email rate limiting (e.g. `slowapi`) before any real deployment.

### Summary — pre-production blockers, in priority order
1. Rate-limit `/auth/login`.
2. Make the MinIO bucket private; serve files through an authenticated endpoint or pre-signed URLs.
3. Bind Postgres/MinIO/MQTT dev ports to localhost, or drop host publishing.
4. Move CORS origin to an env var and set it to the real prod origin at deploy time.
5. Add field-length/format validation (`EmailStr`, `max_length`) on request models.
6. Guard `seed/seed.py` against accidental production use.

None of these are exploited-today findings against a live deployment — they're hardening items the code's own comments already flag as "dev-only, tighten before real deployment." The RLS/RBAC/SQL-parameterization foundations are solid.

---

## 3. Outstanding functional gaps (non-security)

- **`edge/daemon.py` / `edge/mockgen.py`** — real Modbus polling against physical PLC/sensor hardware is **not implemented**; the edge daemon currently only generates mock/simulated sensor data. This is the largest gap if the platform is meant to run against the real pilot plant rather than simulated data.
- **`edge/manifest.py`** — `HttpManifestSource` (fetching a plant's sensor manifest from the platform API) raises `NotImplementedError`; only a local/static manifest source works today.
- **`workers/archive_worker.py`** — OpenTimestamps blockchain-anchoring falls back to a clearly-labeled stub proof (`AIRTHRA-OTS-STUB-PROOF`) whenever the real OTS calendar submission fails. Well-engineered (never silently mistaken for real — has an `is_real` flag), but genealogy/compliance archive proofs may not always be real anchored timestamps. Worth checking how often the fallback triggers and whether downstream consumers actually check the flag.
- **`workers/billing_worker.py` / `workers/kpi_worker.py`** — several business constants (K2SO3/SO2 mass ratio, SO2 billing rate, billing gap-handling mode) are explicitly documented placeholders pending a confirmed PRD figure. These currently produce plausible but not-yet-confirmed invoice amounts.
- **`scripts/provision_pi.py`** — WireGuard server endpoint/public key and device IP allocation are hardcoded placeholders; the Pi-provisioning script can't yet produce a working config against a real fleet-management backend.
- **Two-sensor bracket alarms** (see Section 1 above) — extending `alarm_engine.py` to evaluate against `kpis` (not just raw `readings`) would unlock the rest of the FEED's fault trees, particularly the SO2-removal-efficiency bracket that's already computed as a KPI.
- No CI pipeline exists (no `.github/workflows`); the P0–P7 phase gate scripts (`tests/p2_gate.py` … `tests/p7_gate.py`) are real, still-passing acceptance tests but currently only run manually.

---

## 4. Redundant/old code — what was found and what was done

A dedicated sweep found the codebase to be unusually clean for its size:
- **No** backup files, no dead frontend components, no leftover pre-redesign Tailwind classes (`bg-white`/`bg-slate`/`text-gray` etc. — a prior cleanup pass this session already caught the last two offenders, `app/403/page.tsx` and `app/page.tsx`).
- **No** unused `requirements.txt`/`package.json` entries.
- **One genuinely dead function removed:** `api/erp_storage.py`'s `delete_key()` had zero call sites anywhere in the repo — removed in this pass.

**Deliberately kept, despite looking redundant:** `api/erp_app.py`, `tests/_p6_test_app.py`, and `tests/_p7_test_app.py` are standalone FastAPI apps that duplicate router-wiring already present in `api/main.py`. They exist only to be driven by `tests/p5_gate.py`, `tests/p6_genealogy_gate.py`, and `tests/p7_gate.py` respectively — the only executable proof that each phase's PRD acceptance criteria (GST math, BOM immutability, 3-way match, genealogy forward/recall trace, admin risk scores, billing PDF generation, etc.) actually hold against a live Postgres+MinIO stack. Deleting the standalone apps would break the only regression tests these features have, since nothing else in the repo re-runs those checks against `api/main.py` directly. This is real duplication, but removing it needs a rewrite of the three gate scripts to target `api/main.py` instead of a throwaway app — not a straight deletion — so it's listed here as follow-up work rather than done in this pass.
