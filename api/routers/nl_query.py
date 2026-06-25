"""Natural-language → SQL query endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from api.deps import get_engine, get_config
from api.schemas import NLQueryRequest, NLQueryResult

router = APIRouter(prefix="/nl-query", tags=["nl-query"])


@router.post("", response_model=NLQueryResult)
def nl_query(
    body: NLQueryRequest,
    engine=Depends(get_engine),
    cfg: dict = Depends(get_config),
):
    """Convert a natural-language question to SQL and execute it locally."""
    from src.query.nl_query_engine import NLQueryEngine

    model = cfg.get("extraction", {}).get("llm_model", "qwen2.5:3b")
    ollama_url = cfg.get("llm", {}).get("base_url", "http://localhost:11434")

    try:
        nl_engine = NLQueryEngine(engine=engine, ollama_url=ollama_url, model=model)
        result = nl_engine.query(body.question)
    except Exception as e:
        return NLQueryResult(sql="", columns=[], rows=[], row_count=0, error=str(e))

    sql = result.get("sql") or ""
    rows_raw = result.get("result") or []
    error = None if sql else (result.get("answer") or result.get("explanation"))

    if rows_raw:
        columns = list(rows_raw[0].keys())
        rows = [[row.get(col) for col in columns] for row in rows_raw]
    else:
        columns = []
        rows = []

    return NLQueryResult(
        sql=sql,
        columns=columns,
        rows=rows,
        row_count=len(rows),
        error=error,
    )
