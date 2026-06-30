"""Drop BCT export compliance columns from client_invoices.

Revision ID: b2c3d4e5f6a1
Revises: a1b2c3d4e5f6
Create Date: 2026-06-30

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'b2c3d4e5f6a1'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('client_invoices', schema=None) as batch_op:
        batch_op.drop_column('exchange_rate')
        batch_op.drop_column('foreign_currency_amount')
        batch_op.drop_column('payment_guarantee_type')
        batch_op.drop_column('repatriation_date')
        batch_op.drop_column('repatriation_deadline')
        batch_op.drop_column('shipment_date')
        batch_op.drop_column('domiciliation_number')
        batch_op.drop_column('domiciliation_bank')
        batch_op.drop_column('is_export')
        batch_op.drop_column('currency')


def downgrade() -> None:
    with op.batch_alter_table('client_invoices', schema=None) as batch_op:
        batch_op.add_column(sa.Column('currency', sa.String(length=8), nullable=False, server_default='TND'))
        batch_op.add_column(sa.Column('is_export', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('domiciliation_bank', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('domiciliation_number', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('shipment_date', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('repatriation_deadline', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('repatriation_date', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('payment_guarantee_type', sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column('foreign_currency_amount', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('exchange_rate', sa.Float(), nullable=True))
