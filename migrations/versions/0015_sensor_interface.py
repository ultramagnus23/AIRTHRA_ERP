"""Add sensors.interface, so a sensor can be tracked in the manifest before
its physical bus is confirmed - e.g. the ASAIR O2 sensor ordered for the
Goa pilot plant, whose interface (I2C/UART/analog) isn't decided yet.
Nullable/unconstrained-by-NOT-NULL on purpose: every sensor seeded before
this migration (the 7 original process tags, 15 DS18B20 probes, PMS7003
channels) predates this column and is backfilled by seed/seed.py on its
next run, not by this migration - there is no automated way to know which
bus each pre-existing row is actually wired to from inside a migration.
"""
from __future__ import annotations

from alembic import op

revision = "0015_sensor_interface"
down_revision = "0014_user_is_active"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE sensors ADD COLUMN interface text
        CHECK (interface IN ('modbus', 'onewire', 'pms7003', 'unconfirmed'));
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE sensors DROP COLUMN IF EXISTS interface;")
