"""Document Beanie pour les rapports d'audit périodiques (Audit Agent transversal).

Un document = un (granularity, period_start) donné, produit par
src/ai_agents/audit_agent.py::AuditAgent. Immuable une fois créé : `trend`
est calculé et persisté à la génération à partir du snapshot précédent de
même granularité, jamais recalculé à la lecture — c'est ce qui rend la
dérive dans le temps auditable (on compare deux états figés, pas deux
recalculs à des instants différents sur les mêmes données live).

Lot 1 (2026-07) : metrics + trend + alerts, tous 100% déterministes.
`reconciliation` (rapprochement transversal facture↔échéancier↔budget↔
journal), `similar_incidents` (RAG) et `narrative_summary` (LLM) sont des
champs réservés pour les Lots 2/3 — vides par défaut ici.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import UUID, uuid4

from beanie import Document, Indexed
from pydantic import BaseModel, Field
from pymongo import ASCENDING, DESCENDING, IndexModel


class AuditAlert(BaseModel):
    """Alerte déterministe levée par AuditAgent._evaluate_alerts() — jamais générée par un LLM."""
    domain: str
    severity: str   # "CRITICAL" | "WARNING" | "INFO"
    code: str
    message: str


class AuditSnapshotDocument(Document):
    """Snapshot périodique d'audit transversal.

    Correspond à aucune table SQLAlchemy — domaine né Mongo-natif (pas de
    migration à faire, contrairement au reste du projet).
    """

    id: UUID = Field(default_factory=uuid4)
    granularity: Annotated[str, Indexed()]           # "DAILY" | "WEEKLY" | "MONTHLY"
    period_start: Annotated[datetime, Indexed()]
    period_end: datetime
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "OK"                               # "OK" | "DEGRADED"

    metrics: dict[str, Any] = Field(default_factory=dict)
    trend: dict[str, Any] = Field(default_factory=dict)
    alerts: list[AuditAlert] = Field(default_factory=list)

    # Réservés Lots 2/3 — vides en Lot 1
    reconciliation: dict[str, Any] = Field(default_factory=dict)
    similar_incidents: list[dict[str, Any]] = Field(default_factory=list)
    narrative_summary: str | None = None

    class Settings:
        name = "audit_snapshots"
        indexes = [
            IndexModel([("granularity", ASCENDING), ("period_start", DESCENDING)]),
        ]
