"""Department-scoped users: a new `dept_user` role plus a `department`
column, for staff who should reach exactly one business function's ERP/
admin pages (finance, procurement, engineering, sales, logistics) and
nothing else - not full global_admin/global_read, and not the plant-scoped
tenant roles (those are a different axis: which plant, not which function).

Every ERP table this touches (vendors, materials, boms, pos, grn,
invoices, quotations, ...) already carries no plant_id and no RLS (see
migrations/versions/0001_initial_schema.py, "NOTE ON TABLES WITHOUT RLS")
- department access control is therefore an API-layer concern
(api/dept_deps.py), exactly like the existing global_admin/global_read
split in api/erp_deps.py. This migration only needs to make `users` able
to represent the new role/department pair; it does not touch RLS.

The two CHECK constraints keep the data self-consistent: `role` gains
'dept_user' as a fifth allowed value, and `department` is NOT NULL if and
only if role = 'dept_user' (a global/plant user has no department; a
dept_user always has exactly one).
"""
from __future__ import annotations

from alembic import op

revision = "0013_department_users"
down_revision = "0012_crm_leads"
branch_labels = None
depends_on = None

_DEPARTMENTS = ("finance", "procurement", "engineering", "sales", "logistics")


def upgrade() -> None:
    op.execute("ALTER TABLE users DROP CONSTRAINT users_role_check;")
    op.execute(
        """
        ALTER TABLE users ADD CONSTRAINT users_role_check CHECK (role IN
            ('global_admin', 'global_read', 'plant_admin',
             'plant_operator', 'plant_viewer', 'dept_user'));
        """
    )
    op.execute("ALTER TABLE users ADD COLUMN department text;")
    op.execute(
        f"""
        ALTER TABLE users ADD CONSTRAINT users_department_valid CHECK (
            department IS NULL OR department IN {_DEPARTMENTS}
        );
        """
    )
    op.execute(
        """
        ALTER TABLE users ADD CONSTRAINT users_department_matches_role CHECK (
            (role = 'dept_user') = (department IS NOT NULL)
        );
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_department_matches_role;")
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_department_valid;")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS department;")
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check;")
    op.execute(
        """
        ALTER TABLE users ADD CONSTRAINT users_role_check CHECK (role IN
            ('global_admin', 'global_read', 'plant_admin',
             'plant_operator', 'plant_viewer'));
        """
    )
