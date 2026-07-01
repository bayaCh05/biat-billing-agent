"""Add AI layer columns: invoice AI fields, journal explanation, asset amortization source.

Revision ID: e5f6a1b2c3d4
Revises: d4e5f6a1b2c3
Create Date: 2026-07-01

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'e5f6a1b2c3d4'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a1b2c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # invoices: AI classification metadata
    with op.batch_alter_table('invoices') as batch_op:
        batch_op.add_column(sa.Column('payment_term_days', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('classification_reason', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('classification_pass', sa.String(32), nullable=True))

    # journal_entries: LLM accounting explanation
    with op.batch_alter_table('journal_entries') as batch_op:
        batch_op.add_column(sa.Column('accounting_explanation', sa.Text(), nullable=True))

    # assets: amortization source tracking
    with op.batch_alter_table('assets') as batch_op:
        batch_op.add_column(sa.Column('amortization_source', sa.String(16), nullable=True))
        # supplier_invoice_id was UUID; change to Text to accept string invoice IDs
        batch_op.alter_column('supplier_invoice_id',
                               existing_type=sa.Uuid(as_uuid=True),
                               type_=sa.Text(),
                               existing_nullable=True)

    # payment_installments and classification_feedback already exist via
    # the previous migration (d4e5f6a1b2c3). Create them only if missing.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = inspector.get_table_names()

    if 'payment_installments' not in existing:
        op.create_table(
            'payment_installments',
            sa.Column('id', sa.Uuid(as_uuid=True), nullable=False),
            sa.Column('invoice_id', sa.Text(), nullable=False),
            sa.Column('installment_number', sa.Integer(), nullable=False),
            sa.Column('total_installments', sa.Integer(), nullable=False),
            sa.Column('base_amount', sa.Float(), nullable=False),
            sa.Column('current_amount', sa.Float(), nullable=False),
            sa.Column('due_date', sa.Date(), nullable=False),
            sa.Column('paid_date', sa.Date(), nullable=True),
            sa.Column('paid_amount', sa.Float(), nullable=True),
            sa.Column('status', sa.String(16), nullable=False, server_default='PENDING'),
            sa.Column('late_periods', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.func.now()),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('idx_installments_invoice', 'payment_installments', ['invoice_id'])
        op.create_index('idx_installments_status', 'payment_installments', ['status'])
        op.create_index('idx_installments_due_date', 'payment_installments', ['due_date'])

    if 'classification_feedback' not in existing:
        op.create_table(
            'classification_feedback',
            sa.Column('id', sa.Uuid(as_uuid=True), nullable=False),
            sa.Column('invoice_id', sa.Text(), nullable=False),
            sa.Column('original_compte', sa.String(16), nullable=False),
            sa.Column('corrected_compte', sa.String(16), nullable=False),
            sa.Column('original_catalog_id', sa.Text(), nullable=True),
            sa.Column('corrected_catalog_id', sa.Text(), nullable=True),
            sa.Column('invoice_text', sa.Text(), nullable=False, server_default=''),
            sa.Column('corrected_by', sa.String(128), nullable=False, server_default=''),
            sa.Column('corrected_at', sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.func.now()),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('idx_feedback_invoice', 'classification_feedback', ['invoice_id'])


def downgrade() -> None:
    with op.batch_alter_table('assets') as batch_op:
        batch_op.drop_column('amortization_source')
        batch_op.alter_column('supplier_invoice_id',
                               existing_type=sa.Text(),
                               type_=sa.Uuid(as_uuid=True),
                               existing_nullable=True)

    with op.batch_alter_table('journal_entries') as batch_op:
        batch_op.drop_column('accounting_explanation')

    with op.batch_alter_table('invoices') as batch_op:
        batch_op.drop_column('classification_pass')
        batch_op.drop_column('classification_reason')
        batch_op.drop_column('payment_term_days')
