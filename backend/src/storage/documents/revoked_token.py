"""Document Beanie pour la liste noire des tokens révoqués — migration de RevokedTokenORM.

Règles appliquées (Phase 2) :
  - id : str = le JTI du JWT (clé primaire naturelle, fourni à la création).
    Le champ s'appelait `jti` dans SQLAlchemy ; Beanie impose le nom `id` pour
    le PK. La couche service (Phase 3) remplacera `orm.jti` → `doc.id`.
  - user_id : soft reference (str | None) — pas de Link Beanie, cohérent avec
    le design choisi en Phase 0.5 (évite les cascades et simplifie les requêtes
    d'audit après suppression d'un utilisateur).
  - Collection nommée "revoked_tokens" (= __tablename__ SQLAlchemy).
  - Document append-only — jamais modifié après création (blacklist immuable).

Note Phase 3 — patterns de requête à migrer :
  - db.get(RevokedTokenORM, jti)          → await RevokedTokenDocument.get(jti)
  - db.add(RevokedTokenORM(jti=jti, ...)) → await RevokedTokenDocument(id=jti, ...).insert()
  - `return db.get(...) is not None`      → `return await RevokedTokenDocument.get(jti) is not None`

Note Phase 4 — optimisation TTL :
  Un TTL index sur `revoked_at` (expireAfterSeconds = durée_max_jwt_en_secondes) serait
  bénéfique pour purger automatiquement les tokens dont le JWT est de toute façon expiré.
  Nécessite de stocker `expires_at` (champ absent de RevokedTokenORM actuel).
  Prévoir cet ajout dans le script de migration Phase 5.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from beanie import Document, Indexed
from pydantic import Field


class RevokedTokenDocument(Document):
    """Token JWT révoqué (logout, rotation, révocation manuelle).

    Correspond champ-à-champ à RevokedTokenORM (table `revoked_tokens`).
    `id` = JTI du JWT — fourni par l'appelant, pas de default_factory.
    """

    id: str   # JTI — ex: "a1b2c3d4-e5f6-..."

    revoked_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    reason: str = "logout"   # "logout" | "session_revoked" | "token_rotation" | ...

    user_id: Annotated[str | None, Indexed()] = None   # soft ref vers users._id

    class Settings:
        name = "revoked_tokens"
