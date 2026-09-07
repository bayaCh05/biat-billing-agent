"""audit_logs: 2nd-generation HMAC rebaseline columns (2026-09-07, Option B).

Setting a real AUDIT_HMAC_SECRET (docs/audit_hmac_incident.md section 8)
constitutes a second secret rotation on top of the 2026-07-10 one already
covered by rebaseline_hash/rebaselined_at/rebaseline_reason (migration
a1b2c3d4e5f7, 2026-07-15). Re-rebaselining under the new secret would
overwrite those 3 columns for the 569 rows already rebaselined once,
destroying the on-record proof of the first rebaseline event — exactly
the kind of silent loss this whole mechanism exists to avoid (see section 4).

Adds prior_rebaseline_hash / prior_rebaselined_at / prior_rebaseline_reason,
purely additive. scripts/rebaseline_audit_hmac.py copies the current
rebaseline_hash/rebaselined_at/rebaseline_reason into these 3 columns
(only if not already set) before overwriting them with the generation-2
values — row_hash itself is still never touched, as always.

Revision ID: b3c4d5e6f7a8
Revises: a1b2c3d4e5f7
Create Date: 2026-09-07
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b3c4d5e6f7a8"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_cols = {c["name"] for c in inspector.get_columns("audit_logs")}

    if "prior_rebaseline_hash" not in existing_cols:
        op.add_column("audit_logs", sa.Column("prior_rebaseline_hash", sa.String(64), nullable=True))
    if "prior_rebaselined_at" not in existing_cols:
        op.add_column("audit_logs", sa.Column("prior_rebaselined_at", sa.DateTime(timezone=True), nullable=True))
    if "prior_rebaseline_reason" not in existing_cols:
        op.add_column("audit_logs", sa.Column("prior_rebaseline_reason", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("audit_logs", "prior_rebaseline_reason")
    op.drop_column("audit_logs", "prior_rebaselined_at")
    op.drop_column("audit_logs", "prior_rebaseline_hash")
