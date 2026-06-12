"""Génération des écritures comptables de dotation aux amortissements.

Schéma mensuel (PCE tunisien) :
  Débit  6811  Dotations aux amortissements       montant_mensuel
  Crédit 28xx  Amortissements cumulés (par immo)  montant_mensuel

  Le compte 28xx est déterminé par le compte d'immobilisation de l'actif
  (via ComptesAmortissement.get_amort_compte).

Schéma annuel (clôture d'exercice) :
  Même structure, montant = somme des 12 dotations mensuelles.
"""
from __future__ import annotations

from datetime import date

from src.utils.date_utils import last_day_int as _last_day_of_month
from uuid import UUID

from src.accounting.plan_comptable import ComptesAmortissement
from src.models.asset import Asset
from src.models.journal import JournalEntry, JournalLine


class DepreciationEntryGenerator:
    """Génère les écritures de dotation aux amortissements pour une immobilisation."""

    def monthly_entry(
        self,
        asset: Asset,
        year: int,
        month: int,
        amount: float,
    ) -> JournalEntry:
        """Écriture mensuelle de dotation aux amortissements.

        Args:
            asset:   immobilisation concernée
            year:    année de la dotation
            month:   mois de la dotation (1-12)
            amount:  montant de la dotation mensuelle (TND)
        """
        period = f"{year}-{month:02d}"
        compte_amort = ComptesAmortissement.get_amort_compte(asset.compte_immobilisation)
        short_id = str(asset.id)[:8].upper()
        ref = f"AMORT-{short_id}-{period}"

        return JournalEntry(
            reference=ref,
            date_ecriture=date(year, month, _last_day_of_month(year, month)),
            description=f"Dotation amortissement {period} — {asset.designation}",
            source_asset_id=asset.id,
            lines=[
                JournalLine(
                    compte=ComptesAmortissement.DOTATION,
                    libelle=f"Dotation amort. {asset.designation} {period}",
                    debit=round(amount, 3),
                ),
                JournalLine(
                    compte=compte_amort,
                    libelle=f"Amort. cumulé {asset.designation} {period}",
                    credit=round(amount, 3),
                ),
            ],
        )

    def annual_entry(
        self,
        asset: Asset,
        year: int,
        annual_amount: float,
    ) -> JournalEntry:
        """Écriture annuelle de clôture (dotation globale de l'exercice).

        Args:
            asset:          immobilisation concernée
            year:           exercice comptable
            annual_amount:  dotation annuelle totale (TND)
        """
        compte_amort = ComptesAmortissement.get_amort_compte(asset.compte_immobilisation)
        short_id = str(asset.id)[:8].upper()
        ref = f"AMORT-{short_id}-{year}"

        return JournalEntry(
            reference=ref,
            date_ecriture=date(year, 12, 31),
            description=f"Dotation amortissement {year} — {asset.designation}",
            source_asset_id=asset.id,
            lines=[
                JournalLine(
                    compte=ComptesAmortissement.DOTATION,
                    libelle=f"Dotation amort. {asset.designation} {year}",
                    debit=round(annual_amount, 3),
                ),
                JournalLine(
                    compte=compte_amort,
                    libelle=f"Amort. cumulé {asset.designation} {year}",
                    credit=round(annual_amount, 3),
                ),
            ],
        )

    def bulk_monthly_entries(
        self,
        asset: Asset,
        year: int,
        month: int,
        schedule_lines: list,
    ) -> list[JournalEntry]:
        """Generate entries for all assets in a batch for a given month.

        schedule_lines: list of DepreciationLine objects for that month.
        """
        entries = []
        for line in schedule_lines:
            if line.year == year and line.month == month and line.depreciation_amount > 0:
                entries.append(self.monthly_entry(asset, year, month, line.depreciation_amount))
        return entries


