"""Document management: generic file attachment to any entity.

Closes the enterprise spec's Module "Document management" requirement -
"every document should attach to relevant objects: Site, Skid, Component,
Project, Contract, Batch, Invoice, Compliance record" - as one reusable
system rather than a bespoke file_url/sha256 column pair bolted onto each
table that needs one (the pattern erp_drawings/quotations/POs already use
individually, and which doesn't generalize to a plant, a contract, or a
vendor certification with nowhere obvious to put a column).

documents
    Polymorphic attachment via (entity_type, entity_id) rather than a
    dozen nullable FK columns - the standard trade-off for "attaches to
    anything": entity_type is CHECK-constrained to a known vocabulary (so
    a typo can't silently create an unqueryable orphan category), but
    entity_id is NOT a foreign key (it can't be - it points at a
    different table depending on entity_type) and its existence is
    validated at the API layer per entity_type, not by the database.

    Reuses api/erp_storage.py's upload_bytes (write-then-verify: PUT,
    then re-download and re-hash before trusting the write - the same
    pattern every other file upload in this codebase already follows)
    rather than inventing a second storage path. The bucket is private
    (see AUDIT.md 2.1 / SHIPPING.md's billing-engine entry for the first
    fix of this) - GET /admin/documents returns presigned URLs, never the
    stored object_key directly.
"""
from __future__ import annotations

from alembic import op

revision = "0009_documents"
down_revision = "0008_contracts"
branch_labels = None
depends_on = None

# Deliberately a fixed, reviewed vocabulary - not "any string the caller
# sends". New entity types get added here (a one-line migration) as
# document attachment is wired into more of the app, so the CHECK
# constraint always reflects what the API layer actually validates
# entity_id against (see api/routers/admin_documents.py's _EXISTENCE_CHECK).
_ENTITY_TYPES = (
    "plant", "contract", "vendor", "purchase_order", "bom",
    "invoice", "fabrication_job", "unit_serial", "user", "company",
)


def upgrade() -> None:
    types_sql = ", ".join(f"'{t}'" for t in _ENTITY_TYPES)
    op.execute(
        f"""
        CREATE TABLE documents (
            document_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            entity_type   text NOT NULL CHECK (entity_type IN ({types_sql})),
            entity_id     text NOT NULL,
            filename      text NOT NULL,
            content_type  text NOT NULL,
            object_key    text NOT NULL UNIQUE,
            sha256        text NOT NULL,
            bytes         bigint NOT NULL,
            notes         text,
            uploaded_by   uuid REFERENCES users(user_id),
            uploaded_at   timestamptz NOT NULL DEFAULT now()
        );
        """
    )
    op.execute("CREATE INDEX documents_entity_idx ON documents (entity_type, entity_id);")

    # No RLS: this is an admin-surface capability (global_admin/global_read
    # only, same as audit_log/contracts) even though several entity_types
    # it attaches to (plant, invoice) are themselves plant-scoped data.
    # Tenant-scoped visibility (a plant operator seeing documents attached
    # to their own plant) is a real follow-up, not built in this pass -
    # see SHIPPING.md.


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS documents;")
