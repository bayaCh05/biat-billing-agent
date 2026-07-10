"""Document Beanie pour les tokens de vérification email — migration de PasswordVerificationORM.

TTL index sur expires_at : MongoDB supprime automatiquement les tokens expirés.
Remplace le nettoyage manuel (pas de job scheduler nécessaire en mode MongoDB).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

from beanie import Document, Indexed
from pydantic import Field
from pymongo import ASCENDING, IndexModel


class PasswordVerificationDocument(Document):
    """Token de vérification email (OTP ou lien sécurisé).

    Correspond à PasswordVerificationORM (table password_verifications).
    user_id : soft ref vers UserDocument._id (UUID).
    Suppression automatique après expires_at via TTL index MongoDB.
    """

    id: UUID = Field(default_factory=uuid4)
    user_id: Annotated[UUID, Indexed()]   # soft ref vers users._id
    verification_type: str    # "OTP" | "LINK"
    code_or_token: str
    purpose: str              # "FIRST_LOGIN" | "VOLUNTARY_CHANGE" | "FORGOT_PASSWORD"
    expires_at: datetime      # requis — calculé à la création
    used: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "password_verifications"
        indexes = [
            # TTL : MongoDB supprime le document dès expires_at < maintenant.
            IndexModel([("expires_at", ASCENDING)], expireAfterSeconds=0),
        ]
