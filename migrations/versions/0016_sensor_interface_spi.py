"""Add 'spi' to sensors.interface's allowed values, for the two MAX31865/
PT100 probes (TE-08, TE-09) confirmed 2026-09-13 from the Delhi
engineer's schematic - real SPI wiring (CE0/CE1), not yet a
'modbus'/'onewire'/'pms7003' device and not 'unconfirmed' either, since
its interface genuinely IS confirmed now, just via a fourth protocol the
original migration's CHECK constraint didn't anticipate.
"""
from __future__ import annotations

from alembic import op

revision = "0016_sensor_interface_spi"
down_revision = "0015_sensor_interface"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE sensors DROP CONSTRAINT IF EXISTS sensors_interface_check;")
    op.execute(
        """
        ALTER TABLE sensors ADD CONSTRAINT sensors_interface_check
        CHECK (interface IN ('modbus', 'onewire', 'pms7003', 'spi', 'unconfirmed'));
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE sensors DROP CONSTRAINT IF EXISTS sensors_interface_check;")
    op.execute(
        """
        ALTER TABLE sensors ADD CONSTRAINT sensors_interface_check
        CHECK (interface IN ('modbus', 'onewire', 'pms7003', 'unconfirmed'));
        """
    )
