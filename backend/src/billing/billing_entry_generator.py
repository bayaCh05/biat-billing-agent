"""Génération des écritures comptables pour les factures émises (client).

Schéma pour chaque facture client :

  Débit  411  Client           TTC  (un seul débit, montant total)
  Crédit <compte_produit>      HT   (une ligne par compte de produit distinct)
  Crédit 4367 TVA collectée    TVA  (montant TVA total)

Les lignes de la même facture portant le même compte_produit sont agrégées.
"""
from __future__ import annotations

from collections import defaultdict

from src.accounting.plan_comptable import ComptesTVA, ComptesTiers
from src.models.client_invoice import ClientInvoice
from src.models.journal import JournalEntry, JournalLine


class BillingEntryError(Exception):
    pass


class BillingEntryGenerator:
    """Génère l'écriture comptable double-entrée d'une facture client."""

    def generate(self, invoice: ClientInvoice) -> JournalEntry:
        if invoice.amount_ttc <= 0:
            raise BillingEntryError(
                f"Montant TTC nul ou négatif pour la facture {invoice.invoice_number}"
            )

        lines: list[JournalLine] = []

        # Débit 411 — créance client (TTC)
        lines.append(JournalLine(
            compte=ComptesTiers.CLIENTS,
            libelle=f"Fact. {invoice.invoice_number} — {invoice.client_name}",
            debit=round(invoice.amount_ttc, 3),
        ))

        # Crédit par compte de produit (agrégé)
        produit_totals: dict[str, float] = defaultdict(float)
        for li in invoice.line_items:
            produit_totals[li.compte_produit] += li.line_total
        for compte, ht in sorted(produit_totals.items()):
            lines.append(JournalLine(
                compte=compte,
                libelle=f"Fact. {invoice.invoice_number} — produits SI",
                credit=round(ht, 3),
            ))

        # Crédit 4367 TVA collectée
        if invoice.tva_amount > 0:
            lines.append(JournalLine(
                compte=ComptesTVA.TVA_COLLECTEE,
                libelle=f"Fact. {invoice.invoice_number} — TVA collectée",
                credit=round(invoice.tva_amount, 3),
            ))

        return JournalEntry(
            reference=invoice.invoice_number,
            date_ecriture=invoice.invoice_date,
            description=(
                f"Facture émise {invoice.invoice_number} — {invoice.client_name}"
            ),
            lines=lines,
            source_invoice_id=invoice.id,
        )
