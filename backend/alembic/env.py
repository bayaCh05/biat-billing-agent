"""Alembic environment — BIAT IT Billing Agent.

DATABASE_URL is read from the environment variable so the same alembic.ini
works in dev (SQLite) and production (PostgreSQL) without any edits.

Commands:
    alembic upgrade head          # apply all pending migrations
    alembic downgrade -1          # roll back one step
    alembic history               # list revision history
    alembic current               # show DB's current revision
    alembic revision --autogenerate -m "description"  # new migration
"""
from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# ── Alembic config object (reads alembic.ini) ────────────────────────────────
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ── Override DB URL from environment so prod and dev use the same ini ─────────
_db_url = os.getenv("DATABASE_URL", "sqlite:///./data/invoices.db")
config.set_main_option("sqlalchemy.url", _db_url)

# ── Import all ORM models so Base.metadata is fully populated ────────────────
# Every table must be importable here; add new orm_models_*.py files below.
from src.storage.db import Base                       # noqa: E402 F401
import src.storage.orm_models                        # noqa: E402 F401
import src.storage.orm_models_audit                  # noqa: E402 F401

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Offline mode: emit SQL without a live DB connection.

    Useful for generating a SQL script to review before applying in production.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=url.startswith("sqlite"),
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Online mode: run migrations against a live DB connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=_db_url.startswith("sqlite"),
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
