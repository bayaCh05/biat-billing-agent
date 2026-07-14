"""Backfill ponctuel — indexe TOUT l'historique des risques et anomalies
existants dans la collection ChromaDB `audit_incidents` (RAG narratif de
l'Audit Agent, voir backend/src/ai_agents/audit_agent.py).

Pourquoi un script séparé et pas le job périodique lui-même :
AuditAgent._index_new_incidents() n'indexe que l'incrément depuis le dernier
snapshot (coût constant, petit, à chaque run). Sur un premier déploiement,
l'historique complet peut représenter un volume bien plus important —
l'indexer en plein milieu d'un run planifié (audit_daily, 2h du matin)
ferait varier sa durée de façon imprévisible. Ce script s'exécute une fois,
manuellement, hors du cycle planifié.

Idempotent — index_incident() fait un upsert par (source_type, source_id),
relancer ce script ne duplique rien.

Usage:
    python scripts/backfill_audit_incidents.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).parent.parent))

# api.auth charge .env (MONGODB_URI/CHROMADB_PATH inclus) — même convention
# que les scripts seed_*.py.
import api.auth  # noqa: F401
from src.ai_agents.rag.pce_vectorstore import PCEVectorStore
from src.storage.sync_mongo_repository import (
    invoice_flags_created_since_sync, risques_created_since_sync,
)


def main() -> None:
    store = PCEVectorStore.get()
    if not store.available:
        print("✗ ChromaDB indisponible — backfill impossible (voir logs).")
        return

    n_risques = 0
    for r in risques_created_since_sync(None):
        store.index_incident(
            "risque", r["_id"],
            f"{r.get('titre', '')} {r.get('description', '')}".strip(),
            {"date": str(r.get("created_at", "")), "severity": r.get("niveau_criticite", "")},
        )
        n_risques += 1

    n_anomalies = 0
    for f in invoice_flags_created_since_sync(None):
        store.index_incident(
            "anomaly", f.get("flag_id") or f"{f['invoice_id']}:{f.get('flag_type', '')}",
            f"{f.get('flag_type', '')} {f.get('message', '')}".strip(),
            {"date": str(f.get("created_at", "")), "severity": f.get("severity", "")},
        )
        n_anomalies += 1

    print(f"✓ Backfill terminé : {n_risques} risque(s) + {n_anomalies} anomalie(s) indexé(s).")


if __name__ == "__main__":
    main()
