"""Service LDAP — authentification bind et mapping groupe → rôle applicatif.

Configuration (variables d'environnement ou .env) :
    LDAP_URL=ldap://localhost:389          # URL du serveur LDAP
    LDAP_BASE_DN=dc=biat,dc=local          # DN de base de l'annuaire
    LDAP_USERS_OU=ou=users,dc=biat,dc=local
    LDAP_GROUPS_OU=ou=groups,dc=biat,dc=local
    LDAP_BIND_DN=cn=admin,dc=biat,dc=local # Compte de service pour les recherches
    LDAP_BIND_PASSWORD=admin_secret
    LDAP_SEARCH_ATTR=mail                  # Attribut de recherche (mail ou uid)
    LDAP_TIMEOUT=5                         # Délai de connexion en secondes
    LDAP_DEFAULT_ROLE=                     # Rôle par défaut si aucun groupe ne correspond
                                           # (vide = refus de connexion)
"""
from __future__ import annotations

import logging
import os
from typing import Any

_log = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
_LDAP_URL      = os.getenv("LDAP_URL",      "ldap://localhost:389")
_BASE_DN       = os.getenv("LDAP_BASE_DN",  "dc=biat,dc=local")
_USERS_OU      = os.getenv("LDAP_USERS_OU",  f"ou=users,{_BASE_DN}")
_GROUPS_OU     = os.getenv("LDAP_GROUPS_OU", f"ou=groups,{_BASE_DN}")
_BIND_DN       = os.getenv("LDAP_BIND_DN",   f"cn=admin,{_BASE_DN}")
# No hardcoded fallback: an empty bind password just fails LDAP auth cleanly.
# api/main.py::_startup() already fails the app at startup (before any
# request) if AUTH_MODE requires LDAP and this is unset — see there for why
# the check lives at startup rather than here (this module is only imported
# lazily, on the first actual LDAP login attempt, not at app boot).
_BIND_PASSWORD = os.getenv("LDAP_BIND_PASSWORD", "")
_SEARCH_ATTR   = os.getenv("LDAP_SEARCH_ATTR", "mail")
_TIMEOUT       = int(os.getenv("LDAP_TIMEOUT", "5"))
_DEFAULT_ROLE  = os.getenv("LDAP_DEFAULT_ROLE", "")

# Mapping groupe LDAP (DN complet en minuscules) → rôle applicatif
_ROLE_MAP: dict[str, str] = {
    f"cn=admins,{_GROUPS_OU}".lower():      "Admin",
    f"cn=comptables,{_GROUPS_OU}".lower():  "Comptable",
    f"cn=chefs_projet,{_GROUPS_OU}".lower(): "Chef de Projet",
    f"cn=direction,{_GROUPS_OU}".lower():   "Direction",
}

# ── Import conditionnel de ldap3 ──────────────────────────────────────────────
try:
    from ldap3 import Server as _Server, Connection as _Connection
    from ldap3 import ALL as _ALL, SUBTREE as _SUBTREE
    from ldap3.core.exceptions import LDAPException as _LDAPException
    _LDAP3_AVAILABLE = True
except ImportError:
    _LDAP3_AVAILABLE = False
    _LDAPException = Exception  # type: ignore[assignment,misc]


# ── API publique ──────────────────────────────────────────────────────────────

def get_ldap_user_role(groups: list[str]) -> str | None:
    """Retourne le rôle applicatif correspondant au premier groupe LDAP reconnu.

    Args:
        groups: Liste de DNs de groupes LDAP (ex: ["cn=comptables,ou=groups,dc=biat,dc=local"]).

    Returns:
        Le rôle applicatif (str), ou None si aucun groupe ne correspond et
        qu'aucun rôle par défaut n'est configuré.
    """
    groups_lower = [g.lower() for g in groups]
    for dn_lower, role in _ROLE_MAP.items():
        if dn_lower in groups_lower:
            return role
    return _DEFAULT_ROLE or None


