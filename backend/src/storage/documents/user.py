"""Document Beanie pour les comptes utilisateurs — migration de UserORM.

Règles appliquées (Phase 2) :
  - id : UUID (pas PydanticObjectId) — compatibilité avec active_tokens.user_id,
    revoked_tokens.user_id, audit_logs.resource_id et ChromaDB (cf. Phase 0.5).
  - Noms de champs identiques à UserORM pour limiter l'impact sur le reste du code.
  - Pas de sous-documents embarqués : password_verifications reste une collection
    séparée avec une référence user_id (décision Phase 0.5 #9).
  - Collection MongoDB nommée "users" (cohérence avec __tablename__ SQLAlchemy).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

from beanie import Document, Indexed
from pydantic import Field


class UserDocument(Document):
    """Compte utilisateur BIAT IT.

    Correspond champ-à-champ à UserORM (table `users`).
    Le champ `hashed_password` contient un hash argon2id ou bcrypt (migration
    lazy en cours — voir api/auth.py::needs_rehash).
    """

    id: UUID = Field(default_factory=uuid4)

    nom:       str
    prenom:    str
    email:     Annotated[str, Indexed(unique=True)]
    hashed_password: str
    role:      str
    departement: str = ""

    is_first_login: bool = True
    is_active:      bool = True

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    # ── Verrouillage de compte (Account lockout) ──────────────────────────────
    failed_login_attempts: int = 0
    locked_until:          datetime | None = None
    last_failed_login:     datetime | None = None
    last_login_at:         datetime | None = None
    last_login_ip:         str | None = None

    # ── Profil ────────────────────────────────────────────────────────────────
    profile_picture: str | None = None   # data URI base64 (PATCH /users/me/avatar)

    class Settings:
        name = "users"
        # L'index unique sur email est déclaré via Annotated[str, Indexed(unique=True)]
        # ci-dessus — Beanie le crée automatiquement lors de init_beanie().
