"""Document Beanie pour les sessions actives — migration de ActiveTokenORM.

Règles appliquées (Phase 2) :
  - id : str = le JTI du JWT (clé primaire naturelle, fourni à la création).
    Le champ s'appelait `jti` dans SQLAlchemy ; Beanie impose le nom `id` pour
    le PK. La couche service (Phase 3) remplacera `orm.jti` → `doc.id`.
  - user_id : str (non-nullable) — soft reference vers users._id.
    Pas de Link Beanie : la révocation doit rester possible même si l'utilisateur
    est supprimé (ex : compte désactivé d'urgence).
  - Collection nommée "active_tokens" (= __tablename__ SQLAlchemy).

⟹ Amélioration MongoDB native : TTL index sur expires_at
  MongoDB supprime automatiquement les documents dont expires_at < maintenant,
  sans intervention du scheduler. Remplace le job cleanup SQLAlchemy pour le
  mode MongoDB.
  expireAfterSeconds=0 signifie "supprimer dès que expires_at est dépassé".

Note Phase 3 — patterns de requête à migrer (accès par attribut `.jti` → `.id`) :
  - session.get(ActiveTokenORM, jti)         → await ActiveTokenDocument.get(jti)
  - db.merge(ActiveTokenORM(jti=jti, ...))   → await ActiveTokenDocument(id=jti, ...).save()
  - orm.jti[:8]                              → doc.id[:8]
  - orm.jti == current_jti                   → doc.id == current_jti
  - ActiveTokenORM.jti.startswith(prefix)    → ActiveTokenDocument.id.regex(f"^{re.escape(prefix)}")
  - WHERE user_id==u, revoked==False,        → ActiveTokenDocument.find(
      expires_at > now                             ActiveTokenDocument.user_id == u,
                                                   ActiveTokenDocument.revoked == False,
                                                   ActiveTokenDocument.expires_at > now)

Note Phase 4 — index composé recommandé :
  Les requêtes filtrent toujours sur (user_id, revoked, expires_at).
  Créer : IndexModel([("user_id", 1), ("revoked", 1), ("expires_at", -1)])
  pour éliminer les COLLSCAN sur les tables de sessions actives en production.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from beanie import Document, Indexed
from pydantic import Field
from pymongo import ASCENDING, IndexModel


class ActiveTokenDocument(Document):
    """Session JWT active (access token en cours de validité).

    Correspond champ-à-champ à ActiveTokenORM (table `active_tokens`).
    `id` = JTI du JWT — fourni par l'appelant, pas de default_factory.

    MongoDB supprime automatiquement ce document quand expires_at est dépassé
    grâce au TTL index défini dans Settings.indexes (expireAfterSeconds=0).
    """

    id: str   # JTI — ex: "a1b2c3d4-e5f6-..."

    user_id:   Annotated[str, Indexed()]   # soft ref vers users._id
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    expires_at: datetime   # requis — calculé par create_access_token()

    ip_address: str | None = None
    user_agent: str | None = None

    revoked: bool = False   # True = révoqué manuellement avant expiration naturelle

    class Settings:
        name = "active_tokens"
        indexes = [
            # TTL index : MongoDB supprime le document dès expires_at < now.
            # Remplace le job cleanup du scheduler pour le mode MongoDB.
            IndexModel([("expires_at", ASCENDING)], expireAfterSeconds=0),
        ]
