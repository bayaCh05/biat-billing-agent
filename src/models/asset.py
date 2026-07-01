"""Modèle d'immobilisation (registre des immobilisations CAPEX).

Utilisé à partir du Jalon 5 (module CAPEX). Défini ici dès le Jalon 1
car JournalEntry.source_asset_id en référence l'identifiant.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class Asset(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    designation: str                         # libellé de l'immobilisation
    compte_immobilisation: str               # ex. "2183" matériel informatique
    compte_amortissement: str                # ex. "2893" amort. mat. informatique
    acquisition_date: date
    acquisition_cost_ht: float               # valeur d'entrée HT en TND
    useful_life_years: int                   # durée d'amortissement en années
    depreciation_method: str = "linear"      # "linear" | "degressive"
    supplier_invoice_id: UUID | str | None = None  # facture d'acquisition
    amortization_source: str | None = None   # "AI" | "DEFAULT" | "MANUAL"
    amortization_suggestion_raw: str | None = None
    notes: str = ""
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def annual_depreciation(self) -> float:
        return round(self.acquisition_cost_ht / self.useful_life_years, 3)

    @property
    def monthly_depreciation(self) -> float:
        return round(self.annual_depreciation / 12, 3)

    def book_value_at(self, ref_date: date) -> float:
        """Valeur nette comptable à une date donnée."""
        if self.depreciation_method == "degressive":
            from src.capex.depreciation_calculator import DepreciationCalculator
            return DepreciationCalculator().book_value_at(
                acquisition_cost_ht=self.acquisition_cost_ht,
                acquisition_date=self.acquisition_date,
                useful_life_years=self.useful_life_years,
                ref_date=ref_date,
                method="degressive",
            )
        months_elapsed = (
            (ref_date.year - self.acquisition_date.year) * 12
            + (ref_date.month - self.acquisition_date.month)
        )
        depreciated = self.monthly_depreciation * max(0, months_elapsed)
        return max(0.0, round(self.acquisition_cost_ht - depreciated, 3))


# Alias used by the AI accounting agent
CapexAsset = Asset
