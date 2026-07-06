"""Calcul des plans d'amortissement — méthodes linéaire et dégressive.

Méthode linéaire (art. 12 CIR tunisien) :
  taux = 1 / durée_ans
  dotation_annuelle = valeur_acquisition_HT × taux
  dotation_mensuelle = dotation_annuelle / 12
  VNC = valeur_acquisition_HT − dotation_cumulée

Méthode dégressive (accélérée) :
  taux_dégressif = taux_linéaire × coefficient
  La base de calcul est la VNC en début d'exercice (et non la valeur d'entrée).
  Quand la dotation dégressive devient inférieure à la dotation linéaire
  résiduelle, on bascule automatiquement en linéaire pour épuiser la VNC.

  Coefficients appliqués (conformes aux pratiques tunisiennes) :
    durée ≤ 4 ans → 1.5
    durée ≤ 6 ans → 2.0
    durée > 6 ans → 2.5
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class DepreciationLine:
    year: int
    month: int                       # 1-12
    depreciation_amount: float       # dotation du mois (TND)
    cumulated_depreciation: float    # amortissement cumulé en fin de mois (TND)
    book_value: float                # VNC en fin de mois (TND)
    method_used: str                 # "linear" | "degressive"

    @property
    def period_label(self) -> str:
        return f"{self.year}-{self.month:02d}"


@dataclass
class DepreciationSchedule:
    asset_id: str
    designation: str
    acquisition_cost_ht: float
    acquisition_date: date
    useful_life_years: int
    method: str                          # "linear" | "degressive"
    lines: list[DepreciationLine] = field(default_factory=list)

    @property
    def total_depreciated(self) -> float:
        return sum(ln.depreciation_amount for ln in self.lines)

    @property
    def final_book_value(self) -> float:
        return self.lines[-1].book_value if self.lines else self.acquisition_cost_ht

    def lines_for_year(self, year: int) -> list[DepreciationLine]:
        return [ln for ln in self.lines if ln.year == year]

    def annual_depreciation_for_year(self, year: int) -> float:
        return sum(ln.depreciation_amount for ln in self.lines_for_year(year))


# ── Calculator ────────────────────────────────────────────────────────────────

_DEGRESSIVE_COEFFICIENTS = [
    (4, 1.5),
    (6, 2.0),
]
_DEGRESSIVE_DEFAULT = 2.5


class DepreciationCalculator:
    """Generates full monthly depreciation schedules for an asset."""

    # ── Public API ────────────────────────────────────────────────────────────

    def schedule(
        self,
        asset_id: str,
        designation: str,
        acquisition_cost_ht: float,
        acquisition_date: date,
        useful_life_years: int,
        method: str = "linear",
    ) -> DepreciationSchedule:
        """Generate a complete monthly depreciation schedule from acquisition to full amortisation.

        Args:
            asset_id:             unique identifier of the asset
            designation:          human-readable name
            acquisition_cost_ht:  cost excl. VAT in TND
            acquisition_date:     date of acquisition (month of first depreciation)
            useful_life_years:    depreciation period in years
            method:               "linear" or "degressive"
        """
        if method == "linear":
            lines = self._linear_schedule(acquisition_cost_ht, acquisition_date, useful_life_years)
        elif method == "degressive":
            lines = self._degressive_schedule(acquisition_cost_ht, acquisition_date, useful_life_years)
        else:
            raise ValueError(f"Unknown depreciation method: '{method}'. Use 'linear' or 'degressive'.")

        return DepreciationSchedule(
            asset_id=asset_id,
            designation=designation,
            acquisition_cost_ht=acquisition_cost_ht,
            acquisition_date=acquisition_date,
            useful_life_years=useful_life_years,
            method=method,
            lines=lines,
        )

    def book_value_at(
        self,
        acquisition_cost_ht: float,
        acquisition_date: date,
        useful_life_years: int,
        ref_date: date,
        method: str = "linear",
    ) -> float:
        """Return the net book value (VNC) at ref_date without building the full schedule."""
        sched = self.schedule(
            asset_id="tmp",
            designation="tmp",
            acquisition_cost_ht=acquisition_cost_ht,
            acquisition_date=acquisition_date,
            useful_life_years=useful_life_years,
            method=method,
        )
        target = (ref_date.year, ref_date.month)
        for line in reversed(sched.lines):
            if (line.year, line.month) <= target:
                return line.book_value
        return acquisition_cost_ht

    # ── Linear ────────────────────────────────────────────────────────────────

    def _linear_schedule(
        self,
        cost: float,
        start: date,
        years: int,
    ) -> list[DepreciationLine]:
        monthly = round(cost / (years * 12), 6)
        total_months = years * 12
        lines: list[DepreciationLine] = []
        cumulated = 0.0

        y, m = start.year, start.month
        for i in range(total_months):
            is_last = i == total_months - 1
            amount = round(cost - cumulated, 6) if is_last else round(monthly, 6)
            cumulated = round(cumulated + amount, 6)
            vnc = round(max(0.0, cost - cumulated), 6)
            lines.append(DepreciationLine(
                year=y, month=m,
                depreciation_amount=amount,
                cumulated_depreciation=cumulated,
                book_value=vnc,
                method_used="linear",
            ))
            y, m = _next_month(y, m)

        return lines

    # ── Degressive ────────────────────────────────────────────────────────────

    def _degressive_schedule(
        self,
        cost: float,
        start: date,
        years: int,
    ) -> list[DepreciationLine]:
        coeff = self._degressive_coefficient(years)
        linear_rate = 1.0 / years
        degressive_rate = linear_rate * coeff

        total_months = years * 12
        lines: list[DepreciationLine] = []
        cumulated = 0.0
        vnc = cost

        y, m = start.year, start.month
        months_remaining = total_months

        for _ in range(total_months):
            is_last = months_remaining == 1

            # Annual degressive dotation based on current VNC
            annual_deg = vnc * degressive_rate
            monthly_deg = annual_deg / 12

            # Residual linear dotation for remaining months
            monthly_lin = vnc / months_remaining if months_remaining > 0 else vnc

            # Switch to linear when it gives a higher amount (standard rule)
            if monthly_lin >= monthly_deg or is_last:
                amount = round(vnc, 6) if is_last else round(monthly_lin, 6)
                method = "linear"
            else:
                amount = round(monthly_deg, 6)
                method = "degressive"

            cumulated = round(cumulated + amount, 6)
            vnc = round(max(0.0, cost - cumulated), 6)

            lines.append(DepreciationLine(
                year=y, month=m,
                depreciation_amount=amount,
                cumulated_depreciation=cumulated,
                book_value=vnc,
                method_used=method,
            ))
            y, m = _next_month(y, m)
            months_remaining -= 1

        return lines

    @staticmethod
    def _degressive_coefficient(years: int) -> float:
        for max_years, coeff in _DEGRESSIVE_COEFFICIENTS:
            if years <= max_years:
                return coeff
        return _DEGRESSIVE_DEFAULT


# ── Helpers ───────────────────────────────────────────────────────────────────

def _next_month(year: int, month: int) -> tuple[int, int]:
    if month == 12:
        return year + 1, 1
    return year, month + 1
