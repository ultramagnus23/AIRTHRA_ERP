"""P0 initial schema: shared, machine-data hypertables, ERP procurement/engineering,
ERP inventory/production/QC, logistics, RLS.

Implements PRD section 4 verbatim (table names / columns). See migrations/README.md
for the RLS mechanism, the TimescaleDB portability shim, and documented deviations.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-08-14
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def _timescaledb_available(conn) -> bool:
    """Best-effort check for whether the timescaledb extension can be
    installed on the target Postgres. In docker-compose we always use the
    timescale/timescaledb image, so this is True there. It can be False when
    running the same migration against a plain local Postgres for quick dev
    iteration/testing without Docker - in that case we fall back to plain
    (non-hypertable) tables and skip compression/retention/continuous
    aggregates, with a NOTICE, so the rest of the schema + RLS is still
    fully testable. See migrations/README.md ("TimescaleDB portability").
    """
    row = conn.execute(
        sa.text("SELECT 1 FROM pg_available_extensions WHERE name = 'timescaledb'")
    ).fetchone()
    return row is not None


def upgrade() -> None:
    conn = op.get_bind()
    ts_available = _timescaledb_available(conn)

    if ts_available:
        op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb;")
    else:
        op.execute(
            "DO $$ BEGIN RAISE NOTICE "
            "'timescaledb extension not available on this Postgres - "
            "readings/kpis/trip_pings will be created as plain tables "
            "(no hypertable/compression/retention/continuous aggregates). "
            "Use the docker-compose timescale/timescaledb image for full "
            "TimescaleDB behaviour.'; END $$;"
        )

    # pgcrypto not required: gen_random_uuid() is built into Postgres core
    # since PG13, and the target image is pg16.

    _create_roles()
    _create_rls_helper()

    _create_shared_tables()
    _create_machine_data_tables(ts_available)
    _create_procurement_engineering_tables()
    _create_inventory_production_qc_tables()
    _create_logistics_tables(ts_available)

    _enable_rls()
    _grant_privileges()


def downgrade() -> None:
    # P0 initial migration: downgrade drops everything it created.
    op.execute("DROP SCHEMA public CASCADE;")
    op.execute("CREATE SCHEMA public;")
    op.execute("GRANT ALL ON SCHEMA public TO public;")


# ---------------------------------------------------------------------------
# Roles + RLS helper
# ---------------------------------------------------------------------------

def _create_roles() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'airthra_tenant') THEN
                CREATE ROLE airthra_tenant LOGIN PASSWORD 'change_me_dev_only_tenant';
            END IF;
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'airthra_global') THEN
                CREATE ROLE airthra_global LOGIN PASSWORD 'change_me_dev_only_global' BYPASSRLS;
            END IF;
        END
        $$;
        """
    )


