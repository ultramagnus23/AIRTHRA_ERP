"""ML ground-truth events + quality_flag cause separation

Addresses points 3 and 4 of the industrial IoT review (see
INDUSTRIAL_READINESS.md).

WHY BOTH IN ONE MIGRATION
-------------------------
They are the same problem seen from two sides: a model cannot learn from
this plant's data unless it can tell *why* a value is untrustworthy
(quality_flag) and *what a human did* to cause a step change
(operator_events). Splitting them across two migrations would leave a
window where the calibration flag exists but the calibration event does
not, which is exactly the inconsistent state that produces bad training
labels.

1. operator_events.kind
   Was four generic values with intent buried in a free-text payload
   note. Free text is not a label: "changed stator", "Stator swap P101"
   and "replaced pump stator" are three unparseable strings. Adds the
   specific, taggable maintenance actions that ML ground truth actually
   requires, keyed to the FEED register's own equipment tags.

   The existing four are retained, not replaced - historical rows carry
   them and there is nothing to migrate them *to* (a past 'maintenance'
   row's real meaning is unrecoverable). New UI writes specific kinds.

2. readings/kpis.quality_flag
   CORRECTION to an earlier reading of this schema: migration
   0003_quality_flag_fidelity already replaced the original
   ('good','bad','uncertain','estimated') vocabulary with a
   cause-separated one - ('good','comm_error','out_of_range','frozen',
   'imputed'). The review's flags 1 (hardware fault) and 2 (out of
   range) were therefore ALREADY distinguishable, via comm_error and
   out_of_range, and the platform additionally carries `frozen`, a real
   failure mode the review did not list.

   The one genuine gap is the review's flag 3. There was no way to say
   "intentionally invalid right now - this sensor is being calibrated, or
   the line is purging". During a purge, readings were either wrongly
   'good' or wrongly flagged as a fault, which both raises false alarms
   and poisons training data with maintenance windows presented as
   anomalies.

   So this migration adds exactly `calibration` and `purge`, and touches
   nothing else in that vocabulary.

   Text values, not the review's integers 0-3: a stray `2` in a config
   file or a log line is unreadable, whereas `out_of_range` is
   self-documenting in every query, dashboard and stack trace it appears
   in. The ML pipeline filters on `quality_flag = 'good'` either way.
"""
from __future__ import annotations

from alembic import op

revision = "0006_ml_ground_truth"
down_revision = "0005_hardware_components"
branch_labels = None
depends_on = None


_OLD_EVENT_KINDS = "'maintenance', 'lab_sample', 'note', 'alarm_ack'"
_NEW_EVENT_KINDS = (
    _OLD_EVENT_KINDS + ", "
    # Reagent / consumable actions - step-change the solvent chemistry.
    "'koh_added', 'tote_changeout', "
    # Mechanical interventions - step-change thermal or pump behaviour.
    "'phe_cleaned', 'stator_changed', 'demister_cleaned', "
    # Upstream process changes outside Airthra's equipment.
    "'fuel_change', 'boiler_trip', "
    # Safety / instrument states.
    "'emergency_trip', 'sensor_calibration', 'purge_cycle'"
)

# The live vocabulary as left by 0003_quality_flag_fidelity - NOT 0001's
# original four values, which 0003 already replaced.
_OLD_QUALITY = "'good', 'comm_error', 'out_of_range', 'frozen', 'imputed'"
_NEW_QUALITY = _OLD_QUALITY + ", 'calibration', 'purge'"


def upgrade() -> None:
    op.execute("ALTER TABLE operator_events DROP CONSTRAINT IF EXISTS operator_events_kind_check;")
    op.execute(
        f"ALTER TABLE operator_events ADD CONSTRAINT operator_events_kind_check "
        f"CHECK (kind IN ({_NEW_EVENT_KINDS}));"
    )

    # Index for the ML feature path: "every ground-truth label for this
    # plant, newest first" is the access pattern for building training
    # windows around each maintenance action.
    op.execute(
        "CREATE INDEX IF NOT EXISTS operator_events_plant_ts_idx "
        "ON operator_events (plant_id, ts DESC);"
    )

    for table in ("readings", "kpis"):
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {table}_quality_flag_check;")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {table}_quality_flag_check "
            f"CHECK (quality_flag IN ({_NEW_QUALITY}));"
        )


def downgrade() -> None:
    # Rows written with a new kind/flag would violate the old CHECK, so
    # they are rewritten onto their closest old-vocabulary equivalent
    # rather than letting the constraint fail. This is lossy and one-way:
    # the specific cause is not recoverable afterwards.
    op.execute(
        "UPDATE operator_events SET kind = 'maintenance' "
        "WHERE kind IN ('koh_added', 'tote_changeout', 'phe_cleaned', 'stator_changed', "
        "'demister_cleaned', 'sensor_calibration', 'purge_cycle');"
    )
    op.execute(
        "UPDATE operator_events SET kind = 'note' "
        "WHERE kind IN ('fuel_change', 'boiler_trip', 'emergency_trip');"
    )
    op.execute("ALTER TABLE operator_events DROP CONSTRAINT IF EXISTS operator_events_kind_check;")
    op.execute(
        f"ALTER TABLE operator_events ADD CONSTRAINT operator_events_kind_check "
        f"CHECK (kind IN ({_OLD_EVENT_KINDS}));"
    )
    op.execute("DROP INDEX IF EXISTS operator_events_plant_ts_idx;")

    for table in ("readings", "kpis"):
        # A calibration/purge window has no honest equivalent in the old
        # vocabulary. 'frozen' is the least-wrong landing spot: it marks
        # the rows untrustworthy without claiming a hardware fault that
        # did not occur. Lossy and one-way, like the events remap above.
        op.execute(
            f"UPDATE {table} SET quality_flag = 'frozen' "
            f"WHERE quality_flag IN ('calibration', 'purge');"
        )
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {table}_quality_flag_check;")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {table}_quality_flag_check "
            f"CHECK (quality_flag IN ({_OLD_QUALITY}));"
        )
