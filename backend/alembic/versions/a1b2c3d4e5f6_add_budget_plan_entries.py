"""add budget_plan_entries table

Revision ID: a1b2c3d4e5f6
Revises: 4facaa3e9138
Create Date: 2026-06-29

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '9f69d0021e84'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'budget_plan_entries',
        sa.Column('catalog_id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('year', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('label', sa.Text(), nullable=False),
        sa.Column('monthly', sa.JSON(), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True,
                  server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('budget_plan_entries')
