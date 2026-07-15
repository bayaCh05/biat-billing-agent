"""Natural-language → SQL query endpoint."""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends

from api.auth import require_role
from api.schemas import NLQueryRequest, NLQueryResult

router = APIRouter(prefix="/nl-query", tags=["analytics"])

_COMPTABLE_DIRECTION = Depends(require_role("Comptable", "Direction"))


@router.post(
    "",
    response_model=NLQueryResult,
    summary="Requête en langage naturel",
    description=(
        "Convertit une question en français en SQL et l'exécute localement sur la base de données. "
        "Le modèle Ollama (qwen2.5:3b) génère le SQL — aucune donnée n'est envoyée vers le cloud. "
        "Exemple : `Factures Ooredoo du mois de juin` → "
        "`SELECT COALESCE(SUM(amount_ttc), 0) FROM invoices WHERE issuer_name LIKE '%Ooredoo%'`."
    ),
    response_description="SQL généré, colonnes, lignes de résultat et éventuel message d'erreur",
)
def nl_query(
    body: NLQueryRequest,
    _: dict = _COMPTABLE_DIRECTION,
):
    from src.query.nl_query_engine import NLQueryEngine

    # Same env vars OllamaClient resolves against (ollama_client.py) — config/
    # settings.yaml has no `llm.base_url` key, so reading it here always fell
    # through to the hardcoded default regardless of OLLAMA_BASE_URL.
    model = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
    ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    try:
        nl_engine = NLQueryEngine(ollama_url=ollama_url, model=model)
        result = nl_engine.query(body.question)
    except Exception as e:
        return NLQueryResult(sql="", columns=[], rows=[], row_count=0, error=str(e))

    sql = result.get("sql") or ""
    rows_raw = result.get("result") or []
    answer = result.get("answer")
    explanation = result.get("explanation")
    error = None if sql else answer

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
        answer=answer,
        explanation=explanation,
        error=error,
    )
