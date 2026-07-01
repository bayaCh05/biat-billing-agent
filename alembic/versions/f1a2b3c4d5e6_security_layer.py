"""Security layer: revoked_tokens, active_tokens, user lockout columns, audit row_hash.

Revision ID: f1a2b3c4d5e6
Revises: e5f6a1b2c3d4
Create Date: 2026-07-01
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "e5f6a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # ── revoked_tokens ────────────────────────────────────────────────────────
    inspector = sa.inspect(conn)
    if "revoked_tokens" not in inspector.get_table_names():
        op.create_table(
            "revoked_tokens",
            sa.Column("jti", sa.String(64), primary_key=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("reason", sa.String(32), nullable=False, server_default="logout"),
            sa.Column("user_id", sa.String(64), nullable=True),
        )
        op.create_index("idx_revoked_tokens_user_id", "revoked_tokens", ["user_id"])

    # ── active_tokens ─────────────────────────────────────────────────────────
    if "active_tokens" not in inspector.get_table_names():
        op.create_table(
            "active_tokens",
            sa.Column("jti", sa.String(64), primary_key=True),
            sa.Column("user_id", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("ip_address", sa.String(64), nullable=True),
            sa.Column("user_agent", sa.String(100), nullable=True),
            sa.Column("revoked", sa.Boolean(), nullable=False, server_default="0"),
        )
        op.create_index("idx_active_tokens_user_id", "active_tokens", ["user_id"])

    # ── users: lockout columns ─────────────────────────────────────────────────
    existing_user_cols = {c["name"] for c in inspector.get_columns("users")}

    for col_name, col_def in [
        ("failed_login_attempts", sa.Column("failed_login_attempts", sa.Integer(), nullable=False, server_default="0")),
        ("locked_until", sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True)),
        ("last_failed_login", sa.Column("last_failed_login", sa.DateTime(timezone=True), nullable=True)),
        ("last_login_at", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True)),
        ("last_login_ip", sa.Column("last_login_ip", sa.String(64), nullable=True)),
    ]:
        if col_name not in existing_user_cols:
            op.add_column("users", col_def)

    # ── audit_logs: row_hash ───────────────────────────────────────────────────
    existing_audit_cols = {c["name"] for c in inspector.get_columns("audit_logs")}
    if "row_hash" not in existing_audit_cols:
        op.add_column("audit_logs", sa.Column("row_hash", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("audit_logs", "row_hash")

    for col in ["last_login_ip", "last_login_at", "last_failed_login", "locked_until", "failed_login_attempts"]:
        try:
            op.drop_column("users", col)
        except Exception:
            pass

    try:
        op.drop_index("idx_active_tokens_user_id", table_name="active_tokens")
        op.drop_table("active_tokens")
    except Exception:
        pass

    try:
        op.drop_index("idx_revoked_tokens_user_id", table_name="revoked_tokens")
        op.drop_table("revoked_tokens")
    except Exception:
        pass
