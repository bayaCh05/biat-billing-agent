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
    # LINK (reset password) : code_or_token en clair — c'est un bearer token
    # à haute entropie (secrets.token_urlsafe(48)), déjà conçu pour être
    # transmis tel quel dans l'URL emailée, donc le hacher n'apporterait rien.
    # OTP : code_hash + salt à la place — un code à 6 chiffres (10^6
    # combinaisons) ne doit pas rester lisible en clair en base même si son
    # entropie ne justifie pas un hash lent type bcrypt (voir
    # service_bridge.py::_hash_otp_code). Un seul des deux couples est
    # rempli selon verification_type — jamais les deux à la fois.
    code_or_token: str | None = None
    code_hash: str | None = None
    salt: str | None = None
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
