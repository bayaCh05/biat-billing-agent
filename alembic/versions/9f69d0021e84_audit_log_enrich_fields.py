"""audit_log_enrich_fields

Revision ID: 9f69d0021e84
Revises: 4facaa3e9138
Create Date: 2026-06-28 18:16:15.168401

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9f69d0021e84'
down_revision: Union[str, Sequence[str], None] = '4facaa3e9138'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add banking-compliance fields to audit_logs (BCT Circulaire 2025-13)."""
    with op.batch_alter_table('audit_logs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('user_id',       sa.String(length=64),  nullable=True))
        batch_op.add_column(sa.Column('user_email',    sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column('user_role',     sa.String(length=32),  nullable=True))
        batch_op.add_column(sa.Column('resource_type', sa.String(length=64),  nullable=True))
        batch_op.add_column(sa.Column('resource_id',   sa.String(length=64),  nullable=True))
        batch_op.add_column(sa.Column('before_value',  sa.JSON(),             nullable=True))
        batch_op.add_column(sa.Column('after_value',   sa.JSON(),             nullable=True))
        batch_op.add_column(sa.Column('ip_address',    sa.String(length=64),  nullable=True))
        batch_op.add_column(sa.Column('user_agent',    sa.String(length=256), nullable=True))
        batch_op.add_column(sa.Column('status',        sa.String(length=16),  nullable=False,
                                      server_default='SUCCESS'))
        batch_op.create_index('idx_audit_logs_resource_type', ['resource_type'], unique=False)
        batch_op.create_index('idx_audit_logs_resource_id',   ['resource_id'],   unique=False)
        batch_op.create_index('idx_audit_logs_user_id',       ['user_id'],       unique=False)


def downgrade() -> None:
    """Remove enriched audit fields."""
    with op.batch_alter_table('audit_logs', schema=None) as batch_op:
        batch_op.drop_index('idx_audit_logs_user_id')
        batch_op.drop_index('idx_audit_logs_resource_id')
        batch_op.drop_index('idx_audit_logs_resource_type')
        batch_op.drop_column('status')
        batch_op.drop_column('user_agent')
        batch_op.drop_column('ip_address')
        batch_op.drop_column('after_value')
        batch_op.drop_column('before_value')
        batch_op.drop_column('resource_id')
        batch_op.drop_column('resource_type')
        batch_op.drop_column('user_role')
        batch_op.drop_column('user_email')
        batch_op.drop_column('user_id')
