"""Agent 4 — accounting: journal entries, CAPEX assets, payment schedules.

All amounts are rule-based (NO LLM for figures).
LLM is used only for: accounting explanation text, CAPEX amortization duration.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import date, timedelta
from uuid import uuid4

from sqlalchemy.orm import Session

from src.ai_agents.base_agent import BaseAgent
from src.ai_agents.models import AgentResult
from src.ai_agents.ollama_client import OllamaClient
from src.models.enums import ChargeType, InvoiceDirection
from src.models.invoice import InvoiceRecord

logger = logging.getLogger(__name__)

_INSTALL_PERIOD = int(os.getenv("PAYMENT_INSTALLMENT_PERIOD_DAYS", "30"))
_LATE_PENALTY_RATE = float(os.getenv("LATE_PAYMENT_PENALTY_RATE", "0.10"))


class AccountingAgent(BaseAgent):
    name = "AccountingAgent"

    def __init__(self, entry_generator, journal_repo, cost_catalog) -> None:
        super().__init__()
        self._entry_gen = entry_generator
        self._journal_repo = journal_repo
        self._catalog = cost_catalog

    def run(self, context: dict) -> AgentResult:
        """context keys: invoice (InvoiceRecord), db (Session)"""
        start = time.monotonic()
        invoice: InvoiceRecord = context["invoice"]
        db: Session = context["db"]

        try:
            catalog_entry = None
            if invoice.cost_catalog_id:
                catalog_entry = self._catalog.get(invoice.cost_catalog_id)

            # 1) Journal entry
            journal_id, is_balanced, explanation = self._post_journal(invoice, catalog_entry, db)

            # 2) CAPEX asset
            asset_id = None
            amortization_years = None
            amortization_source = None
            if invoice.charge_type == ChargeType.CAPEX:
                asset_id, amortization_years, amortization_source = self._create_capex_asset(
                    invoice, catalog_entry, db
                )

            # 3) Payment schedule
            installment_ids = []
            if getattr(invoice, "payment_term_days", None):
                installment_ids = self._create_payment_schedule(invoice, db)

            return AgentResult(
                agent_name=self.name,
                success=True,
                duration_ms=(time.monotonic() - start) * 1000,
                output={
                    "journal_entry_id": journal_id,
                    "is_balanced": is_balanced,
                    "accounting_explanation": explanation,
                    "asset_created": asset_id is not None,
                    "asset_id": asset_id,
                    "amortization_years": amortization_years,
                    "amortization_source": amortization_source,
                    "installments_created": len(installment_ids),
                    "installment_ids": installment_ids,
                },
                explanation=explanation,
                ollama_calls_made=self._call_count,
            )

        except Exception as exc:
            logger.error("accounting_agent_error: %s", exc)
            return AgentResult(
                agent_name=self.name,
                success=False,
                duration_ms=(time.monotonic() - start) * 1000,
                error=str(exc),
                ollama_calls_made=self._call_count,
            )

    # ── Journal entry ─────────────────────────────────────────────────────────

    def _post_journal(self, invoice: InvoiceRecord, catalog_entry,
                      db: Session) -> tuple[str | None, bool, str]:
        if not catalog_entry:
            return None, False, ""

        try:
            entry = self._entry_gen.generate(invoice, catalog_entry)

            is_balanced = abs(
                sum(l.debit or 0 for l in entry.lines) -
                sum(l.credit or 0 for l in entry.lines)
            ) < 0.005

            explanation = self._generate_accounting_explanation(invoice, entry)
            entry.accounting_explanation = explanation

            self._journal_repo.save(entry)

            return str(entry.id), is_balanced, explanation

        except Exception as exc:
            logger.error("journal_post_error: %s", exc)
            return None, False, ""

    def _generate_accounting_explanation(self, invoice: InvoiceRecord, entry) -> str:
        if not OllamaClient.get().is_available():
            return ""
        try:
            issuer = invoice.issuer_name.value or "Fournisseur"
            amount = invoice.amount_ttc.value or 0
            lines_text = "\n".join(
                f"  {'Débit' if l.debit else 'Crédit'} {l.compte} {l.libelle}: "
                f"{l.debit or l.credit:.3f} TND"
                for l in entry.lines
            )
            prompt = (
                f"Tu es expert-comptable tunisien (PCE).\n"
                f"Facture de {issuer} pour {amount:.3f} TND TTC.\n\n"
                f"Écriture comptable générée:\n{lines_text}\n\n"
                f"Explique en 2 phrases en français pourquoi cette écriture est correcte "
                f"selon le PCE tunisien. Mentionne le principe comptable appliqué. "
                f"Maximum 200 caractères."
            )
            self._call_count += 1
            raw = OllamaClient.get().complete(prompt, temperature=0.1, max_tokens=100)
            return (raw or "").strip()[:250]
        except Exception:
            return ""

    # ── CAPEX asset ───────────────────────────────────────────────────────────

    def _create_capex_asset(self, invoice: InvoiceRecord, catalog_entry,
                             db: Session) -> tuple[str | None, int | None, str | None]:
        if not catalog_entry:
            return None, None, None

        description = ""
        if invoice.line_items:
            description = invoice.line_items[0].description or ""
        if not description:
            description = catalog_entry.label

        amortization_years, source = self._get_amortization_duration(description, catalog_entry)

        compte_immob = catalog_entry.compte
        compte_amort = "28" + compte_immob[1:] if len(compte_immob) > 2 else "28184"

        acquisition_cost = invoice.amount_ht.value or 0.0
        acquisition_date = invoice.invoice_date.value or date.today()

        try:
            from src.models.asset import CapexAsset
            from src.capex.asset_repository import AssetRepository

            asset = CapexAsset(
                designation=description,
                compte_immobilisation=compte_immob,
                compte_amortissement=compte_amort,
                acquisition_date=acquisition_date,
                acquisition_cost_ht=acquisition_cost,
                useful_life_years=amortization_years,
                depreciation_method="linear",
                amortization_source=source,
                supplier_invoice_id=str(invoice.id),
            )
            repo = AssetRepository(db)
            repo.save(asset)
            return str(asset.id), amortization_years, source
        except Exception as exc:
            logger.warning("capex_asset_error: %s", exc)
            return None, amortization_years, source

    def _get_amortization_duration(self, description: str, catalog_entry) -> tuple[int, str]:
        """Ask Ollama for the PCE amortization duration. Falls back to 5 years."""
        if not OllamaClient.get().is_available():
            return 5, "DEFAULT"

        prompt = (
            f"Droit comptable tunisien — PCE.\n"
            f"Quelle est la durée d'amortissement standard en années pour:\n"
            f'"{description}" (catégorie: {catalog_entry.label})?\n\n'
            f"Réponds UNIQUEMENT avec un entier entre 1 et 20.\n"
            f"Références: matériel informatique→3-5ans, serveur→5ans, logiciel→3ans, "
            f"véhicule→5ans, mobilier→10ans, bâtiment→20ans."
        )
        self._call_count += 1
        raw = OllamaClient.get().complete(prompt, temperature=0.0, max_tokens=5)
        if raw:
            import re
            # D'abord: réponse idéale = entier seul sur la ligne
            m = re.search(r"^\s*(\d{1,2})\s*$", raw.strip())
            if not m:
                # Sinon: cherche un entier 1-20 entouré de séparateurs de mots
                m = re.search(r"\b([1-9]|1\d|20)\b", raw)
            if m:
                years = int(m.group(1))
                if 1 <= years <= 20:
                    return years, "AI"
            logger.warning("amortization_parse_failed raw=%r → fallback 5 ans", raw[:80])
        return 5, "DEFAULT"

    # ── Payment schedule ──────────────────────────────────────────────────────

    def _create_payment_schedule(self, invoice: InvoiceRecord, db: Session) -> list[str]:
        term = getattr(invoice, "payment_term_days", None)
        if not term or not invoice.amount_ttc.value:
            return []

        period = _INSTALL_PERIOD
        n_full = term // period
        remainder = term % period
        total = n_full + (1 if remainder > 0 else 0)
        if total == 0:
            return []

        base_amount = invoice.amount_ttc.value / total
        received = invoice.received_at.date() if hasattr(invoice.received_at, "date") else date.today()

        ids = []
        try:
            from src.storage.orm_models_payments import PaymentInstallmentORM

            for i in range(1, total + 1):
                period_days = period if (i < total or remainder == 0) else remainder
                cumulative_days = period * (i - 1) + period_days
                due_date = received + timedelta(days=cumulative_days)

                installment = PaymentInstallmentORM(
                    id=uuid4(),
                    invoice_id=str(invoice.id),
                    installment_number=i,
                    total_installments=total,
                    base_amount=round(base_amount, 3),
                    current_amount=round(base_amount, 3),
                    due_date=due_date,
                    status="PENDING",
                    late_periods=0,
                )
                db.add(installment)
                ids.append(str(installment.id))

            db.commit()
            logger.info("payment_schedule_created invoice=%s installments=%d", invoice.id, total)
        except Exception as exc:
            logger.warning("payment_schedule_error: %s", exc)

        return ids

    # ── Consistency check ─────────────────────────────────────────────────────

    def check_consistency(self, db: Session) -> dict:
        """Audit journal entries for balance and coverage."""
        from sqlalchemy import select, func, text

        issues = []
        total_checked = 0

        try:
            # Check 1: unbalanced journal entries
            rows = db.execute(text(
                "SELECT je.id, je.reference, "
                "SUM(jl.debit) AS total_debit, SUM(jl.credit) AS total_credit "
                "FROM journal_entries je "
                "JOIN journal_lines jl ON jl.entry_id = je.id "
                "GROUP BY je.id HAVING ABS(COALESCE(SUM(jl.debit),0) - COALESCE(SUM(jl.credit),0)) > 0.005"
            )).fetchall()
            total_checked += 1
            if rows:
                issues.append({"type": "UNBALANCED_ENTRIES", "count": len(rows),
                                "detail": [{"id": str(r[0]), "reference": r[1]} for r in rows[:5]]})

        except Exception as exc:
            logger.warning("consistency_check_error: %s", exc)

        return {
            "consistency_score": round(1 - len(issues) / max(total_checked, 1), 3),
            "total_checked": total_checked,
            "issues": issues,
        }
