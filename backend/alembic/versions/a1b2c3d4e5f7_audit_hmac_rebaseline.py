"""audit_logs: HMAC rebaseline columns (post-2026-07-10 secret rotation).

Adds rebaseline_hash / rebaselined_at / rebaseline_reason, purely additive
alongside the existing row_hash — row_hash is never overwritten by this
migration or by the rebaseline script that populates these new columns
(scripts/rebaseline_audit_hmac.py). See docs/audit_hmac_incident.md.

Revision ID: a1b2c3d4e5f7
Revises: 1a2b3c4d5e6f
Create Date: 2026-07-15
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f7"
down_revision: Union[str, Sequence[str], None] = "1a2b3c4d5e6f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_cols = {c["name"] for c in inspector.get_columns("audit_logs")}

    if "rebaseline_hash" not in existing_cols:
        op.add_column("audit_logs", sa.Column("rebaseline_hash", sa.String(64), nullable=True))
    if "rebaselined_at" not in existing_cols:
        op.add_column("audit_logs", sa.Column("rebaselined_at", sa.DateTime(timezone=True), nullable=True))
    if "rebaseline_reason" not in existing_cols:
        op.add_column("audit_logs", sa.Column("rebaseline_reason", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("audit_logs", "rebaseline_reason")
    op.drop_column("audit_logs", "rebaselined_at")
    op.drop_column("audit_logs", "rebaseline_hash")
