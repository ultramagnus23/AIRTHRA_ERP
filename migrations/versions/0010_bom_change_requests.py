"""Engineering Change Management: formal request/approval before a
released BOM gets revised.

Closes the enterprise spec's Module 10 requirement:

    Change request -> reason -> affected components -> engineering
    approval -> new revision -> effective date -> affected units

api/routers/erp_boms.py already enforces release-immutability correctly
(a released BOM's rows can never be edited; POST .../revise creates a
new 'draft' row with supersedes_bom_id pointing back, so a deployed
skid's as-built record is never silently altered - this was already
correct P5 behaviour, not something this migration changes). What was
missing is the GOVERNANCE step in front of that: today, any erp_admin_user
can call POST .../revise with no recorded reason and no separate approver
- the requester and the approver are structurally the same click.

bom_change_requests
    One row per requested change. status starts 'pending'; an
    erp_admin_user approves (which atomically creates the new draft BOM
    via the same revise logic, linking resulting_bom_id) or rejects
    (with a reason, so a rejected request is a record, not silence).

    Deliberately NOT a replacement for POST /erp/boms/{id}/revise, which
    stays as a direct action for an admin making their own change with no
    separate approver - the formal ECR path is additive, for changes that
    need a reviewable trail, not a lockout of the existing endpoint. See
    api/routers/erp_boms.py's updated module docstring.
"""
from __future__ import annotations

from alembic import op

revision = "0010_bom_change_requests"
down_revision = "0009_documents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE bom_change_requests (
            id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            bom_id             uuid NOT NULL REFERENCES boms(id) ON DELETE CASCADE,
            reason             text NOT NULL,
            affected_note      text,
            requested_new_revision text NOT NULL,
            status             text NOT NULL DEFAULT 'pending'
                                    CHECK (status IN ('pending', 'approved', 'rejected')),
            requested_by       uuid REFERENCES users(user_id),
            requested_at       timestamptz NOT NULL DEFAULT now(),
            reviewed_by        uuid REFERENCES users(user_id),
            reviewed_at        timestamptz,
            review_note        text,
            resulting_bom_id   uuid REFERENCES boms(id),

            CHECK (status = 'pending' OR reviewed_by IS NOT NULL)
        );
        """
    )
    op.execute("CREATE INDEX bom_change_requests_bom_idx ON bom_change_requests (bom_id);")
    op.execute("CREATE INDEX bom_change_requests_status_idx ON bom_change_requests (status);")

    # No RLS: BOMs/projects are already company-wide reference data with
    # no plant_id/RLS (same as boms/bom_items themselves - see
    # migrations/README.md), scoped by erp_read_user/erp_admin_user role
    # checks at the API layer, not tenant isolation.


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS bom_change_requests;")
