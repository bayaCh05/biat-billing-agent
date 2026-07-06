"""Pydantic models for project management — chartes, phases, fiches mensuelles."""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel


class PhaseStatus(str, Enum):
    OPEN      = "open"
    CLOSED    = "closed"
    CANCELLED = "cancelled"


class FicheStatus(str, Enum):
    DRAFT     = "draft"
    SUBMITTED = "submitted"
    BILLED    = "billed"


class CharteProjet(BaseModel):
    id: str                        # e.g. "CHR-2026-0042"
    project_id: str
    project_name: str
    client: str = "BIAT"
    valid_from: date
    valid_until: date | None = None
    budget_jh: float               # total jour-homme budget
    taux_jh: float                 # daily rate in TND (fixed, same for all staff)
    is_active: bool = True


class Phase(BaseModel):
    id: str
    project_id: str
    name: str
    description: str = ""
    planned_jh: float
    consumed_jh: float = 0.0
    status: PhaseStatus
    closed_date: date | None = None
    livrables: list[str] = []      # deliverable descriptions


class AvanceProgrammee(BaseModel):
    project_id: str
    charte_id: str
    description: str
    montant_ht: float
    schedule_reference: str        # reference to planned schedule document


class FicheMensuelle(BaseModel):
    id: str
    period_month: int              # 1–12
    period_year: int
    prepared_by: str
    prepared_at: datetime
    phases_cloturees: list[str]    # list of Phase.id
    avances: list[AvanceProgrammee]
    status: FicheStatus
    invoice_number: str | None = None  # set when status transitions to BILLED
