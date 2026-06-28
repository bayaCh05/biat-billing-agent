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
    """Register all ORM models with Base.metadata.

    For **in-memory SQLite** (tests): creates all tables via create_all() so
    that unit/integration tests can run without Alembic.

    For **file-based / production** databases: schema must be applied with
        alembic upgrade head
    create_all() is intentionally NOT called for production databases to
    prevent silent schema drift — Alembic is the single source of truth.
    """
    import src.storage.orm_models               # noqa: F401
    import src.accounting.journal_store         # noqa: F401
    import src.billing.client_invoice_store     # noqa: F401
    import src.capex.asset_repository           # noqa: F401
    import src.storage.orm_models_projects      # noqa: F401
    import src.storage.orm_models_users         # noqa: F401
    import src.storage.orm_models_extra         # noqa: F401
    import src.storage.orm_models_notifications # noqa: F401
    import src.storage.orm_models_audit         # noqa: F401

    db_url = str(engine.url)
    if ":memory:" in db_url:
        # Tests only: create_all() on in-memory SQLite avoids Alembic overhead.
        # Alembic migrations do not support in-memory connections.
        Base.metadata.create_all(engine)
    # File-based and remote DBs: schema is managed by Alembic migrations only.
