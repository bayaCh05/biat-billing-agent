"""Natural-language → SQL query endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text

from api.deps import get_session, get_config
from api.schemas import NLQueryRequest, NLQueryResult

router = APIRouter(prefix="/nl-query", tags=["nl-query"])


@router.post("", response_model=NLQueryResult)
def nl_query(
    body: NLQueryRequest,
    session: Session = Depends(get_session),
    cfg: dict = Depends(get_config),
):
    """Convert a natural-language question to SQL and execute it locally."""
    from src.query.nl_query_engine import NLQueryEngine

    engine_cfg = cfg.get("extraction", {})
    model = engine_cfg.get("llm_model", "qwen2.5:3b")
    base_url = cfg.get("llm", {}).get("base_url", "http://localhost:11434")

    try:
        engine = NLQueryEngine(model=model, base_url=base_url)
        sql = engine.to_sql(body.question)
    except Exception as e:
        return NLQueryResult(sql="", columns=[], rows=[], row_count=0, error=str(e))

    try:
        result = session.execute(text(sql))
        columns = list(result.keys())
        rows = [list(row) for row in result.fetchall()]
        return NLQueryResult(
            sql=sql,
            columns=columns,
            rows=rows,
            row_count=len(rows),
        )
    except Exception as e:
        return NLQueryResult(sql=sql, columns=[], rows=[], row_count=0, error=str(e))
