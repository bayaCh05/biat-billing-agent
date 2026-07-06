"""Génération des écritures comptables (journal général) à partir des factures.

Schémas d'écritures appliqués :

  Facture fournisseur OPEX ou CAPEX — avec TVA :
    Débit  <compte_charge_ou_immo>    HT
    Débit  4366 TVA déductible        tva_amount
    Crédit 401  Fournisseur           TTC

  Facture fournisseur — sans TVA (tva_rate = 0) :
    Débit  <compte_charge>            HT (= TTC)
    Crédit 401  Fournisseur           HT (= TTC)

  Facture client — avec TVA :
    Débit  411  Client                TTC
    Crédit <compte_produit>           HT
    Crédit 4367 TVA collectée         tva_amount

  Facture client — sans TVA :
    Débit  411  Client                HT (= TTC)
    Crédit <compte_produit>           HT (= TTC)

Note : le schéma est identique pour OPEX et CAPEX côté fournisseur — c'est le
numéro de compte (6xxx vs 2xxx) qui différencie les deux dans le plan comptable.
"""
from __future__ import annotations

from datetime import date
from uuid import UUID

from src.accounting.plan_comptable import ComptesTiers, ComptesTVA
from src.cost_catalog.catalog import CostCatalogEntry
from src.models.enums import ChargeFlux
from src.models.invoice import InvoiceRecord
from src.models.journal import JournalEntry, JournalLine


class EntryGenerationError(Exception):
    """Levée quand les données de la facture ne permettent pas de générer l'écriture."""


class EntryGenerator:
    """Génère une écriture comptable équilibrée depuis une facture classifiée."""

    def generate(
        self,
        invoice: InvoiceRecord,
        catalog_entry: CostCatalogEntry,
    ) -> JournalEntry:
        """Générer l'écriture pour une facture dont la classification est connue.

        Raises:
            EntryGenerationError: si les montants ne sont pas extraits ou si le
                flux du catalog_entry ne supporte pas la génération automatique.
        """
        ht = invoice.amount_ht.value
        tva = invoice.tva_amount.value or 0.0
        ttc = invoice.amount_ttc.value

        if ht is None or ttc is None:
            raise EntryGenerationError(
                f"Facture {invoice.id} : montants non extraits "
                f"(HT={ht}, TTC={ttc}). Écriture impossible."
            )

        ref = invoice.invoice_number.value or str(invoice.id)[:8].upper()
        inv_date = invoice.invoice_date.value or date.today()
        issuer = invoice.issuer_name.value or "Fournisseur inconnu"
        recipient = invoice.recipient_name.value or "Client inconnu"

        if catalog_entry.flux == ChargeFlux.FOURNISSEUR:
            return self._fournisseur_entry(
                invoice_id=invoice.id,
                reference=ref,
                inv_date=inv_date,
                ht=round(ht, 3),
                tva=round(tva, 3),
                ttc=round(ttc, 3),
                compte_charge=catalog_entry.compte,
                label_charge=catalog_entry.label,
                issuer_name=issuer,
            )
        elif catalog_entry.flux == ChargeFlux.CLIENT:
            return self._client_entry(
                invoice_id=invoice.id,
                reference=ref,
                inv_date=inv_date,
                ht=round(ht, 3),
                tva=round(tva, 3),
                ttc=round(ttc, 3),
                compte_produit=catalog_entry.compte,
                label_produit=catalog_entry.label,
                recipient_name=recipient,
            )
        else:
            raise EntryGenerationError(
                f"Flux '{catalog_entry.flux.value}' non supporté pour la génération "
                "automatique d'écritures (seuls 'fournisseur' et 'client' sont pris en charge)."
            )

    # ── Schémas d'écritures ───────────────────────────────────────────────────

    def _fournisseur_entry(
        self,
        invoice_id: UUID,
        reference: str,
        inv_date: date,
        ht: float,
        tva: float,
        ttc: float,
        compte_charge: str,
        label_charge: str,
        issuer_name: str,
    ) -> JournalEntry:
        lines: list[JournalLine] = [
            JournalLine(
                compte=compte_charge,
                libelle=f"{label_charge} — {reference}",
                debit=ht,
            ),
        ]
        if tva > 0:
            lines.append(JournalLine(
                compte=ComptesTVA.TVA_DEDUCTIBLE,
                libelle=f"TVA déductible {reference}",
                debit=tva,
            ))
        lines.append(JournalLine(
            compte=ComptesTiers.FOURNISSEURS,
            libelle=issuer_name,
            credit=ttc,
        ))
        return JournalEntry(
            reference=reference,
            date_ecriture=inv_date,
            description=f"Facture fournisseur — {issuer_name} — {label_charge}",
            lines=lines,
            source_invoice_id=invoice_id,
        )

    def _client_entry(
        self,
        invoice_id: UUID,
        reference: str,
        inv_date: date,
        ht: float,
        tva: float,
        ttc: float,
        compte_produit: str,
        label_produit: str,
        recipient_name: str,
    ) -> JournalEntry:
        lines: list[JournalLine] = [
            JournalLine(
                compte=ComptesTiers.CLIENTS,
                libelle=recipient_name,
                debit=ttc,
            ),
            JournalLine(
                compte=compte_produit,
                libelle=f"{label_produit} — {reference}",
                credit=ht,
            ),
        ]
        if tva > 0:
            lines.append(JournalLine(
                compte=ComptesTVA.TVA_COLLECTEE,
                libelle=f"TVA collectée {reference}",
                credit=tva,
            ))
        return JournalEntry(
            reference=reference,
            date_ecriture=inv_date,
            description=f"Facture client — {recipient_name} — {label_produit}",
            lines=lines,
            source_invoice_id=invoice_id,
        )
