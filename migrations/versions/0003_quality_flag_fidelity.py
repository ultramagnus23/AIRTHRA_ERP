"""P1 follow-up: widen quality_flag to the PRD's exact 5-value vocabulary.

The original P0 migration modeled `readings.quality_flag` / `kpis.quality_flag`
as a 4-value text enum ('good','bad','uncertain','estimated'). The PRD's
global guardrails specify a distinct 5-value semantic instead:
    0 good, 1 comm error/timeout, 2 out of range, 3 frozen value, 4 imputed
Collapsing comm-error (1) and out-of-range (2) into a single 'bad' value
loses diagnostic fidelity the alarm engine (P3) and billing/MRV gap rules
(P7) need - e.g. "frozen sensor" must be distinguishable from "sensor out of
calibration range" to produce the right diagnosis/suggested_part.

This migration widens the CHECK constraint (default 'good' unaffected) and
remaps existing rows via the old-label -> new-label bridge below. Safe to
run on an empty or populated table.

Revision ID: 0003_quality_flag_fidelity
Revises: 0002_dead_letter
Create Date: 2026-08-14
"""
from alembic import op

revision = "0003_quality_flag_fidelity"
down_revision = "0002_dead_letter"
branch_labels = None
depends_on = None

NEW_VALUES = ("good", "comm_error", "out_of_range", "frozen", "imputed")

# Best-effort remap of any rows already written under the old 4-value enum.
# 'bad' is ambiguous (was comm_error OR out_of_range) - remapped to
# 'comm_error' as the more common P1 mock-fault case; this only matters for
# rows written before this migration runs, which in practice is none/few
# given P1 just landed.
OLD_TO_NEW = {
    "good": "good",
    "bad": "comm_error",
    "uncertain": "frozen",
    "estimated": "imputed",
}


def upgrade() -> None:
    for table in ("readings", "kpis"):
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT {table}_quality_flag_check;")
        for old, new in OLD_TO_NEW.items():
            if old == new:
                continue
            op.execute(
                f"UPDATE {table} SET quality_flag = '{new}' WHERE quality_flag = '{old}';"
            )
        values_sql = ", ".join(f"'{v}'" for v in NEW_VALUES)
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {table}_quality_flag_check "
            f"CHECK (quality_flag IN ({values_sql}));"
        )


def downgrade() -> None:
    OLD_VALUES = ("good", "bad", "uncertain", "estimated")
    NEW_TO_OLD = {
        "good": "good",
        "comm_error": "bad",
        "out_of_range": "bad",
        "frozen": "uncertain",
        "imputed": "estimated",
    }
    for table in ("readings", "kpis"):
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT {table}_quality_flag_check;")
        for new, old in NEW_TO_OLD.items():
            if old == new:
                continue
            op.execute(
                f"UPDATE {table} SET quality_flag = '{old}' WHERE quality_flag = '{new}';"
            )
        values_sql = ", ".join(f"'{v}'" for v in OLD_VALUES)
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {table}_quality_flag_check "
            f"CHECK (quality_flag IN ({values_sql}));"
        )
