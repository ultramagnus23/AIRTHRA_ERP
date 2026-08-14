# Migrations

Alembic, wired to a single comprehensive P0 migration:
`migrations/versions/0001_initial_schema.py`.

## Running

```
# from repo root, with DATABASE_URL set (via .env or the shell)
python -m alembic upgrade head
python -m alembic downgrade base   # drops everything (dev only)
```

`migrations/env.py` loads `../.env` and uses `DATABASE_URL` to build the
connection - `alembic.ini` deliberately has no `sqlalchemy.url` so nothing
sensitive is checked in.

## TimescaleDB portability

The migration checks `pg_available_extensions` for `timescaledb` before
using it. Against the docker-compose `timescale/timescaledb:latest-pg16`
image this is always true, and `readings`, `kpis`, `trip_pings` are created
as real hypertables with compression, retention, and continuous aggregates
exactly as specified in the PRD. If timescaledb is not installed (e.g.
someone points DATABASE_URL at a plain local Postgres for a quick sanity
check without Docker), the same tables are created as ordinary Postgres
tables with the same columns/PK/FKs, and the hypertable/compression/
retention/continuous-aggregate statements are skipped with a `NOTICE`. This
was necessary in the environment this was built in (no Docker/WSL2
available) to still be able to run and verify the migration end-to-end; it
does not change the schema in the true (Docker) target environment.

## Row-Level Security (RLS)

Every table that carries a `plant_id` (or an equivalent plant-identifying
column) has RLS enabled with a policy of the form:

```sql
USING (plant_id = ANY (app_current_plant_ids()))
```

`app_current_plant_ids()` is a small SQL function defined by the migration
that reads the Postgres session variable `app.current_plant_ids` (a
comma-separated list of plant ids) and returns `text[]`, or `{}` if unset.

**Contract for the API layer (built in a later phase):** on every
request, after authenticating the user and resolving which plants they're
allowed to see, run:

```sql
SELECT set_config('app.current_plant_ids', 'plant_a,plant_b', false);
-- or, inside an explicit transaction, prefer:
SET LOCAL app.current_plant_ids = 'plant_a,plant_b';
```

before issuing any queries on that connection/transaction. Because Postgres
does not support bind parameters in a bare `SET` statement, build that
value server-side (never interpolate untrusted input directly into SQL) -
`set_config()` is the parameterizable equivalent and is what
`seed/seed.py` and `tests/p0_gate.py` use.

Two Postgres roles are created by the migration:

- **`airthra_tenant`** - subject to RLS. Used for normal, plant-scoped
  requests (`plant_admin`, `plant_operator`, `plant_viewer` users).
- **`airthra_global`** - created `BYPASSRLS`. Used for `global_admin` /
  `global_read` users who should see every plant's data unconditionally.
  No policy needed for this role; `BYPASSRLS` skips policy evaluation
  entirely at the Postgres level.

Both roles are granted `SELECT, INSERT, UPDATE, DELETE` on all tables (via
`ALTER DEFAULT PRIVILEGES` too, so future tables inherit the same grants).
The dev passwords for both roles live in `.env.example` /`.env` - rotate
them for anything beyond local dev.

### Tables with RLS enabled

Direct `plant_id` column, straightforward policy:
`sensors`, `alarms`, `operator_events`,
`setpoint_changes`, `invoices`, `archive_log`, `user_plants`,
`installations`, `trip_stops`, `plants`.

### `readings` / `kpis`: RLS deliberately NOT enabled (real TimescaleDB constraint)

These are the two hypertables the PRD requires to carry compression
("compression after 7 days"). TimescaleDB does not permit native Postgres
RLS together with columnstore/compression on the same hypertable, in
either order - `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` fails once
compression is set, and enabling compression fails once RLS is on
("columnstore cannot be used on table with row security"). This was only
discoverable against real TimescaleDB (the local-Postgres fallback used
during initial P0 verification has no `timescaledb` extension, so it
never hit this).

Since the PRD's compression requirement for these two tables is
non-negotiable (they are the highest-volume ingest path) and RLS is
explicitly specced as a second net "under API-level scoping" rather than
the sole control, the resolution is: keep compression, and enforce
plant_id scoping for `readings`/`kpis` at the API layer only (built in
P2). Every other plant_id-bearing table above still gets native RLS as
the primary control.

Special-cased:
- `alarm_rules` - `plant_id` is nullable (NULL = global rule); policy is
  `plant_id IS NULL OR plant_id = ANY(...)`.
- `trips` - the plant-identifying column is `dest_plant_id`, not
  `plant_id`; policy checks that column instead.
- `trip_pings` - has no plant column of its own, only `trip_id`. The
  policy uses `EXISTS (SELECT 1 FROM trips WHERE trips.id = trip_pings.trip_id
  AND ...)` to reach `trips.dest_plant_id`. This is a join-based policy and
  therefore somewhat more expensive per-row than a direct column check;
  acceptable given `trip_pings` volume is far lower than `readings`/`kpis`.
  If this becomes a hot path, consider denormalizing `plant_id` onto
  `trip_pings` directly.

### Tables WITHOUT RLS (and why)

`users`, `company`, and the ERP tables in PRD sections 4.3/4.4 (`vendors`,
`materials`, `quotations`, `quotation_lines`, `projects`, `drawings`,
`boms`, `bom_items`, `pos`, `po_items`, `vendor_invoices`, `tasks`, `grn`,
`grn_lines`, `inventory_lots`, `issue_lines`, `fabrication_jobs`,
`unit_serials`, `qc_records`) carry no `plant_id` column. In the P0 data
model, Airthra runs ERP centrally as a single company across all
plants/projects - these entities are not partitioned per plant, so
plant-based RLS does not cleanly apply to them. Access control for these
(e.g. "only see tasks on your project") is a role/permission concern for
the API layer in a later phase, not Postgres RLS.

## Idempotency of `readings` ingest

`readings` has primary key `(plant_id, sensor_id, ts)`. The (P1+) ingest
service is expected to insert with:

```sql
INSERT INTO readings (ts, plant_id, sensor_id, value, quality_flag)
VALUES (...)
ON CONFLICT (plant_id, sensor_id, ts) DO NOTHING;
```

so re-delivered MQTT messages (at-least-once delivery) are naturally
deduplicated. This migration only needs to guarantee the PK exists; the
insert logic itself is out of scope for P0.

## Other documented deviations

- `quotations.party_id` is **not** a foreign key. `direction='vendor'`
  points at `vendors.id`; `direction='customer'` has no `customers` table
  in the P0 schema (out of scope for P0/not in the PRD section 4 spec). A
  later phase should either add a `customers` table or make this a
  polymorphic reference with a CHECK-enforced discriminator.
- Several `status`/`kind`-like fields the PRD didn't enumerate (e.g.
  `quotations.status`, `tasks.status`, `fabrication_jobs.status`,
  `trips.status`) were given a reasonable default set of CHECK values,
  called out with comments at each site in the migration.
- `po_no` format `AIR/PO/{FY}/{seq:04d}` is enforced on-disk via a CHECK
  regex (`AIR/PO/25-26/0001` style, Indian FY Apr-Mar as two-digit
  year-year). Generating the next sequence number is an API-layer (later
  phase) concern.
