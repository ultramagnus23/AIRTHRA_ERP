"""CRM: a lightweight lead pipeline, deliberately not an 11th department.

Closes the enterprise spec's Commercial/CRM section, which is explicit
that this should NOT become a giant module: "Make it a cross-cutting
layer... Lead -> Site assessment -> Technical feasibility -> Proposal ->
Contract -> Skid deployment -> Operations -> Billing -> Renewal /
expansion. Every deployed skid should have a commercial contract
attached." This migration is scoped to exactly that pipeline shape, one
table, no separate "opportunities"/"activities"/"tasks" sub-entities a
heavier CRM would have.

leads
    stage is the pipeline position, not a status flag - it only moves
    forward (enforced at the API layer, not the DB, since 'lost' can be
    reached from any stage and a rigid DB-level state machine would
    fight that). converted_plant_id is the actual tie to the rest of the
    platform: when a lead becomes a real deployment, it links to the
    plants row created via POST /admin/plants (migration 0007's tenant
    onboarding work) - completing "lead -> proposal -> contract ->
    deployed skid" as a real, followable chain instead of two disconnected
    systems that happen to both mention customers.
"""
from __future__ import annotations

from alembic import op

revision = "0012_crm_leads"
down_revision = "0011_offtake"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE leads (
            id                        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            company_name              text NOT NULL,
            contact_name              text,
            contact_email             text,
            contact_phone             text,
            source                    text,
            stage                     text NOT NULL DEFAULT 'lead'
                                          CHECK (stage IN
                                              ('lead', 'site_assessment', 'proposal',
                                               'contract_sent', 'won', 'lost')),
            estimated_boiler_capacity_tpd numeric,
            notes                     text,
            lost_reason               text,
            converted_plant_id        text REFERENCES plants(plant_id),
            assigned_to               uuid REFERENCES users(user_id),
            created_by                uuid REFERENCES users(user_id),
            created_at                timestamptz NOT NULL DEFAULT now(),
            updated_at                timestamptz NOT NULL DEFAULT now(),

            CHECK (stage != 'lost' OR lost_reason IS NOT NULL),
            CHECK (stage != 'won' OR converted_plant_id IS NOT NULL)
        );
        """
    )
    op.execute("CREATE INDEX leads_stage_idx ON leads (stage);")

    # No RLS: internal-only admin surface (global_admin/global_read), same
    # basis as contracts/audit_log/documents this session - leads aren't
    # tenant data, they're pre-tenant.


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS leads;")
