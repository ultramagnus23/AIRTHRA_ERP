"""Tenant onboarding: audit_log + user_invites

Closes SHIPPING.md item 0.2 - the platform previously had no way to add a
plant or a user except running seed/seed.py by hand against the database,
which also unconditionally resets the global_admin password on every run
(see that script's production guard, migration 0006's sibling work). This
is the single largest software blocker to onboarding a second real
customer.

Two new tables, no changes to the existing users/plants/user_plants shape
- those were already correctly modeled, just unreachable through the API.

audit_log
    Every admin-surface mutation (plant created, user created, invite
    accepted) gets one row here. No RLS: this table is inherently
    cross-tenant (an admin action often targets a specific plant, but the
    log itself is a global_admin-only surface), the same documented
    decision already made for `users`/`company` in migrations/README.md.

user_invites
    Replaces "the admin picks a password and tells the user" with a
    token-based accept flow: the new user sets their own password, so no
    human ever transmits a real credential over Slack/WhatsApp/email.
    token_hash stores sha256(token), never the raw token - same principle
    as password hashing, so a leaked audit_log or a DB dump doesn't hand
    out live invite tokens. The raw token exists only in the API response
    at creation time and in the URL the admin copies to the new user.
"""
from __future__ import annotations

from alembic import op

revision = "0007_tenant_onboarding"
down_revision = "0006_ml_ground_truth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE audit_log (
            log_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            actor_user_id  uuid REFERENCES users(user_id),
            action         text NOT NULL,
            target_type    text NOT NULL,
            target_id      text NOT NULL,
            detail         jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at     timestamptz NOT NULL DEFAULT now()
        );
        """
    )
    op.execute("CREATE INDEX audit_log_created_idx ON audit_log (created_at DESC);")
    op.execute("CREATE INDEX audit_log_target_idx ON audit_log (target_type, target_id);")

    op.execute(
        """
        CREATE TABLE user_invites (
            invite_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id     uuid NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            token_hash  text NOT NULL UNIQUE,
            expires_at  timestamptz NOT NULL,
            used_at     timestamptz,
            created_at  timestamptz NOT NULL DEFAULT now()
        );
        """
    )
    # One active invite per user is the common case, but a re-invite
    # (lost link, expired) creates a new row rather than mutating the old
    # one - used_at/expires_at on the old row stay as an honest history of
    # "this link was issued and went stale", not silently overwritten.
    op.execute("CREATE INDEX user_invites_user_idx ON user_invites (user_id);")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_invites;")
    op.execute("DROP TABLE IF EXISTS audit_log;")
