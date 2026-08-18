"""Add users.is_active, so an admin can deactivate an account (revoke
login) without deleting the row - audit_log/created_by/user_plants
references, and the account's own history, all stay intact. Needed for
the admin user-management UI (POST/PATCH /admin/users): a deactivated
account must be rejected at login (api/routers/auth.py checks this),
not just hidden in a list.
"""
from __future__ import annotations

from alembic import op

revision = "0014_user_is_active"
down_revision = "0013_department_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN is_active boolean NOT NULL DEFAULT true;")


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS is_active;")
