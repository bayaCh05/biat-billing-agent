"""Requêtes en langage naturel — text-to-SQL interface."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app._backend import get_db_engine, require_auth
from src.query.nl_query_engine import NLQueryEngine

require_auth()

OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

st.title("💬 Requêtes en langage naturel")
st.caption(
    "Interrogez la base de données en français. "
    "Toutes les réponses sont calculées en temps réel depuis vos données. "
    "Aucune donnée ne quitte le serveur local."
)

# ── Example questions ──────────────────────────────────────────────────────

EXAMPLES = [
    "Combien avons-nous dépensé en télécommunications cette année?",
    "Quel fournisseur nous a le plus facturé cette année?",
    "Combien de factures sont actuellement en attente de validation?",
    "Quelle est la VNC totale de nos immobilisations?",
    "Combien de factures sont en retard de paiement?",
    "Quel est notre solde TVA déductible en 2026?",
    "Combien avons-nous facturé à BIAT cette année?",
    "Quelle est la répartition des dépenses par catégorie?",
]

st.markdown("**Exemples de questions :**")


def _pick_example(ex: str) -> None:
    st.session_state["_nl_preset"] = ex


cols = st.columns(2)
for i, ex in enumerate(EXAMPLES):
    cols[i % 2].button(
        ex, key=f"ex_{i}",
        on_click=_pick_example, args=(ex,),
        use_container_width=True,
    )

st.divider()

# ── Question input ─────────────────────────────────────────────────────────

preset   = st.session_state.pop("_nl_preset", "")
question = st.text_input(
    "Votre question",
    value=preset,
    placeholder="Ex: Combien avons-nous dépensé en formation cette année?",
)

submitted = st.button("▶ Interroger", type="primary")

# ── Run query ──────────────────────────────────────────────────────────────

result: dict | None = None

if submitted and question.strip():
    with st.spinner("Génération SQL et exécution en cours…"):
        try:
            engine  = get_db_engine()
            nl      = NLQueryEngine(engine, ollama_url=OLLAMA_URL)
            result  = nl.query(question.strip())
        except Exception as exc:
            st.error(f"Erreur inattendue : {exc}")

    if result:
        st.session_state.setdefault("nl_history", []).insert(0, {
            "q": question.strip(),
            "a": result["answer"],
            "sql": result.get("sql"),
        })
        # Keep last 10 in history
        st.session_state["nl_history"] = st.session_state["nl_history"][:10]

# ── Display result ─────────────────────────────────────────────────────────

if result:
    st.markdown("### Réponse")
    st.markdown(result["answer"])

    if result.get("sql"):
        with st.expander("Requête SQL générée", expanded=False):
            st.code(result["sql"], language="sql")

    raw_rows = result.get("result") or []
    if len(raw_rows) > 1:
        with st.expander(f"Données brutes ({len(raw_rows)} lignes)", expanded=False):
            st.dataframe(pd.DataFrame(raw_rows), width="stretch", hide_index=True)

# ── Session history ────────────────────────────────────────────────────────

history = st.session_state.get("nl_history", [])
if history:
    st.divider()
    st.markdown("**Historique de cette session**")
    for item in history:
        with st.container():
            st.markdown(f"**Q :** {item['q']}")
            st.markdown(f"**R :** {item['a']}")
            if item.get("sql"):
                with st.expander("SQL", expanded=False):
                    st.code(item["sql"], language="sql")
            st.divider()
