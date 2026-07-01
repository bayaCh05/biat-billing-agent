"""Add risques table for risk management.

Revision ID: c3d4e5f6a1b2
Revises: b2c3d4e5f6a1
Create Date: 2026-06-30

"""
from __future__ import annotations

from typing import Sequence, Union
import sqlalchemy as sa
from sqlalchemy.dialects import sqlite
from alembic import op

revision: str = 'c3d4e5f6a1b2'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'risques',
        sa.Column('id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column('titre', sa.Text(), nullable=False),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('type_risque', sa.String(32), nullable=False, server_default='AUTRE'),
        sa.Column('probabilite', sa.String(16), nullable=False),
        sa.Column('impact', sa.String(16), nullable=False),
        sa.Column('niveau_criticite', sa.String(16), nullable=False),
        sa.Column('statut', sa.String(24), nullable=False, server_default='IDENTIFIE'),
        sa.Column('plan_mitigation', sa.Text(), nullable=False, server_default=''),
        sa.Column('responsable_id', sa.String(64), nullable=True),
        sa.Column('date_identification', sa.Date(), nullable=False),
        sa.Column('date_echeance_mitigation', sa.Date(), nullable=True),
        sa.Column('date_cloture', sa.Date(), nullable=True),
        sa.Column('feuille_route_id', sa.Uuid(as_uuid=True), sa.ForeignKey('feuilles_de_route.id', ondelete='CASCADE'), nullable=True),
        sa.Column('projet_id', sa.String(64), nullable=True),
        sa.Column('created_by', sa.String(64), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_risques_feuille_route_id', 'risques', ['feuille_route_id'])
    op.create_index('ix_risques_projet_id', 'risques', ['projet_id'])


def downgrade() -> None:
    op.drop_index('ix_risques_projet_id', table_name='risques')
    op.drop_index('ix_risques_feuille_route_id', table_name='risques')
    op.drop_table('risques')
