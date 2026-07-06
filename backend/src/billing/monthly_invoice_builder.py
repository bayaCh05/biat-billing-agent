"""Build the monthly ClientInvoice to BIAT from a FicheMensuelle."""
from __future__ import annotations

import logging
from datetime import date, timedelta

from src.billing.invoice_numbering import InvoiceNumberer
from src.billing.project_repository import ProjectRepository
from src.models.client_invoice import ClientInvoice, ClientLineItem
from src.models.project import FicheMensuelle

logger = logging.getLogger(__name__)


class MonthlyInvoiceBuilder:
    """Construit la facture mensuelle BIAT IT → BIAT à partir d'une FicheMensuelle.

    Chaque fiche produit exactement une ClientInvoice avec deux types de lignes:
      - Type A : phases clôturées (JH × taux_jh, TVA 0%, compte 7061)
      - Type B : avances sur projets programmés (montant forfaitaire, TVA 0%, compte 4191)
    """

    # BIAT client details are fixed — BIAT IT has only one client
    _CLIENT_ID      = "biat_bank"
    _CLIENT_NAME    = "BIAT — Banque Internationale Arabe de Tunisie"
    _CLIENT_TAX_ID  = "0000217V/A/M/000"
    _CLIENT_ADDRESS = "70-72 Avenue Habib Bourguiba, 1080 Tunis, Tunisie"
    def __init__(
        self,
        issuer_name: str,
        issuer_tax_id: str,
        issuer_address: str = "",
        payment_terms_days: int = 30,
    ) -> None:
        self._issuer_name       = issuer_name
        self._issuer_tax_id     = issuer_tax_id
        self._issuer_address    = issuer_address
        self._payment_terms     = payment_terms_days

    def build_from_fiche(
        self,
        fiche: FicheMensuelle,
        project_repo: ProjectRepository,
        numberer: InvoiceNumberer,
    ) -> ClientInvoice:
        """Build the monthly invoice from a submitted or draft FicheMensuelle."""
        invoice_date = date.today()
        due_date = invoice_date + timedelta(days=self._payment_terms)
        lines: list[ClientLineItem] = []

        # ── Type A: phases clôturées ──────────────────────────────────────────
        for phase_id in fiche.phases_cloturees:
            phase = project_repo.get_phase(phase_id)
            if phase is None:
                logger.warning("monthly_invoice_skip_phase: phase %s not found in DB", phase_id)
                continue
            charte = project_repo.get_charte_for_project(phase.project_id)
            if charte is None:
                logger.warning("monthly_invoice_skip_phase: no active charte for project %s", phase.project_id)
                continue
            if phase.consumed_jh <= 0:
                logger.warning("monthly_invoice_skip_phase: phase %s has consumed_jh=%s, skipping zero-value line", phase_id, phase.consumed_jh)
                continue

            livrables_str = ", ".join(phase.livrables) if phase.livrables else "—"
            description = (
                f"[{phase.project_id}] {phase.name} — Phases clôturées\n"
                f"Livrables: {livrables_str}\n"
                f"Capacité: {phase.consumed_jh} JH × {charte.taux_jh} TND/JH"
            )
            line_total = round(phase.consumed_jh * charte.taux_jh, 3)
            lines.append(ClientLineItem(
                description=description,
                quantity=phase.consumed_jh,
                unit_price=charte.taux_jh,
                line_total=line_total,
                tva_rate=0.0,
                tva_amount=0.0,
                compte_produit="7061",
                charte_reference=charte.id,
                phase_id=phase.id,
            ))

        # ── Type B: avances sur projets programmés ────────────────────────────
        for avance in fiche.avances:
            description = (
                f"[{avance.project_id}] Avance sur projet programmé\n"
                f"Réf. planning: {avance.schedule_reference}"
            )
            lines.append(ClientLineItem(
                description=description,
                quantity=1,
                unit_price=avance.montant_ht,
                line_total=round(avance.montant_ht, 3),
                tva_rate=0.0,
                tva_amount=0.0,
                compte_produit="4191",  # avances reçues
                charte_reference=avance.charte_id,
                phase_id=None,
            ))

        if not lines:
            raise ValueError(
                f"Fiche {fiche.id} has no billable lines — "
                "all phases were skipped (missing charte, zero JH, or unknown phase id) "
                "and no avances were provided."
            )

        invoice_number = numberer.next_number()
        period = f"{fiche.period_month:02d}/{fiche.period_year}"

        invoice = ClientInvoice(
            invoice_number=invoice_number,
            invoice_date=invoice_date,
            due_date=due_date,
            issuer_name=self._issuer_name,
            issuer_tax_id=self._issuer_tax_id,
            issuer_address=self._issuer_address,
            client_id=self._CLIENT_ID,
            client_name=self._CLIENT_NAME,
            client_tax_id=self._CLIENT_TAX_ID,
            client_address=self._CLIENT_ADDRESS,
            line_items=lines,
            notes=f"Facture mensuelle BIAT IT — période {period} — réf. {fiche.id}",
            source_template_id=None,
        )

        # Advance fiche state to BILLED now that the invoice number is assigned
        if fiche.status.value == "submitted":
            try:
                project_repo.mark_as_billed(fiche.id, invoice_number)
            except ValueError:
                pass  # fiche may already be billed (idempotent rebuild)

        return invoice
