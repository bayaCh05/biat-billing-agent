"""Document Beanie pour le journal d'audit — migration de AuditLogORM.

Règles appliquées (Phase 2) :
  - id : UUID (cohérence avec UserDocument et tous les documents du projet).
  - Noms de champs identiques à AuditLogORM — compute_row_hash() accède aux
    attributs par nom et doit continuer à fonctionner sans modification.
  - Collection MongoDB nommée "audit_logs" (= __tablename__ SQLAlchemy).
  - Pas de sous-documents : AuditLog est une entité autonome, append-only.
  - before_value / after_value : dict natif Python → stocké tel quel en BSON.

⚠️  HMAC row_hash — incompatibilité de précision datetime à corriger en Phase 4
────────────────────────────────────────────────────────────────────────────────
compute_row_hash() (api/security/audit_integrity.py) construit son payload avec :
    created = dt.replace(tzinfo=None).isoformat()

    SQLite  → datetime naive, précision µs : "2026-07-08T14:32:15.123456"
    MongoDB → datetime UTC-aware lu par Motor, précision ms : replace(tzinfo=None)
              → "2026-07-08T14:32:15.123000"   ← 3 chiffres différents !

Conséquence : le hash calculé lors de la création (avant insertion MongoDB) diffère
du hash recalculé lors de la vérification (après lecture depuis MongoDB), car
MongoDB tronque les µs à la milliseconde (BSON Date = entier 64-bit en ms).

Fix planifié en Phase 4 :
  1. Modifier compute_row_hash() pour tronquer explicitement à la milliseconde :
         dt = dt.replace(microsecond=(dt.microsecond // 1000) * 1000)
     avant d'appeler isoformat(). Cela rend le hash identique quelle que soit
     la source (SQLite ou MongoDB).
  2. Script de migration Phase 5 : re-hash de tous les AuditLogORM existants
     avec la nouvelle formule avant de les insérer dans MongoDB.

NE PAS modifier audit_integrity.py avant la Phase 4 — changer la formule maintenant
casserait la vérification des logs SQLite existants en production.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import UUID, uuid4

from beanie import Document, Indexed
from pydantic import Field


class AuditLogDocument(Document):
    """Entrée du journal d'audit (trace de conformité BCT).

    Correspond champ-à-champ à AuditLogORM (table `audit_logs`).
    Document append-only — jamais modifié après création.
    """

    id: UUID = Field(default_factory=uuid4)

    created_at: Annotated[datetime, Indexed()] = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    # ── Qui ───────────────────────────────────────────────────────────────────
    user_id:    Annotated[str | None, Indexed()] = None
    user_email: str | None = None
    user_role:  str | None = None
    actor:      str = ""   # alias backwards-compat (= user_email pour les seeds)

    # ── Quoi ──────────────────────────────────────────────────────────────────
    action:        Annotated[str,       Indexed()]
    resource_type: Annotated[str | None, Indexed()] = None
    resource_id:   Annotated[str | None, Indexed()] = None
    entity_id:     str | None = None   # alias backwards-compat (= resource_id)

    # ── Snapshot d'état ───────────────────────────────────────────────────────
    before_value: dict[str, Any] | None = None
    after_value:  dict[str, Any] | None = None

    # ── Contexte requête ──────────────────────────────────────────────────────
    ip_address: str | None = None
    user_agent: str | None = None

    # ── Résultat ─────────────────────────────────────────────────────────────
    status: str = "SUCCESS"
    detail: str | None = None

    # ── Intégrité HMAC ────────────────────────────────────────────────────────
    row_hash: str | None = None   # calculé par compute_row_hash() après flush

    # ── Rebaseline (rotation de secret) ─────────────────────────────────────────
    # Miroir des 3 colonnes ajoutées côté SQLite par la migration Alembic
    # a1b2c3d4e5f7 (2026-07-15) — voir docs/audit_hmac_incident.md section 7.
    # row_hash n'est JAMAIS recalculé ; rebaseline_hash est stocké à côté,
    # calculé une fois sous le secret courant, pour les documents dont
    # row_hash ne vérifie plus après une rotation de AUDIT_HMAC_SECRET/JWT_SECRET.
    rebaseline_hash:   str | None = None
    rebaselined_at:    datetime | None = None
    rebaseline_reason: str | None = None

    # ── Rebaseline, generation 2 (post-2026-09-07 AUDIT_HMAC_SECRET
    # introduction — see docs/audit_hmac_incident.md section 8). Archives
    # the generation-1 values above before they get overwritten under the
    # new secret, so no rebaseline record is ever silently lost.
    prior_rebaseline_hash:   str | None = None
    prior_rebaselined_at:    datetime | None = None
    prior_rebaseline_reason: str | None = None

    class Settings:
        name = "audit_logs"
