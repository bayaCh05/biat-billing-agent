"""Agent 5 — risk management.

Capability A: Nightly roadmap scan → creates AI-suggested risks for overdue items.
Capability B: On-demand mitigation plan drafting.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import date

from src.ai_agents.base_agent import BaseAgent
from src.ai_agents.agent_schemas import AgentResult
from src.ai_agents.ollama_client import OllamaClient

logger = logging.getLogger(__name__)

_VALID_TYPE_RISQUE = {"DELAI", "BUDGET", "TECHNIQUE", "RESSOURCE", "AUTRE"}
_VALID_PROBABILITE = {"FAIBLE", "MOYENNE", "ELEVEE"}
_VALID_IMPACT = {"FAIBLE", "MOYEN", "ELEVE", "CRITIQUE"}


def _validated_enum(value: str | None, allowed: set[str], default: str) -> str:
    """Valide une valeur LLM contre un ensemble autorisé — retourne default si invalide."""
    if value and value.strip().upper() in allowed:
        return value.strip().upper()
    if value:
        logger.warning("risk_enum_invalid value=%r allowed=%s → fallback=%s", value, allowed, default)
    return default


class RiskAgent(BaseAgent):
    name = "RiskAgent"

    def run(self, context: dict) -> AgentResult:
        """Dispatch: context["task"] = "scan_roadmap" | "draft_mitigation" """
        task = context.get("task", "scan_roadmap")
        if task == "draft_mitigation":
            return self._draft_mitigation(context)
        return self._scan_roadmap(context)

    # ── Capability A — nightly roadmap scan ───────────────────────────────────

    def _scan_roadmap(self, context: dict) -> AgentResult:
        """Sync entry point — bridges to Mongo via asyncio.run().

        Callers (scheduler.py's nightly job, the two /ai/scan-*-risk(s)
        routes, which are plain `def` and so also run outside any event
        loop) are all synchronous; real roadmap/risk data lives in Mongo
        (service_bridge.py's create_risk_native() etc.), so this bridges
        once here rather than needing async up the whole call chain.
        """
        def _do() -> dict:
            output = asyncio.run(self._scan_roadmap_async(context.get("item_id")))
            logger.info(
                "risk_scan_complete created=%d skipped=%d",
                output["risks_created"], output["items_skipped"],
            )
            return dict(output=output)

        return self._run_safely(_do)

    async def _scan_roadmap_async(self, item_id_filter: str | None) -> dict:
        from types import SimpleNamespace
        from uuid import UUID as _UUID

        from src.storage.documents.feuille_de_route import FeuilleDeRouteDocument
        from src.storage.documents.risque import RisqueDocument
        from src.storage.documents.service_bridge import _to_midnight_utc, create_risk_native

        today = date.today()

        # Overdue roadmap items (optionally filtered to a single item)
        query: dict = {
            "date_fin": {"$lt": _to_midnight_utc(today)},
            "statut": {"$nin": ["TERMINE", "ANNULE"]},
        }
        if item_id_filter:
            query["_id"] = str(_UUID(item_id_filter))
        overdue = await FeuilleDeRouteDocument.find(query).to_list()

        created, skipped = 0, 0

        for item in overdue:
            # Skip if an AI-suggested risk already exists and is still IDENTIFIE.
            # Dict-filtered query (not a typed Document.field == value) — feuille_route_id
            # is declared UUID in the Pydantic schema but stored as a string, per convention.
            existing = await RisqueDocument.find_one({
                "feuille_route_id": str(item.id),
                "created_by": "system:ai",
                "statut": "IDENTIFIE",
            })
            if existing:
                skipped += 1
                continue

            days_overdue = (today - item.date_fin).days
            risk_data = self._generate_risk_for_overdue(item, days_overdue)
            if not risk_data:
                skipped += 1
                continue

            type_risque = _validated_enum(risk_data.get("type_risque"), _VALID_TYPE_RISQUE, "DELAI")
            probabilite = _validated_enum(risk_data.get("probabilite"), _VALID_PROBABILITE, "MOYENNE")
            impact = _validated_enum(risk_data.get("impact"), _VALID_IMPACT, "ELEVE")

            # create_risk_native() only reads attributes off `body` (no Pydantic
            # validation) — a plain namespace avoids importing a router module's
            # request schema into the agent layer.
            body = SimpleNamespace(
                titre=risk_data.get("titre", f"Retard: {item.titre}"),
                description=f"Jalon en retard de {days_overdue} jours: {item.description}",
                type_risque=type_risque,
                probabilite=probabilite,
                impact=impact,
                statut="IDENTIFIE",
                plan_mitigation=risk_data.get("plan_mitigation", ""),
                responsable_id=None,
                date_identification=today,
                date_echeance_mitigation=None,
                feuille_route_id=str(item.id),
                projet_id=item.projet_id,
            )
            await create_risk_native(body, {"email": "system:ai"})
            created += 1

        return {
            "items_scanned": len(overdue),
            "risks_created": created,
            "items_skipped": skipped,
        }

    def _generate_risk_for_overdue(self, item, days_overdue: int) -> dict | None:
        if not OllamaClient.get().is_available():
            return {
                "titre": f"Retard jalon: {item.titre}",
                "type_risque": "DELAI",
                "probabilite": "ELEVEE",
                "impact": "ELEVE",
                "plan_mitigation": "1. Analyser les causes du retard\n2. Réviser le calendrier\n3. Escalader si nécessaire",
            }

        prompt = (
            f"Un jalon IT est en retard:\n"
            f"Titre: {item.titre}\n"
            f"Date prévue: {item.date_fin}\n"
            f"Retard: {days_overdue} jours\n\n"
            f"Génère un risque projet en JSON strict (sans texte supplémentaire):\n"
            f'{{"titre": "", "type_risque": "DELAI|BUDGET|TECHNIQUE|RESSOURCE|AUTRE", '
            f'"probabilite": "FAIBLE|MOYENNE|ELEVEE", '
            f'"impact": "FAIBLE|MOYEN|ELEVE|CRITIQUE", '
            f'"plan_mitigation": "3 actions numérotées"}}'
        )
        self._call_count += 1
        raw = OllamaClient.get().complete(prompt, temperature=0.2, max_tokens=200)
        if not raw:
            return None

        try:
            m = re.search(r"\{[\s\S]+\}", raw)
            if m:
                return json.loads(m.group(0))
        except Exception:
            pass
        return None

    # ── Capability B — mitigation drafter ────────────────────────────────────

    def _draft_mitigation(self, context: dict) -> AgentResult:
        start = time.monotonic()
        titre = context.get("titre", "")
        type_risque = context.get("type_risque", "AUTRE")
        probabilite = context.get("probabilite", "MOYENNE")
        impact = context.get("impact", "MOYEN")

        fallback = (
            "1. Identifier et documenter les causes racines\n"
            "2. Mettre en place un suivi hebdomadaire avec le responsable\n"
            "3. Escalader si aucune amélioration dans 2 semaines"
        )

        if not OllamaClient.get().is_available():
            return AgentResult(
                agent_name=self.name, success=True,
                duration_ms=(time.monotonic() - start) * 1000,
                output={"suggestion": fallback},
                ollama_calls_made=0,
            )

        prompt = (
            f"Risque IT à mitiger:\n"
            f"Type: {type_risque} | Probabilité: {probabilite} | Impact: {impact}\n"
            f"Description: {titre}\n\n"
            f"Propose exactement 3 actions de mitigation concrètes et actionnables en français.\n"
            f"Format:\n1. [action]\n2. [action]\n3. [action]\nMaximum 150 mots total."
        )
        self._call_count += 1
        raw = OllamaClient.get().complete(prompt, temperature=0.3, max_tokens=200)
        suggestion = (raw or fallback).strip()

        return AgentResult(
            agent_name=self.name,
            success=True,
            duration_ms=(time.monotonic() - start) * 1000,
            output={"suggestion": suggestion},
            ollama_calls_made=self._call_count,
        )