def authenticate_ldap(email: str, password: str) -> dict[str, Any] | None:
    """Authentifie un utilisateur via bind LDAP et retourne ses attributs.

    Processus en 3 étapes :
    1. Bind admin → recherche du DN de l'utilisateur par email (ou uid).
    2. Bind utilisateur → validation du mot de passe.
    3. Recherche des groupes → détermination du rôle applicatif.

    Args:
        email:    Email (ou uid) de l'utilisateur à authentifier.
        password: Mot de passe en clair (transmis via TLS en production).

    Returns:
        Dict d'attributs si l'authentification réussit :
            {
                "dn": str,          # DN LDAP complet de l'utilisateur
                "mail": str,        # Email
                "givenName": str,   # Prénom
                "sn": str,          # Nom de famille
                "uid": str,         # Identifiant court
                "groups": list[str],# DNs des groupes d'appartenance
                "role": str | None, # Rôle applicatif mappé depuis les groupes
            }
        None si l'authentification échoue (mauvais mdp, utilisateur introuvable,
        serveur injoignable).
    """
    if not _LDAP3_AVAILABLE:
        _log.warning(
            "ldap3 non installé — authentification LDAP désactivée. "
            "Installer via : pip install ldap3>=2.9"
        )
        return None

    try:
        server = _Server(_LDAP_URL, get_info=_ALL, connect_timeout=_TIMEOUT)

        # Étape 1 : bind admin pour rechercher le DN de l'utilisateur
        admin_conn = _Connection(
            server, user=_BIND_DN, password=_BIND_PASSWORD, auto_bind=True
        )
        try:
            admin_conn.search(
                search_base=_USERS_OU,
                search_filter=f"({_SEARCH_ATTR}={_escape_filter_value(email)})",
                search_scope=_SUBTREE,
                attributes=["cn", "uid", "mail", "givenName", "sn"],
            )

            if not admin_conn.entries:
                _log.debug("Utilisateur LDAP introuvable : %s", email)
                return None

            entry = admin_conn.entries[0]
            user_dn = entry.entry_dn

            # Étape 2 : bind utilisateur pour valider le mot de passe
            try:
                user_conn = _Connection(
                    server, user=user_dn, password=password, auto_bind=True
                )
                user_conn.unbind()
            except _LDAPException:
                _log.debug("Mot de passe LDAP incorrect pour : %s", email)
                return None

            # Étape 3 : recherche des groupes (filtre member=<dn>)
            admin_conn.search(
                search_base=_GROUPS_OU,
                search_filter=f"(member={user_dn})",
                search_scope=_SUBTREE,
                attributes=["cn"],
            )
            groups = [g.entry_dn for g in admin_conn.entries]

        finally:
            admin_conn.unbind()

    except _LDAPException as exc:
        _log.warning("Erreur de connexion LDAP (%s) : %s", _LDAP_URL, exc)
        return None
    except Exception as exc:
        _log.error("Erreur LDAP inattendue : %s", exc, exc_info=True)
        return None

    role = get_ldap_user_role(groups)

    return {
        "dn":        user_dn,
        "mail":      _attr(entry, "mail") or email,
        "givenName": _attr(entry, "givenName"),
        "sn":        _attr(entry, "sn"),
        "uid":       _attr(entry, "uid"),
        "groups":    groups,
        "role":      role,
    }


# ── Helpers privés ────────────────────────────────────────────────────────────

def _attr(entry: Any, name: str) -> str:
    """Extrait la valeur texte d'un attribut ldap3 Entry (robuste aux absences)."""
    try:
        val = entry[name].value
        return str(val) if val else ""
    except Exception:
        return ""


def _escape_filter_value(value: str) -> str:
    """Échappe les caractères spéciaux dans une valeur de filtre LDAP (RFC 4515)."""
    replacements = {
        "\\": "\\5c",
        "*":  "\\2a",
        "(":  "\\28",
        ")":  "\\29",
        "\0": "\\00",
    }
    for char, escaped in replacements.items():
        value = value.replace(char, escaped)
    return value
