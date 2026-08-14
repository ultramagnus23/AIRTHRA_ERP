"""P6: add trips.token for per-trip ping authentication.

Logistics trip pings (POST /logistics/trips/{id}/ping) are authenticated by
a per-trip random token generated at trip-creation time (edge/driver device
does not have a user JWT). The `trips` table has no column suited for this
(checked migrations/versions/0001_initial_schema.py - no token/secret
column exists), so this migration adds exactly one minimal column.

Coordination note: this is 0004, chained after 0003_quality_flag_fidelity
(the latest revision present in migrations/versions/ at the time this was
written). If another concurrent phase also added a 0004, chain after that
one instead - do not silently overwrite.

Revision ID: 0004_trip_token
Revises: 0003_quality_flag_fidelity
Create Date: 2026-08-14
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_trip_token"
down_revision = "0003_quality_flag_fidelity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("trips", sa.Column("token", sa.Text(), nullable=True))
    # Not UNIQUE NOT NULL at the DB level: existing rows (none expected pre-P6,
    # but keep the migration safe/idempotent-in-spirit) have no token yet, and
    # backfilling a real unique random token via SQL DEFAULT is unnecessary
    # complexity for a dev-scale table. The API always sets a token at
    # creation time (api/routers/logistics.py); uniqueness is de facto
    # guaranteed by generating from secrets.token_urlsafe(32).
    op.create_index("ix_trips_token", "trips", ["token"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_trips_token", table_name="trips")
    op.drop_column("trips", "token")
