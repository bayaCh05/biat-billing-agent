"""Authentification LDAP mock pour BIAT IT — environnement de développement.

Charge un ou plusieurs fichiers LDIF au démarrage et expose une fonction
authenticate() qui simule le comportement d'un serveur LDAP sans dépendance
externe (pas de python-ldap, pas de docker).

Utilisation :
    from src.services.mock_ldap_auth import MockLDAPAuth

    auth = MockLDAPAuth.get()          # singleton, chargé une seule fois
    user = auth.authenticate("mtrabelsi", "biat2026")
    # → {"uid": "mtrabelsi", "cn": "Mohamed Trabelsi", "mail": ..., "role": "CHEF_PROJET"}
    # → None si uid inconnu ou mot de passe incorrect
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

from src.services.ldif_parser import parse_ldif

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Table de correspondance departmentNumber → rôle applicatif
# ---------------------------------------------------------------------------
_DEPT_TO_ROLE: dict[str, str] = {
    "100": "Direction",
    "200": "Chef_Projet",
    "300": "Comptable",
    "900": "Admin",
}
_DEFAULT_ROLE = "Comptable"

# Dossier par défaut contenant les fichiers .ldif
_DEFAULT_LDIF_DIR = Path(__file__).parent.parent.parent / "mock_ldap_data"


def _map_role(department_number: str | None) -> str:
    """Convertit un departmentNumber LDIF en rôle applicatif.

    Retourne le rôle par défaut si le numéro est absent ou inconnu.
    """
    if not department_number:
        return _DEFAULT_ROLE
    return _DEPT_TO_ROLE.get(str(department_number).strip(), _DEFAULT_ROLE)


def _build_user_dict(entry: dict) -> dict:
    """Construit le dictionnaire utilisateur exposé par authenticate().

    Ne retourne pas le mot de passe.
    """
    return {
        "uid":        entry.get("uid", ""),
        "cn":         entry.get("cn", ""),
        "given_name": entry.get("given_name", ""),
        "sn":         entry.get("sn", ""),
        "mail":       entry.get("mail", ""),
        "department": entry.get("department_number", ""),
        "role":       _map_role(entry.get("department_number")),
    }


class MockLDAPAuth:
    """Singleton de l'annuaire mock — chargé une seule fois au démarrage."""

    _instance: "MockLDAPAuth | None" = None
    _lock = threading.Lock()

    def __init__(self, ldif_dir: str | Path | None = None) -> None:
        # Index uid → entry complet (incluant user_password pour la comparaison)
        self._index: dict[str, dict] = {}
        self._load(ldif_dir or _DEFAULT_LDIF_DIR)

    # ------------------------------------------------------------------
    # Accès singleton
    # ------------------------------------------------------------------

    @classmethod
    def get(cls, ldif_dir: str | Path | None = None) -> "MockLDAPAuth":
        """Retourne l'instance singleton, en la créant si nécessaire."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(ldif_dir)
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Réinitialise le singleton — utile dans les tests unitaires."""
        with cls._lock:
            cls._instance = None

    # ------------------------------------------------------------------
    # Chargement des fichiers LDIF
    # ------------------------------------------------------------------

    def _load(self, ldif_dir: str | Path) -> None:
        """Charge tous les fichiers .ldif du dossier dans l'index en mémoire."""
        directory = Path(ldif_dir)
        if not directory.exists():
            logger.warning("mock_ldap: dossier LDIF introuvable : %s", directory)
            return

        ldif_files = sorted(directory.glob("*.ldif"))
        if not ldif_files:
            logger.warning("mock_ldap: aucun fichier .ldif trouvé dans %s", directory)
            return

        total = 0
        for ldif_file in ldif_files:
            try:
                entries = parse_ldif(str(ldif_file))
                for entry in entries:
                    uid = entry.get("uid", "").strip()
                    if uid:
                        self._index[uid] = entry
                        total += 1
            except Exception as exc:
                logger.error("mock_ldap: erreur lors du chargement de %s : %s", ldif_file.name, exc)

        logger.info("mock_ldap: %d utilisateur(s) chargé(s) depuis %s", total, directory)

    # ------------------------------------------------------------------
    # Authentification
    # ------------------------------------------------------------------

    def authenticate(self, uid: str, password: str) -> dict | None:
        """Vérifie les identifiants et retourne le dict utilisateur ou None.

        Args:
            uid:      Identifiant de l'utilisateur (attribut LDIF 'uid').
            password: Mot de passe en clair à comparer.

        Returns:
            Dict utilisateur sans mot de passe si authentification réussie,
            None si uid inconnu ou mot de passe incorrect.
        """
        if not uid or not password:
            return None

        entry = self._index.get(uid.strip())
        if entry is None:
            logger.debug("mock_ldap: uid '%s' introuvable", uid)
            return None

        stored_password = entry.get("user_password", "")
        if stored_password != password:
            logger.debug("mock_ldap: mot de passe incorrect pour '%s'", uid)
            return None

        logger.info("mock_ldap: authentification réussie pour '%s'", uid)
        return _build_user_dict(entry)

    # ------------------------------------------------------------------
    # Utilitaires
    # ------------------------------------------------------------------

    def get_user(self, uid: str) -> dict | None:
        """Retourne le dict utilisateur (sans mot de passe) sans vérifier le mdp.

        Utile pour récupérer les attributs d'un utilisateur déjà authentifié.
        """
        entry = self._index.get(uid.strip())
        if entry is None:
            return None
        return _build_user_dict(entry)

    @property
    def user_count(self) -> int:
        """Nombre d'utilisateurs chargés dans l'index."""
        return len(self._index)
