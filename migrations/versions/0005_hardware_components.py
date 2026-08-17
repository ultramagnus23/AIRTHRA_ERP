"""Add hardware_components: the edge-unit electrical/instrumentation
register, sourced from the FEED Addendum A (Rev 2) Full Instrument
Schedule (Section 2) and DAQ Hardware BOM (Section 4.1).

A tracked reference register for the physical hardware stack that goes
into each plant's edge unit - compute/power, gas & CEMS sensors, process
sensors/translators, comms/actuators, and field-survival hardware, plus
the process-tagged instrument schedule (tag_id, tier, segment) used by
the fault decision trees in the FEED document. This is distinct from the
fabrication `materials` catalog (raw steel/pipe stock priced by weight):
these are discrete electronic/instrumentation components tracked by
item + spec + (where applicable) a process tag and diagnostic purpose.

No plant_id (company-wide reference BOM, not per-plant inventory -
mirrors the same "ERP tables carry no plant_id" pattern documented in
migrations/README.md for vendors/materials/etc). No RLS, consistent
with those other ERP tables.

Revision ID: 0005_hardware_components
Revises: 0004_trip_token
Create Date: 2026-08-17
"""
from alembic import op

revision = "0005_hardware_components"
down_revision = "0004_trip_token"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE hardware_components (
            id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            category        text NOT NULL,
            category_order  int NOT NULL,
            sort_order      int NOT NULL,
            item            text NOT NULL,
            spec_function   text,
            -- Process instrument schedule fields (FEED Addendum A Section 2).
            -- Nullable: generic DAQ/survival-gear line items (e.g. "Raspberry
            -- Pi 4") have no process tag/tier/segment/cost; tagged process
            -- instruments (e.g. "AT-01") do.
            tag_id          text,
            tier            int,           -- 1=safety-critical, 2=diagnostic, 3=ML enrichment
            segment         text,          -- plant segment code, e.g. "G-01a" (see FEED Section 1.1)
            cost_inr        numeric(10, 2),
            created_at      timestamptz NOT NULL DEFAULT now()
        );

        CREATE INDEX ix_hardware_components_category_order
            ON hardware_components (category_order, sort_order);
        CREATE INDEX ix_hardware_components_tag_id
            ON hardware_components (tag_id) WHERE tag_id IS NOT NULL;
        """
    )
    op.execute(
        """
        GRANT SELECT, INSERT, UPDATE, DELETE ON hardware_components TO airthra_tenant, airthra_global;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS hardware_components;")
