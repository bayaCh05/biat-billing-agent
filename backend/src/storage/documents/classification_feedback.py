"""Document Beanie pour les corrections de classification — migration de ClassificationFeedbackORM.

Collection séparée (décision Phase 0 #9) — utilisée pour le réentraînement ML.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

from beanie import Document, Indexed
from pydantic import Field


class ClassificationFeedbackDocument(Document):
    """Correction de compte comptable par un utilisateur humain.

    Correspond à ClassificationFeedbackORM (table classification_feedback).
    Utilisée par le ML re-trainer (job dimanche 3h, seuil ML_RETRAIN_MIN_INVOICES).
    """

    id: UUID = Field(default_factory=uuid4)
    invoice_id: Annotated[str, Indexed()]   # soft ref vers invoices._id
    original_compte: str
    corrected_compte: str
    original_catalog_id: str | None = None
    corrected_catalog_id: str | None = None
    invoice_text: str = ""
    corrected_by: str = ""
    corrected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "classification_feedback"
