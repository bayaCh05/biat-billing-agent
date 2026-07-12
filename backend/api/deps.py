"""Shared FastAPI dependencies — DB session, pipeline components."""
from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from typing import Generator

from sqlalchemy.orm import Session

from src.agent.config_loader import AIComponents, build_ai_components, load_config
from src.storage.db import build_engine, build_session_factory, init_db
from src.cost_catalog.catalog import CostCatalog
from src.budget.budget_tracker import BudgetPlan


@lru_cache(maxsize=1)
def _shared_resources():
    cfg = load_config()
    engine = build_engine(cfg["storage"]["db_url"])
    init_db(engine)
    sf = build_session_factory(engine)
    catalog = CostCatalog.from_yaml(cfg["classification"]["cost_catalog_file"])
    plan = BudgetPlan.from_yaml("config/budget_plan.yaml")
    return engine, sf, cfg, catalog, plan


def get_session() -> Generator[Session, None, None]:
    _, sf, _, _, _ = _shared_resources()
    session = sf()
    try:
        yield session
    finally:
        session.close()


def get_catalog() -> CostCatalog:
    _, _, _, catalog, _ = _shared_resources()
    return catalog


def get_budget_plan() -> BudgetPlan:
    _, _, _, _, plan = _shared_resources()
    return plan


def get_config() -> dict:
    _, _, cfg, _, _ = _shared_resources()
    return cfg


def get_engine():
    engine, _, _, _, _ = _shared_resources()
    return engine


def get_components() -> AIComponents:
    """Build a fresh AIComponents (Ollama backend) for AIOrchestrator. Close after use."""
    return build_ai_components()


@contextmanager
def get_session_ctx():
    """Context-manager session for use in scheduler jobs (not FastAPI DI)."""
    _, sf, _, _, _ = _shared_resources()
    session = sf()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
