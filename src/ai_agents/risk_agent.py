"""Agent 5 — risk management.

Capability A: Nightly roadmap scan → creates AI-suggested risks for overdue items.
Capability B: On-demand mitigation plan drafting.
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import date

from sqlalchemy.orm import Session

from src.ai_agents.base_agent import BaseAgent
from src.ai_agents.models import AgentResult
from src.ai_agents.ollama_client import OllamaClient

logger = logging.getLogger(__name__)


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
        start = time.monotonic()
        db: Session = context["db"]
        today = date.today()

        try:
            from sqlalchemy import text
            from src.storage.orm_models_extra import FeuilleDeRouteORM, RisqueORM
            from sqlalchemy import select
            from uuid import UUID as _UUID

            item_id_filter = context.get("item_id")

            # Overdue roadmap items (optionally filtered to a single item)
            q = select(FeuilleDeRouteORM).where(
                FeuilleDeRouteORM.date_fin < today,
                FeuilleDeRouteORM.statut.notin_(["TERMINE", "ANNULE"]),
            )
            if item_id_filter:
                q = q.where(FeuilleDeRouteORM.id == _UUID(item_id_filter))
            overdue = db.execute(q).scalars().all()

            created, skipped = 0, 0

            for item in overdue:
                # Skip if an AI-suggested risk already exists and is still IDENTIFIE
                existing = db.execute(
                    select(RisqueORM).where(
                        RisqueORM.feuille_route_id == item.id,
                        RisqueORM.created_by == "system:ai",
                        RisqueORM.statut == "IDENTIFIE",
                    )
                ).scalar_one_or_none()

                if existing:
                    skipped += 1
                    continue

                days_overdue = (today - item.date_fin).days
                risk_data = self._generate_risk_for_overdue(item, days_overdue)
                if not risk_data:
                    skipped += 1
                    continue

                from uuid import uuid4
                from src.services.risk_service import calculate_criticite

                risk = RisqueORM(
                    id=uuid4(),
                    titre=risk_data.get("titre", f"Retard: {item.titre}"),
                    description=f"Jalon en retard de {days_overdue} jours: {item.description}",
                    type_risque=risk_data.get("type_risque", "DELAI"),
                    probabilite=risk_data.get("probabilite", "MOYENNE"),
                    impact=risk_data.get("impact", "ELEVE"),
                    niveau_criticite=calculate_criticite(
                        risk_data.get("probabilite", "MOYENNE"),
                        risk_data.get("impact", "ELEVE"),
                    ),
                    statut="IDENTIFIE",
                    plan_mitigation=risk_data.get("plan_mitigation", ""),
                    feuille_route_id=item.id,
                    created_by="system:ai",
                    date_identification=today,
                )
                db.add(risk)
                created += 1

            db.commit()
            logger.info("risk_scan_complete created=%d skipped=%d", created, skipped)

            return AgentResult(
                agent_name=self.name,
                success=True,
                duration_ms=(time.monotonic() - start) * 1000,
                output={
                    "items_scanned": len(overdue),
                    "risks_created": created,
                    "items_skipped": skipped,
                },
                ollama_calls_made=self._call_count,
            )

        except Exception as exc:
            logger.error("risk_scan_error: %s", exc)
            return AgentResult(
                agent_name=self.name,
                success=False,
                duration_ms=(time.monotonic() - start) * 1000,
                error=str(exc),
                ollama_calls_made=self._call_count,
            )

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
