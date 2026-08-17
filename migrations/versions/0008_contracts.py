"""Contracts: replace the hardcoded SO2_RATE_PER_KG env var with a real,
per-plant, per-period billing formula.

Directly closes the enterprise spec's own non-negotiable rule #8 ("don't
hard-code Airthra's current commercial model into the software") and
Module 09's requirement that the billing engine be contract-driven:
base fee + usage fee + performance fee - penalties, per contract.

Before this migration, workers/billing_worker.py multiplied every plant's
captured SO2 by ONE global rate (SO2_RATE_PER_KG, a single env var shared
across the whole fleet) - there was no way for two customers to be on
different commercial terms, which is not how Airthra actually sells this
(BOO contracts vary by site).

contracts
    One row per commercial agreement. A plant can have contract HISTORY
    (a superseded contract stays in the table, status='ended') but only
    ONE 'active' contract at a time - enforced by a partial unique index
    rather than at the application layer, so a race between two admin
    requests can't create two simultaneously-active contracts for the
    same plant.

    Deliberately NOT a rewrite of invoices.amount into a dozen columns -
    the formula stays simple (base + usage*kg, with an uptime-gated
    performance bonus/penalty) because that's what the current sensor
    manifest can actually evidence. revenue_share_pct exists as a
    configured field for when product-offtake revenue is tracked, but
    billing_worker.py will not multiply it against a number the platform
    doesn't have - see that file's updated docstring.

invoices gains:
    contract_id - which contract produced this invoice (nullable: old
    pre-contract invoices have none, and stay exactly as they were,
    never rewritten).
    line_items - the computed breakdown (base_fee, usage_fee,
    performance_adjustment, total), jsonb, so an invoice's PDF/UI can
    show its own math instead of a single opaque `amount`.
"""
from __future__ import annotations

from alembic import op

revision = "0008_contracts"
down_revision = "0007_tenant_onboarding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE contracts (
            contract_id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            plant_id                         text NOT NULL REFERENCES plants(plant_id) ON DELETE CASCADE,
            status                            text NOT NULL DEFAULT 'active'
                                                  CHECK (status IN ('draft', 'active', 'ended')),
            effective_from                    date NOT NULL,
            effective_to                      date,

            -- Fixed monthly charge, billed regardless of throughput.
            base_fee_inr                      numeric NOT NULL DEFAULT 0,

            -- Usage-based: INR per kg SO2 captured (replaces the old
            -- global SO2_RATE_PER_KG env var - now per-contract).
            usage_rate_inr_per_kg             numeric NOT NULL DEFAULT 0,

            -- Performance fee/penalty, gated on the period's uptime_pct
            -- (already computed by billing_worker.py from real sensor
            -- data availability - see that file's "flagged hour" logic).
            performance_bonus_threshold_pct   numeric,
            performance_bonus_inr             numeric NOT NULL DEFAULT 0,
            performance_penalty_threshold_pct numeric,
            performance_penalty_inr           numeric NOT NULL DEFAULT 0,

            -- Configured for future use once product-offtake revenue is
            -- tracked (see module docstring) - not multiplied against
            -- anything today.
            revenue_share_pct                 numeric NOT NULL DEFAULT 0,

            notes                             text,
            created_by                        uuid REFERENCES users(user_id),
            created_at                        timestamptz NOT NULL DEFAULT now(),

            CHECK (effective_to IS NULL OR effective_to >= effective_from)
        );
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX contracts_one_active_per_plant
        ON contracts (plant_id) WHERE status = 'active';
        """
    )
    op.execute("CREATE INDEX contracts_plant_idx ON contracts (plant_id);")

    op.execute("ALTER TABLE invoices ADD COLUMN contract_id uuid REFERENCES contracts(contract_id);")
    op.execute("ALTER TABLE invoices ADD COLUMN line_items jsonb NOT NULL DEFAULT '{}'::jsonb;")

    # contracts is plant-scoped like erp_* procurement tables, but reused
    # by the admin billing surface (global_admin/global_read), not the
    # client dashboard - no RLS, same documented decision as
    # users/company/audit_log (migrations/README.md).


def downgrade() -> None:
    op.execute("ALTER TABLE invoices DROP COLUMN IF EXISTS line_items;")
    op.execute("ALTER TABLE invoices DROP COLUMN IF EXISTS contract_id;")
    op.execute("DROP TABLE IF EXISTS contracts;")
