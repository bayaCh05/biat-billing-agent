"""add_missing_performance_indexes

Revision ID: 4facaa3e9138
Revises: 8b8980897ba0
Create Date: 2026-06-28 17:58:39.820599

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4facaa3e9138'
down_revision: Union[str, Sequence[str], None] = '8b8980897ba0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add missing performance indexes identified during DB audit (2026-06-28)."""
    with op.batch_alter_table('invoices', schema=None) as batch_op:
        batch_op.create_index('idx_invoices_received_at', ['received_at'], unique=False)

    with op.batch_alter_table('audit_logs', schema=None) as batch_op:
        batch_op.create_index('idx_audit_logs_created_at', ['created_at'], unique=False)
        batch_op.create_index('idx_audit_logs_actor', ['actor'], unique=False)


def downgrade() -> None:
    """Remove the performance indexes added in this revision."""
    with op.batch_alter_table('audit_logs', schema=None) as batch_op:
        batch_op.drop_index('idx_audit_logs_actor')
        batch_op.drop_index('idx_audit_logs_created_at')

    with op.batch_alter_table('invoices', schema=None) as batch_op:
        batch_op.drop_index('idx_invoices_received_at')
