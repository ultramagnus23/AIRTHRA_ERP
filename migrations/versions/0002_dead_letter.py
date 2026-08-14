"""P1: dead-letter table for rejected/invalid ingest payloads.

Minimal, scoped addition for the ingest service (P1 "data spine"): readings
or setpoint_changes messages that fail manifest validation (unknown
plant_id/sensor_id, out-of-range value not already flagged, malformed
payload, etc.) are written here instead of being silently dropped, per the
"no silent failures" rule. Does not touch any P0 table.

Revision ID: 0002_dead_letter
Revises: 0001_initial_schema
Create Date: 2026-08-14
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0002_dead_letter"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE dead_letter_readings (
            id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            plant_id      text,
            sensor_id     text,
            ts            timestamptz,
            raw_payload   jsonb NOT NULL,
            reason        text NOT NULL,
            received_at   timestamptz NOT NULL DEFAULT now()
        );

        CREATE INDEX ix_dead_letter_readings_received_at ON dead_letter_readings (received_at);
        CREATE INDEX ix_dead_letter_readings_plant_id ON dead_letter_readings (plant_id);
        """
    )

    # Same grants as every other P0 table (see 0001's _grant_privileges) -
    # the ingest service writes via the airthra_global role.
    op.execute(
        """
        GRANT SELECT, INSERT, UPDATE, DELETE ON dead_letter_readings TO airthra_tenant, airthra_global;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS dead_letter_readings;")
