"""Shared FastAPI dependencies — DB session, pipeline components."""
from __future__ import annotations

from functools import lru_cache
from typing import Generator

from sqlalchemy.orm import Session

from src.agent.config_loader import build_pipeline_components, load_config
from src.agent.pipeline import PipelineComponents
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


def get_components() -> PipelineComponents:
    """Build a fresh PipelineComponents (Ollama backend). Close after use."""
    components, _ = build_pipeline_components()
    return components