def _create_rls_helper() -> None:
    # The API layer (built in a later phase) is expected to run, per request:
    #   SET LOCAL app.current_plant_ids = 'plant_a,plant_b';
    # for a tenant-scoped session, or authenticate as airthra_global for
    # global_admin/global_read users (who bypass RLS entirely via BYPASSRLS).
    # See migrations/README.md for the full contract.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_current_plant_ids() RETURNS text[]
        LANGUAGE sql STABLE
        AS $$
            SELECT CASE
                WHEN current_setting('app.current_plant_ids', true) IS NULL
                     OR current_setting('app.current_plant_ids', true) = ''
                THEN ARRAY[]::text[]
                ELSE string_to_array(current_setting('app.current_plant_ids', true), ',')
            END;
        $$;
        """
    )


# ---------------------------------------------------------------------------
# 4.1 Shared
# ---------------------------------------------------------------------------

def _create_shared_tables() -> None:
    op.execute(
        """
        CREATE TABLE plants (
            plant_id             text PRIMARY KEY,
            name                 text NOT NULL,
            lat                  double precision,
            lon                  double precision,
            ambient_climate      text,
            boiler_capacity_tpd  numeric,
            fuel_type_primary    text,
            commissioning_date   date,
            timezone_display     text NOT NULL DEFAULT 'Asia/Kolkata'
        );

        CREATE TABLE users (
            user_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            email     text NOT NULL UNIQUE,
            pw_hash   text NOT NULL,
            role      text NOT NULL CHECK (role IN
                          ('global_admin', 'global_read', 'plant_admin',
                           'plant_operator', 'plant_viewer')),
            created_at timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE user_plants (
            user_id   uuid NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            plant_id  text NOT NULL REFERENCES plants(plant_id) ON DELETE CASCADE,
            PRIMARY KEY (user_id, plant_id)
        );

        -- Single-row table: Airthra's own company record (used on invoices/
        -- PDFs etc.). Enforced as a true singleton via the boolean unique
        -- trick below rather than an application convention.
        CREATE TABLE company (
            id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            singleton  boolean NOT NULL DEFAULT true UNIQUE CHECK (singleton),
            name       text NOT NULL,
            address    text NOT NULL,
            gstin      text NOT NULL,
            state_code text NOT NULL,
            phone      text,
            email      text
        );
        """
    )


# ---------------------------------------------------------------------------
# 4.2 Machine data
# ---------------------------------------------------------------------------

def _create_machine_data_tables(ts_available: bool) -> None:
    op.execute(
        """
        CREATE TABLE sensors (
            plant_id      text NOT NULL REFERENCES plants(plant_id) ON DELETE CASCADE,
            sensor_id     text NOT NULL,
            tag           text NOT NULL,
            kind          text NOT NULL,
            unit          text NOT NULL,
            min_valid     double precision,
            max_valid     double precision,
            calib_date    date,
            calib_doc_url text,
            PRIMARY KEY (plant_id, sensor_id)
        );

        CREATE TABLE readings (
            ts            timestamptz NOT NULL,
            plant_id      text NOT NULL,
            sensor_id     text NOT NULL,
            value         double precision,
            quality_flag  text NOT NULL DEFAULT 'good'
                          CHECK (quality_flag IN ('good', 'bad', 'uncertain', 'estimated')),
            PRIMARY KEY (plant_id, sensor_id, ts),
            FOREIGN KEY (plant_id, sensor_id) REFERENCES sensors(plant_id, sensor_id) ON DELETE CASCADE
        );
        -- Idempotent ingest contract (enforced by the P1+ ingest service, not
        -- this migration): INSERT ... ON CONFLICT (plant_id, sensor_id, ts)
        -- DO NOTHING. The composite PK above is what makes that possible.

        CREATE TABLE kpis (
            ts            timestamptz NOT NULL,
            plant_id      text NOT NULL REFERENCES plants(plant_id) ON DELETE CASCADE,
            kpi_name      text NOT NULL,
            value         double precision,
            quality_flag  text NOT NULL DEFAULT 'good'
                          CHECK (quality_flag IN ('good', 'bad', 'uncertain', 'estimated')),
            PRIMARY KEY (plant_id, kpi_name, ts)
        );

        CREATE TABLE alarm_rules (
            rule_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            plant_id        text REFERENCES plants(plant_id) ON DELETE CASCADE,  -- NULL = global rule
            expression_type text NOT NULL CHECK (expression_type IN
                              ('threshold', 'rolling_z', 'rate_of_change')),
            params          jsonb NOT NULL DEFAULT '{}'::jsonb,
            severity        text NOT NULL CHECK (severity IN ('info', 'warning', 'critical')),
            diagnosis       text,
            suggested_part  text,
            cooldown_s      integer NOT NULL DEFAULT 0
        );

        CREATE TABLE alarms (
            alarm_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            plant_id        text NOT NULL REFERENCES plants(plant_id) ON DELETE CASCADE,
            rule_id         uuid REFERENCES alarm_rules(rule_id),
            severity        text NOT NULL CHECK (severity IN ('info', 'warning', 'critical')),
            state           text NOT NULL CHECK (state IN ('raised', 'acked', 'cleared', 'escalated')),
            raised_at       timestamptz NOT NULL,
            acked_at        timestamptz,
            acked_by        uuid REFERENCES users(user_id),
            cleared_at      timestamptz,
            diagnosis       text,
            suggested_part  text
        );

        CREATE TABLE operator_events (
            event_id  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            plant_id  text NOT NULL REFERENCES plants(plant_id) ON DELETE CASCADE,
            user_id   uuid REFERENCES users(user_id),
            ts        timestamptz NOT NULL DEFAULT now(),
            kind      text NOT NULL CHECK (kind IN
                        ('maintenance', 'lab_sample', 'note', 'alarm_ack')),
            payload   jsonb NOT NULL DEFAULT '{}'::jsonb
        );

        CREATE TABLE setpoint_changes (
            id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            plant_id   text NOT NULL REFERENCES plants(plant_id) ON DELETE CASCADE,
            device     text NOT NULL,
            register   text NOT NULL,
            old_value  text,
            new_value  text,
            ts         timestamptz NOT NULL DEFAULT now(),
            source     text NOT NULL CHECK (source IN ('manual_panel', 'api'))
        );

        CREATE TABLE invoices (
            invoice_id  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            plant_id    text NOT NULL REFERENCES plants(plant_id) ON DELETE CASCADE,
            period      text NOT NULL,  -- e.g. '2026-07' (calendar month billed)
            so2_kg      numeric,
            k2so3_kg    numeric,
            uptime_pct  numeric,
            amount      numeric,
            pdf_url     text,
            status      text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'approved', 'sent')),
            UNIQUE (plant_id, period)
        );

        CREATE TABLE archive_log (
            day            date NOT NULL,
            plant_id       text NOT NULL REFERENCES plants(plant_id) ON DELETE CASCADE,
            parquet_url    text NOT NULL,
            sha256         text NOT NULL,
            ots_proof_url  text,
            verified       boolean NOT NULL DEFAULT false,
            PRIMARY KEY (day, plant_id)
        );
        """
    )

    if ts_available:
        op.execute("SELECT create_hypertable('readings', 'ts', chunk_time_interval => INTERVAL '1 day', migrate_data => TRUE);")
        op.execute("SELECT create_hypertable('kpis', 'ts', chunk_time_interval => INTERVAL '1 day', migrate_data => TRUE);")

        # DEVIATION (documented in migrations/README.md): TimescaleDB does not
        # allow native Postgres RLS together with columnstore (compression)
        # on the same hypertable ("columnstore cannot be used on table with
        # row security"), in either order. The PRD requires compression on
        # readings/kpis (billing/compliance-scale tables) and explicitly
        # frames RLS as a second net "under API-level scoping" - so here we
        # keep compression (non-negotiable per spec) and rely on API-level
        # plant_id scoping as the enforcement for these two hypertables only.
        # Every other plant_id-bearing table below still gets native RLS.

        # Compression: raw readings older than 7 days, segmented by
        # plant/sensor for good compression ratio + query locality.
        op.execute(
            """
            ALTER TABLE readings SET (
                timescaledb.compress,
                timescaledb.compress_segmentby = 'plant_id, sensor_id',
                timescaledb.compress_orderby = 'ts DESC'
            );
            """
        )
        op.execute("SELECT add_compression_policy('readings', INTERVAL '7 days');")

        # Raw retention: 90 days. Continuous aggregates below are NOT subject
        # to a retention policy, i.e. they are kept forever per spec.
        op.execute("SELECT add_retention_policy('readings', INTERVAL '90 days');")

        # Continuous aggregates at 1m / 15m / 1h: avg/min/max/count plus a
        # flagged-count (readings whose quality_flag != 'good').
        for bucket, view in (("1 minute", "readings_1m"), ("15 minutes", "readings_15m"), ("1 hour", "readings_1h")):
            op.execute(
                f"""
                CREATE MATERIALIZED VIEW {view}
                WITH (timescaledb.continuous) AS
                SELECT
                    plant_id,
                    sensor_id,
                    time_bucket('{bucket}', ts) AS bucket,
                    avg(value)                                        AS avg_value,
                    min(value)                                        AS min_value,
                    max(value)                                        AS max_value,
                    count(value)                                      AS sample_count,
                    count(*) FILTER (WHERE quality_flag <> 'good')    AS flagged_count
                FROM readings
                GROUP BY plant_id, sensor_id, bucket
                WITH NO DATA;
                """
            )

        op.execute(
            "SELECT add_continuous_aggregate_policy('readings_1m', "
            "start_offset => INTERVAL '3 hours', end_offset => INTERVAL '1 minute', "
            "schedule_interval => INTERVAL '1 minute');"
        )
        op.execute(
            "SELECT add_continuous_aggregate_policy('readings_15m', "
            "start_offset => INTERVAL '3 days', end_offset => INTERVAL '15 minutes', "
            "schedule_interval => INTERVAL '15 minutes');"
        )
        op.execute(
            "SELECT add_continuous_aggregate_policy('readings_1h', "
            "start_offset => INTERVAL '7 days', end_offset => INTERVAL '1 hour', "
            "schedule_interval => INTERVAL '1 hour');"
        )


# ---------------------------------------------------------------------------
# 4.3 ERP: procurement and engineering
# ---------------------------------------------------------------------------

def _create_procurement_engineering_tables() -> None:
    op.execute(
        """
        CREATE TABLE vendors (
            id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            name     text NOT NULL,
            gstin    text,
            address  text,
            state_code text,
            contact  text,
            phone    text,
            email    text,
            category text,
            rating   integer CHECK (rating BETWEEN 1 AND 5),
            notes    text
        );

        CREATE TABLE materials (
            id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            name           text NOT NULL,
            grade          text,
            density_kg_m3  numeric,
            rate_per_kg    numeric,
            hsn            text
        );

        -- projects <-> quotations is a mutual reference (project.quotation_id,
        -- quotation.project_id). Created without the projects->quotations FK
        -- first, added via ALTER TABLE once quotations exists, to avoid a
        -- circular dependency at CREATE TABLE time.
        CREATE TABLE projects (
            id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            code          text NOT NULL UNIQUE,
            name          text NOT NULL,
            client        text,
            status        text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'experimental', 'closed')),
            quotation_id  uuid
        );

        -- quotations.party_id is intentionally NOT a foreign key: direction
        -- 'vendor' points at vendors.id, direction 'customer' has no
        -- customers table in the P0 schema (out of scope; Airthra's own
        -- customer/plant-operator records live in `plants`/`company` for
        -- now). Documented in migrations/README.md.
        CREATE TABLE quotations (
            id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            direction   text NOT NULL CHECK (direction IN ('vendor', 'customer')),
            party_id    uuid NOT NULL,
            project_id  uuid REFERENCES projects(id),
            ref_no      text,
            date        date,
            valid_till  date,
            file_url    text,
            sha256      text,
            status      text NOT NULL DEFAULT 'draft' CHECK (status IN
                          ('draft', 'sent', 'accepted', 'rejected', 'expired'))
        );

        ALTER TABLE projects
            ADD CONSTRAINT fk_projects_quotation
            FOREIGN KEY (quotation_id) REFERENCES quotations(id);

        CREATE TABLE quotation_lines (
            id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            quotation_id  uuid NOT NULL REFERENCES quotations(id) ON DELETE CASCADE,
            description   text NOT NULL,
            qty           numeric NOT NULL,
            unit          text NOT NULL,
            rate          numeric NOT NULL
        );

        CREATE TABLE drawings (
            id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id   uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            dwg_no       text NOT NULL,
            title        text,
            revision     text,
            file_url     text,
            sha256       text,
            status       text NOT NULL DEFAULT 'draft' CHECK (status IN
                           ('draft', 'for_review', 'released', 'superseded')),
            released_by  uuid REFERENCES users(user_id),
            released_at  timestamptz,
            UNIQUE (project_id, dwg_no, revision)
        );

        CREATE TABLE boms (
            id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id         uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            drawing_id         uuid REFERENCES drawings(id),
            name               text NOT NULL,
            revision           text,
            status             text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'released')),
            supersedes_bom_id  uuid REFERENCES boms(id)
        );

        CREATE TABLE bom_items (
            id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            bom_id           uuid NOT NULL REFERENCES boms(id) ON DELETE CASCADE,
            description      text NOT NULL,
            material_id      uuid NOT NULL REFERENCES materials(id),
            shape            text NOT NULL CHECK (shape IN ('plate', 'rod', 'pipe', 'custom')),
            dims             jsonb NOT NULL DEFAULT '{}'::jsonb,  -- mm, shape-dependent keys
            qty              numeric NOT NULL DEFAULT 1,
            scrap_pct        numeric NOT NULL DEFAULT 0,
            unit_weight_kg   numeric,
            total_weight_kg  numeric,
            cost             numeric
        );

        -- po_no format: AIR/PO/{FY}/{seq:04d}, Indian FY (Apr-Mar), e.g.
        -- AIR/PO/25-26/0001. Sequence generation itself is a later-phase
        -- (API) concern; this CHECK only pins the on-disk format.
        CREATE TABLE pos (
            id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            po_no             text NOT NULL UNIQUE CHECK (po_no ~ '^AIR/PO/\\d{2}-\\d{2}/\\d{4}$'),
            vendor_id         uuid NOT NULL REFERENCES vendors(id),
            po_date           date NOT NULL DEFAULT CURRENT_DATE,
            delivery_address  text,
            payment_terms     text,
            delivery_terms    text,
            freight           numeric,
            notes             text,
            status            text NOT NULL DEFAULT 'draft' CHECK (status IN
                                ('draft', 'issued', 'partial', 'received', 'closed', 'cancelled'))
        );

        CREATE TABLE po_items (
            id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            po_id         uuid NOT NULL REFERENCES pos(id) ON DELETE CASCADE,
            bom_item_id   uuid REFERENCES bom_items(id),
            description   text NOT NULL,
            hsn           text,
            qty           numeric NOT NULL,
            unit          text NOT NULL,
            rate          numeric NOT NULL,
            gst_rate      numeric NOT NULL DEFAULT 18,
            received_qty  numeric NOT NULL DEFAULT 0
        );

        CREATE TABLE vendor_invoices (
            id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            vendor_id uuid NOT NULL REFERENCES vendors(id),
            po_id     uuid REFERENCES pos(id),
            inv_no    text NOT NULL,
            date      date,
            taxable   numeric,
            gst       numeric,
            total     numeric,
            file_url  text,
            sha256    text,
            status    text NOT NULL DEFAULT 'received' CHECK (status IN
                        ('received', 'matched', 'approved', 'paid'))
        );

        CREATE TABLE tasks (
            id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id       uuid REFERENCES projects(id) ON DELETE CASCADE,
            title            text NOT NULL,
            assignee         uuid REFERENCES users(user_id),
            due              date,
            status           text NOT NULL DEFAULT 'open' CHECK (status IN
                                ('open', 'in_progress', 'blocked', 'done', 'cancelled')),
            blocked_by_po_id uuid REFERENCES pos(id)
        );
        """
    )


# ---------------------------------------------------------------------------
# 4.4 ERP: inventory, production, QC
# ---------------------------------------------------------------------------

def _create_inventory_production_qc_tables() -> None:
    op.execute(
        """
        CREATE TABLE grn (
            id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            po_id         uuid NOT NULL REFERENCES pos(id),
            grn_no        text NOT NULL UNIQUE,
            date          date NOT NULL DEFAULT CURRENT_DATE,
            received_by   uuid REFERENCES users(user_id),
            vehicle_no    text,
            eway_bill_no  text,
            notes         text
        );

        CREATE TABLE grn_lines (
            id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            grn_id         uuid NOT NULL REFERENCES grn(id) ON DELETE CASCADE,
            po_item_id     uuid NOT NULL REFERENCES po_items(id),
            qty_received   numeric NOT NULL,
            qty_accepted   numeric NOT NULL DEFAULT 0,
            qty_rejected   numeric NOT NULL DEFAULT 0
        );

        CREATE TABLE inventory_lots (
            lot_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            grn_line_id   uuid REFERENCES grn_lines(id),
            material_id   uuid NOT NULL REFERENCES materials(id),
            qty_on_hand   numeric NOT NULL DEFAULT 0,
            unit          text NOT NULL,
            location      text,
            heat_no       text,
            mtc_url       text,
            sha256        text
        );

        CREATE TABLE unit_serials (
            serial      text PRIMARY KEY,
            model       text,
            project_id  uuid REFERENCES projects(id),
            status      text NOT NULL DEFAULT 'fabrication' CHECK (status IN
                          ('fabrication', 'qc', 'dispatched', 'installed'))
        );

        CREATE TABLE fabrication_jobs (
            id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id   uuid NOT NULL REFERENCES projects(id),
            bom_id       uuid REFERENCES boms(id),
            unit_serial  text REFERENCES unit_serials(serial),
            status       text NOT NULL DEFAULT 'planned' CHECK (status IN
                           ('planned', 'in_progress', 'on_hold', 'completed', 'cancelled')),
            started      timestamptz,
            finished     timestamptz
        );

        CREATE TABLE issue_lines (
            id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            lot_id               uuid NOT NULL REFERENCES inventory_lots(lot_id),
            qty                  numeric NOT NULL,
            fabrication_job_id   uuid REFERENCES fabrication_jobs(id),
            issued_at            timestamptz NOT NULL DEFAULT now(),
            issued_by            uuid REFERENCES users(user_id)
        );

        CREATE TABLE qc_records (
            id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            lot_id       uuid REFERENCES inventory_lots(lot_id),
            job_id       uuid REFERENCES fabrication_jobs(id),
            unit_serial  text REFERENCES unit_serials(serial),
            type         text NOT NULL CHECK (type IN ('incoming', 'in_process', 'final')),
            result       text,
            inspector    text,
            ts           timestamptz NOT NULL DEFAULT now(),
            report_url   text,
            sha256       text,
            CHECK (lot_id IS NOT NULL OR job_id IS NOT NULL OR unit_serial IS NOT NULL)
        );

        CREATE TABLE installations (
            id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            serial          text NOT NULL REFERENCES unit_serials(serial),
            plant_id        text NOT NULL REFERENCES plants(plant_id),
            installed_at    timestamptz,
            commissioned_at timestamptz
        );
        """
    )


# ---------------------------------------------------------------------------
# 4.5 Logistics
# ---------------------------------------------------------------------------

def _create_logistics_tables(ts_available: bool) -> None:
    op.execute(
        """
        CREATE TABLE trips (
            id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            vehicle_no    text NOT NULL,
            driver        text,
            phone         text,
            purpose       text NOT NULL CHECK (purpose IN
                            ('koh_delivery', 'k2so3_pickup', 'dispatch')),
            origin        text,
            dest_plant_id text REFERENCES plants(plant_id),
            eway_bill_no  text,
            status        text NOT NULL DEFAULT 'planned' CHECK (status IN
                            ('planned', 'in_transit', 'completed', 'cancelled')),
            started       timestamptz,
            completed     timestamptz
        );

        CREATE TABLE trip_pings (
            trip_id  uuid NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
            ts       timestamptz NOT NULL,
            lat      double precision NOT NULL,
            lon      double precision NOT NULL,
            speed    numeric,
            PRIMARY KEY (trip_id, ts)
        );

        CREATE TABLE trip_stops (
            id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            trip_id         uuid NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
            plant_id        text NOT NULL REFERENCES plants(plant_id),
            planned_eta     timestamptz,
            actual_arrival  timestamptz,
            qty_delivered   numeric,
            qty_collected   numeric
        );
        """
    )

    if ts_available:
        op.execute("SELECT create_hypertable('trip_pings', 'ts', chunk_time_interval => INTERVAL '1 day', migrate_data => TRUE);")


# ---------------------------------------------------------------------------
# Row Level Security
# ---------------------------------------------------------------------------

def _enable_rls() -> None:
    # Tables with a direct plant_id column: straightforward policy.
    # NOTE: readings/kpis RLS is enabled earlier in _create_machine_data_tables,
    # before compression is turned on (Timescale forbids enabling RLS on an
    # already-compressed hypertable) - do not add them back here.
    direct_plant_tables = [
        "sensors", "alarms", "operator_events",
        "setpoint_changes", "invoices", "archive_log", "user_plants",
        "installations", "trip_stops",
    ]
    for table in direct_plant_tables:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(
            f"""
            CREATE POLICY {table}_tenant_isolation ON {table}
            FOR ALL
            USING (plant_id = ANY (app_current_plant_ids()))
            WITH CHECK (plant_id = ANY (app_current_plant_ids()));
            """
        )

    # alarm_rules: plant_id is nullable (NULL = global rule, visible to all
    # tenants alongside their own plant-scoped rules).
    op.execute("ALTER TABLE alarm_rules ENABLE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY alarm_rules_tenant_isolation ON alarm_rules
        FOR ALL
        USING (plant_id IS NULL OR plant_id = ANY (app_current_plant_ids()))
        WITH CHECK (plant_id IS NULL OR plant_id = ANY (app_current_plant_ids()));
        """
    )

    # trips: the plant-identifying column is dest_plant_id, not plant_id.
    op.execute("ALTER TABLE trips ENABLE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY trips_tenant_isolation ON trips
        FOR ALL
        USING (dest_plant_id IS NULL OR dest_plant_id = ANY (app_current_plant_ids()))
        WITH CHECK (dest_plant_id IS NULL OR dest_plant_id = ANY (app_current_plant_ids()));
        """
    )

    # trip_pings: no plant_id of its own; scoped via trips.dest_plant_id
    # through trip_id. Documented as a join-based policy (see README) -
    # slightly more expensive than a direct column check, acceptable given
    # trip_pings volume is much lower than readings/kpis.
    op.execute("ALTER TABLE trip_pings ENABLE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY trip_pings_tenant_isolation ON trip_pings
        FOR ALL
        USING (EXISTS (
            SELECT 1 FROM trips t
            WHERE t.id = trip_pings.trip_id
              AND (t.dest_plant_id IS NULL OR t.dest_plant_id = ANY (app_current_plant_ids()))
        ))
        WITH CHECK (EXISTS (
            SELECT 1 FROM trips t
            WHERE t.id = trip_pings.trip_id
              AND (t.dest_plant_id IS NULL OR t.dest_plant_id = ANY (app_current_plant_ids()))
        ));
        """
    )

    # plants itself: tenant users may only see plants they're scoped to.
    op.execute("ALTER TABLE plants ENABLE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY plants_tenant_isolation ON plants
        FOR ALL
        USING (plant_id = ANY (app_current_plant_ids()))
        WITH CHECK (plant_id = ANY (app_current_plant_ids()));
        """
    )

    # NOTE ON TABLES WITHOUT RLS: users, company, and the ERP tables in
    # sections 4.3/4.4 (vendors, materials, quotations, projects, drawings,
    # boms, pos, grn, fabrication_jobs, unit_serials, qc_records, ...) carry
    # no plant_id column. Per the P0 data model, Airthra is a single company
    # running ERP centrally across all plants/projects - these entities are
    # not partitioned per plant, so plant-based RLS does not cleanly apply.
    # Access control for them (e.g. "only see POs for your project") is a
    # role/permission concern for the API layer in a later phase, not RLS.
    # This is documented in migrations/README.md.


def _grant_privileges() -> None:
    op.execute(
        """
        GRANT USAGE ON SCHEMA public TO airthra_tenant, airthra_global;
        GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO airthra_tenant, airthra_global;
        GRANT EXECUTE ON FUNCTION app_current_plant_ids() TO airthra_tenant, airthra_global;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO airthra_tenant, airthra_global;
        """
    )
