from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import NullPool, StaticPool


class Base(DeclarativeBase):
    pass


def build_engine(db_url: str):
    connect_args = {"check_same_thread": False} if db_url.startswith("sqlite") else {}
    if ":memory:" in db_url:
        # StaticPool reuses a single connection for all sessions — required for
        # in-memory SQLite so every session sees the same database (used in tests).
        pool_kwargs: dict = {"poolclass": StaticPool}
    elif db_url.startswith("sqlite"):
        # NullPool for file-based SQLite: each Session opens/closes its own
        # connection, preventing QueuePool exhaustion on Streamlit page re-renders.
        pool_kwargs = {"poolclass": NullPool}
    else:
        pool_kwargs = {}
    engine = create_engine(db_url, connect_args=connect_args, echo=False, **pool_kwargs)
    if db_url.startswith("sqlite"):
        # Enable WAL mode and foreign key enforcement for SQLite
        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(connection, _):
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA foreign_keys=ON")
    return engine


def build_session_factory(engine):
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def init_db(engine) -> None:
    """Create all tables. In production, use Alembic migrations instead."""
    import src.storage.orm_models               # noqa: F401
    import src.accounting.journal_store         # noqa: F401  registers journal tables
    import src.billing.client_invoice_store     # noqa: F401  registers billing tables
    import src.capex.asset_repository           # noqa: F401  registers assets table
    import src.storage.orm_models_projects      # noqa: F401  registers project tables
    import src.storage.orm_models_users         # noqa: F401  registers users table
    import src.storage.orm_models_extra         # noqa: F401  registers budget/roadmap/livrables tables
    Base.metadata.create_all(engine)
