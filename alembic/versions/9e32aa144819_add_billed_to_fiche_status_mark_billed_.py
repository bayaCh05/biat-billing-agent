"""add BILLED to fiche status + mark_billed method

Revision ID: 9e32aa144819
Revises: 0b6a99bbc611
Create Date: 2026-06-12 10:19:14.452594

Notes:
  SQLite does not enforce CHECK constraints at the column level after
  ALTER TABLE, so there is no DDL change for the status column itself.
  This migration sanitises any invalid status values and is the audit
  record that 'billed' is now an official state.

  For PostgreSQL, you would add:
    op.execute("ALTER TABLE fiches_mensuelles
                DROP CONSTRAINT IF EXISTS ck_fiche_status")
    op.execute("ALTER TABLE fiches_mensuelles
                ADD CONSTRAINT ck_fiche_status
                CHECK (status IN ('draft','submitted','billed'))")
"""
from typing import Sequence, Union

from alembic import op


revision: str = '9e32aa144819'
down_revision: Union[str, Sequence[str], None] = '0b6a99bbc611'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Sanitise any rows that may have an unrecognised status value.
    # Valid states are: draft | submitted | billed
    op.execute(
        "UPDATE fiches_mensuelles "
        "SET status = 'submitted' "
        "WHERE status NOT IN ('draft', 'submitted', 'billed')"
    )


def downgrade() -> None:
    # Roll back: 'billed' rows revert to 'submitted'
    op.execute(
        "UPDATE fiches_mensuelles "
        "SET status = 'submitted' "
        "WHERE status = 'billed'"
    )
