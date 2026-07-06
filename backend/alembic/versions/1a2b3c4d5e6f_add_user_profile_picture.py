"""add user profile_picture column

Revision ID: 1a2b3c4d5e6f
Revises: f1a2b3c4d5e6
Create Date: 2026-07-05
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = '1a2b3c4d5e6f'
down_revision: str = 'f1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('profile_picture', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'profile_picture')
