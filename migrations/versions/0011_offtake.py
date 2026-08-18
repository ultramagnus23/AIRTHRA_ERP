"""Offtake: product batches (the chemical output, not the hardware) ->
QC -> CoA -> buyer allocation -> dispatch.

Closes enterprise spec Module 04. A real, previously-unmodeled gap: the
existing `qc_records` table (migration 0001) is scoped to lot_id/job_id/
unit_serial - all HARDWARE fabrication QC, for building the FGD skids
themselves. There was no table at all for the K2SO3 (and future K2S2O3)
fertilizer each plant physically produces as its operational OUTPUT -
the thing that gets sold to a buyer, which needs its own QC and
Certificate of Analysis, entirely separate from whether the skid that
made it was built correctly.

buyers
    Deliberately mirrors `vendors`' exact column shape (this codebase's
    established pattern for a commercial counterparty) - a buyer is a
    vendor in every structural sense except which direction goods/money
    move, matching quotations.direction's existing ('vendor', 'customer')
    distinction rather than inventing a different shape for the same
    kind of entity.

product_batches
    One row per production run. QC is NEVER auto-passed from sensor/KPI
    data - qc_status starts 'pending' and can only become 'passed'/
    'failed' via an explicit human-entered qc_records-equivalent action
    (api/routers/admin_offtake.py's record_qc), same "never fabricate
    a result from data alone" principle the platform already holds for
    readings/kpis. Allocation and CoA generation are both blocked until
    qc_status = 'passed' - a failed or untested batch cannot be sold or
    certified, enforced at the API layer with the status column here as
    the source of truth.

    coa_object_key / coa_sha256 record the generated Certificate of
    Analysis once issued (same "store the key, presign on read" pattern
    as documents/invoices, not a public file_url).
"""
from __future__ import annotations

from alembic import op

revision = "0011_offtake"
down_revision = "0010_bom_change_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE buyers (
            id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            name       text NOT NULL,
            gstin      text,
            address    text,
            state_code text,
            contact    text,
            phone      text,
            email      text,
            notes      text
        );
        """
    )

    op.execute(
        """
        CREATE TABLE product_batches (
            id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            plant_id         text NOT NULL REFERENCES plants(plant_id) ON DELETE CASCADE,
            batch_no         text NOT NULL,
            product_name     text NOT NULL,
            qty_kg           numeric NOT NULL CHECK (qty_kg > 0),
            produced_at      timestamptz NOT NULL DEFAULT now(),

            qc_status        text NOT NULL DEFAULT 'pending'
                                  CHECK (qc_status IN ('pending', 'passed', 'failed')),
            qc_result        text,
            qc_inspector     text,
            qc_notes         text,
            qc_at            timestamptz,

            status           text NOT NULL DEFAULT 'produced'
                                  CHECK (status IN ('produced', 'allocated', 'dispatched')),
            buyer_id         uuid REFERENCES buyers(id),
            rate_inr_per_kg  numeric,
            allocated_at     timestamptz,
            dispatched_at    timestamptz,

            coa_object_key   text,
            coa_sha256       text,
            coa_generated_at timestamptz,

            created_by       uuid REFERENCES users(user_id),
            created_at       timestamptz NOT NULL DEFAULT now(),

            UNIQUE (plant_id, batch_no),
            -- Enforced in sequence at the DB level, not just the API:
            -- can't be allocated/dispatched without a passed QC, can't be
            -- dispatched without being allocated first.
            CHECK (status = 'produced' OR qc_status = 'passed'),
            CHECK (status != 'dispatched' OR buyer_id IS NOT NULL)
        );
        """
    )
    op.execute("CREATE INDEX product_batches_plant_idx ON product_batches (plant_id);")
    op.execute("CREATE INDEX product_batches_status_idx ON product_batches (status);")

    # No RLS: product_batches is plant-scoped data, but per the same
    # decision as invoices/contracts this session, offtake is an
    # Airthra-internal admin surface (global_admin/global_read), not
    # exposed to tenant_read yet - a plant operator seeing their own
    # plant's batches is a real follow-up, not built in this pass.


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS product_batches;")
    op.execute("DROP TABLE IF EXISTS buyers;")
