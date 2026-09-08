"""Document Beanie pour la rotation des refresh tokens (single-use, chaîné par
famille) — voir docs/ (ou le commit qui introduit ce fichier) pour la
conception complète.

Un seul enregistrement par refresh token JAMAIS émis (à la connexion, et à
chaque rotation) — contrairement à ActiveTokenDocument (sessions actives,
access tokens uniquement), qui n'a jamais suivi les refresh tokens du tout.

`family_id` : constant sur toute la chaîne de rotation d'une même session —
généré une fois à la connexion, propagé à chaque nouveau refresh token émis
par rotation. Permet de révoquer toute la lignée d'un coup (déconnexion,
détection de rejeu, changement de mot de passe) sans devoir connaître tous
les jti déjà émis.

`expires_at` : plafond ABSOLU de la famille, fixé à la connexion
(now + JWT_REFRESH_TOKEN_EXPIRE_DAYS) et jamais repoussé par une rotation —
une session ne peut pas s'auto-renouveler indéfiniment simplement en restant
active. Le JWT du refresh token lui-même porte le même `exp` (voir
jwt_handler.py::create_refresh_token) — le token ne prétend jamais être valide
plus longtemps que ce que ce système honorera réellement. Sert aussi de TTL
Mongo : le document disparaît de lui-même au plafond, qu'il ait été utilisé,
révoqué, ou juste jamais consommé.

`used` : True dès que ce jti précis a été échangé contre un nouveau (rotation
réussie) — un jti déjà `used` présenté à nouveau est un rejeu (vol probable) :
voir service_bridge.py::rotate_or_detect_reuse_native().

`revoked` : True si la famille entière a été tuée (déconnexion, rejeu détecté,
changement de mot de passe) — indépendant de `used`, un jti jamais consommé
peut être révoqué directement (ex: déconnexion juste après une rotation).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from beanie import Document, Indexed
from pydantic import Field
from pymongo import ASCENDING, IndexModel


class RefreshTokenDocument(Document):
    """Un refresh token émis (connexion ou rotation) — voir docstring module."""

    id: str   # JTI — ex: "a1b2c3d4-e5f6-..."

    family_id: Annotated[str, Indexed()]
    user_id:   Annotated[str, Indexed()]   # soft ref vers users._id

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime   # plafond ABSOLU de la famille — jamais repoussé par une rotation

    used:       bool = False
    used_at:    datetime | None = None
    replaced_by: str | None = None   # jti du token émis par la rotation de celui-ci

    revoked: bool = False

    class Settings:
        name = "refresh_tokens"
        indexes = [
            # TTL : MongoDB supprime le document dès expires_at < maintenant —
            # le plafond de la famille, pas une expiration par-token.
            IndexModel([("expires_at", ASCENDING)], expireAfterSeconds=0),
        ]
