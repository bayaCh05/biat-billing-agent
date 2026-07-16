"""Agent 5 — risk management.

Capability A: Nightly roadmap scan → creates AI-suggested risks for overdue items.
Capability B: On-demand mitigation plan drafting.
"""
from __future__ import annotations

import logging
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
        """Sync entry point — pymongo synchrone (sync_mongo_repository.py),
        jamais Beanie/Motor.

        Callers (scheduler.py's nightly job, the two /ai/scan-*-risk(s)
        routes, which are plain `def` and so also run outside any event
        loop) are all synchronous. This used to bridge into Beanie's async
        API via asyncio.run(), which crashed intermittently ("Future
        attached to a different loop") — the shared Motor client is bound
        to the event loop FastAPI's startup created it on, and asyncio.run()
        always creates a brand-new loop, breaking Motor's per-loop
        assumptions. Same reasoning as InvoiceProcessingOrchestrator/
        AuditAgent: a sync caller reads/writes Mongo via sync_mongo_repository.py,
        never awaits.
        """
        def _do() -> dict:
            from src.services.risk_service import calculate_criticite
            from src.storage.sync_mongo_repository import (
                create_risk_sync, existing_ai_risk_for_item_sync, overdue_roadmap_items_sync,
            )

            today = date.today()
            overdue = overdue_roadmap_items_sync(context.get("item_id"))
            created, skipped = 0, 0

            for item in overdue:
                item_id = item["_id"]
                if existing_ai_risk_for_item_sync(item_id):
                    skipped += 1
                    continue

                days_overdue = (today - item["date_fin"].date()).days
                risk_data = self._generate_risk_for_overdue(item, days_overdue)
                if not risk_data:
                    skipped += 1
                    continue

                type_risque = _validated_enum(
                    risk_data.get("type_risque"), _VALID_TYPE_RISQUE, "DELAI")
                probabilite = _validated_enum(
                    risk_data.get("probabilite"), _VALID_PROBABILITE, "MOYENNE")
                impact = _validated_enum(risk_data.get("impact"), _VALID_IMPACT, "ELEVE")

                description = item.get("description", "")
                create_risk_sync({
                    "titre": risk_data.get("titre", f"Retard: {item['titre']}"),
                    "description": f"Jalon en retard de {days_overdue} jours: {description}",
                    "type_risque": type_risque,
                    "probabilite": probabilite,
                    "impact": impact,
                    "niveau_criticite": calculate_criticite(probabilite, impact),
                    "statut": "IDENTIFIE",
                    "plan_mitigation": risk_data.get("plan_mitigation", ""),
                    "responsable_id": None,
                    "date_identification": today,
                    "date_echeance_mitigation": None,
                    "feuille_route_id": item_id,
                    "projet_id": item.get("projet_id"),
                    "created_by": "system:ai",
                })
                self._audit_risk_created(item_id, risk_data.get("titre", ""))
                created += 1

            output = {
                "items_scanned": len(overdue),
                "risks_created": created,
                "items_skipped": skipped,
            }
            logger.info(
                "risk_scan_complete created=%d skipped=%d",
                output["risks_created"], output["items_skipped"],
            )
            return dict(output=output)

        return self._run_safely(_do)

    def _audit_risk_created(self, feuille_route_id: str, titre: str) -> None:
        """Enregistre la création d'un risque IA dans l'audit trail — n'interrompt
        jamais le scan (même garantie que InvoiceProcessingOrchestrator._audit_ai())."""
        try:
            from src.models.audit import AuditLogCreate
            from src.storage.sync_mongo_repository import log_ai_audit_event_sync
            log_ai_audit_event_sync(AuditLogCreate(
                user_id="system:ai",
                user_email="system:ai",
                user_role="AI",
                action="RISK_CREATED",
                resource_type="Risque",
                resource_id=feuille_route_id,
                detail=f"Risque créé (scan roadmap): {titre}",
            ))
        except Exception as exc:
            logger.warning("risk_audit_failed: %s", exc)

    def _generate_risk_for_overdue(self, item: dict, days_overdue: int) -> dict | None:
        if not OllamaClient.get().is_available():
            return {
                "titre": f"Retard jalon: {item['titre']}",
                "type_risque": "DELAI",
                "probabilite": "ELEVEE",
                "impact": "ELEVE",
                "plan_mitigation": "1. Analyser les causes du retard\n2. Réviser le calendrier\n3. Escalader si nécessaire",
            }

        prompt = (
            f"Un jalon IT est en retard:\n"
            f"Titre: {item['titre']}\n"
            f"Date prévue: {item['date_fin']}\n"
            f"Retard: {days_overdue} jours\n\n"
            f"Génère un risque projet en JSON strict (sans texte supplémentaire):\n"
            f'{{"titre": "", "type_risque": "DELAI|BUDGET|TECHNIQUE|RESSOURCE|AUTRE", '
            f'"probabilite": "FAIBLE|MOYENNE|ELEVEE", '
            f'"impact": "FAIBLE|MOYEN|ELEVE|CRITIQUE", '
            f'"plan_mitigation": "3 actions numérotées"}}'
        )
        raw = self._call_ollama(prompt, temperature=0.2, max_tokens=200)
        return self._parse_json_response(raw)

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
        raw = self._call_ollama(prompt, temperature=0.3, max_tokens=200)
        suggestion = (raw or fallback).strip()

        return AgentResult(
            agent_name=self.name,
            success=True,
            duration_ms=(time.monotonic() - start) * 1000,
            output={"suggestion": suggestion},
            ollama_calls_made=self._call_count,
        )
