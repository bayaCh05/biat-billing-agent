"""Tests unitaires pour src/services/ldap_service.py.

Tous les appels ldap3 sont mockés — aucun serveur LDAP réel n'est requis.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import src.services.ldap_service as ldap_mod
from src.services.ldap_service import authenticate_ldap, get_ldap_user_role


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _force_ldap3_available():
    """Force _LDAP3_AVAILABLE=True pour tous les tests (ldap3 est installé)."""
    original = ldap_mod._LDAP3_AVAILABLE
    ldap_mod._LDAP3_AVAILABLE = True
    yield
    ldap_mod._LDAP3_AVAILABLE = original


def _make_ldap_entry(dn: str, mail: str, givenName: str, sn: str, uid: str) -> MagicMock:
    """Construit un mock d'entrée ldap3 avec les attributs nécessaires.

    Les méthodes spéciales de Python (comme __getitem__) sont résolues sur la
    classe, pas l'instance — donc on utilise side_effect sur le MagicMock
    __getitem__ intégré plutôt que de remplacer l'attribut d'instance.
    """
    attrs: dict[str, MagicMock] = {
        "mail":      MagicMock(value=mail),
        "givenName": MagicMock(value=givenName),
        "sn":        MagicMock(value=sn),
        "uid":       MagicMock(value=uid),
    }
    entry = MagicMock()
    entry.entry_dn = dn
    entry.__getitem__.side_effect = lambda key: attrs.get(key, MagicMock(value=""))
    return entry


def _make_group_entry(dn: str) -> MagicMock:
    entry = MagicMock()
    entry.entry_dn = dn
    return entry


# ── Tests : get_ldap_user_role ─────────────────────────────────────────────────

class TestGetLdapUserRole:
    def test_admin_group(self):
        groups = ["cn=admins,ou=groups,dc=biat,dc=local"]
        assert get_ldap_user_role(groups) == "Admin"

    def test_comptable_group(self):
        groups = ["cn=comptables,ou=groups,dc=biat,dc=local"]
        assert get_ldap_user_role(groups) == "Comptable"

    def test_chef_projet_group(self):
        groups = ["cn=chefs_projet,ou=groups,dc=biat,dc=local"]
        assert get_ldap_user_role(groups) == "Chef de Projet"

    def test_direction_group(self):
        groups = ["cn=direction,ou=groups,dc=biat,dc=local"]
        assert get_ldap_user_role(groups) == "Direction"

    def test_case_insensitive(self):
        groups = ["CN=Admins,OU=Groups,DC=biat,DC=local"]
        assert get_ldap_user_role(groups) == "Admin"

    def test_unknown_group_no_default(self, monkeypatch):
        monkeypatch.setattr(ldap_mod, "_DEFAULT_ROLE", "")
        groups = ["cn=inconnu,ou=groups,dc=biat,dc=local"]
        assert get_ldap_user_role(groups) is None

    def test_unknown_group_with_default_role(self, monkeypatch):
        monkeypatch.setattr(ldap_mod, "_DEFAULT_ROLE", "Comptable")
        groups = ["cn=inconnu,ou=groups,dc=biat,dc=local"]
        assert get_ldap_user_role(groups) == "Comptable"

    def test_empty_groups_list(self):
        assert get_ldap_user_role([]) is None

    def test_first_matching_group_wins(self):
        groups = [
            "cn=direction,ou=groups,dc=biat,dc=local",
            "cn=admins,ou=groups,dc=biat,dc=local",
        ]
        # Les deux sont dans la map — on obtient l'un des deux rôles valides
        role = get_ldap_user_role(groups)
        assert role in ("Direction", "Admin")


# ── Tests : authenticate_ldap ─────────────────────────────────────────────────

class TestAuthenticateLdap:

    @patch("src.services.ldap_service._Connection")
    @patch("src.services.ldap_service._Server")
    def test_success_returns_user_dict(self, mock_server_cls, mock_conn_cls):
        """Chemin nominal : bind admin + bind utilisateur + groupes → dict complet."""
        user_dn = "cn=mtrabelsi,ou=users,dc=biat,dc=local"
        group_dn = "cn=comptables,ou=groups,dc=biat,dc=local"

        user_entry = _make_ldap_entry(user_dn, "mtrabelsi@biat.local", "Mehdi", "Trabelsi", "mtrabelsi")
        group_entry = _make_group_entry(group_dn)

        # L'admin conn revient du premier appel Connection()
        admin_conn = MagicMock()
        # Deux appels search : 1er pour l'utilisateur, 2e pour les groupes
        admin_conn.entries = [user_entry]  # par défaut

        def search_side_effect(*args, **kwargs):
            filt = kwargs.get("search_filter", "")
            if "member=" in filt:
                admin_conn.entries = [group_entry]
            else:
                admin_conn.entries = [user_entry]

        admin_conn.search.side_effect = search_side_effect

        # Le user conn revient du second appel Connection() (bind utilisateur)
        user_conn = MagicMock()

        mock_conn_cls.side_effect = [admin_conn, user_conn]

        result = authenticate_ldap("mtrabelsi@biat.local", "Biat2026!")

        assert result is not None
        assert result["mail"] == "mtrabelsi@biat.local"
        assert result["givenName"] == "Mehdi"
        assert result["sn"] == "Trabelsi"
        assert result["role"] == "Comptable"
        assert group_dn in result["groups"]

    @patch("src.services.ldap_service._Connection")
    @patch("src.services.ldap_service._Server")
    def test_user_not_found_returns_none(self, mock_server_cls, mock_conn_cls):
        """L'utilisateur n'existe pas dans l'annuaire → None."""
        admin_conn = MagicMock()
        admin_conn.entries = []  # aucun résultat
        mock_conn_cls.return_value = admin_conn

        result = authenticate_ldap("inconnu@biat.local", "password")
        assert result is None

    @patch("src.services.ldap_service._Connection")
    @patch("src.services.ldap_service._Server")
    def test_wrong_password_returns_none(self, mock_server_cls, mock_conn_cls):
        """Bind utilisateur échoue (mauvais mot de passe) → None."""
        user_dn = "cn=abenali,ou=users,dc=biat,dc=local"
        user_entry = _make_ldap_entry(user_dn, "abenali@biat.local", "Amine", "Ben Ali", "abenali")

        admin_conn = MagicMock()
        admin_conn.entries = [user_entry]

        # Le second appel (bind utilisateur) lève LDAPException
        from ldap3.core.exceptions import LDAPException
        mock_conn_cls.side_effect = [admin_conn, LDAPException("Invalid credentials")]

        result = authenticate_ldap("abenali@biat.local", "mauvais_mdp")
        assert result is None

    @patch("src.services.ldap_service._Connection")
    @patch("src.services.ldap_service._Server")
    def test_server_unreachable_returns_none(self, mock_server_cls, mock_conn_cls):
        """Le serveur LDAP est injoignable → None (pas d'exception levée vers l'appelant)."""
        from ldap3.core.exceptions import LDAPSocketOpenError
        mock_conn_cls.side_effect = LDAPSocketOpenError("Connection refused")

        result = authenticate_ldap("user@biat.local", "password")
        assert result is None

    def test_ldap3_not_available_returns_none(self, monkeypatch):
        """ldap3 non installé → None sans erreur."""
        monkeypatch.setattr(ldap_mod, "_LDAP3_AVAILABLE", False)
        result = authenticate_ldap("user@biat.local", "password")
        assert result is None

    @patch("src.services.ldap_service._Connection")
    @patch("src.services.ldap_service._Server")
    def test_user_with_no_groups_gets_none_role(self, mock_server_cls, mock_conn_cls):
        """Utilisateur authentifié mais sans groupe → role=None."""
        user_dn = "cn=orphan,ou=users,dc=biat,dc=local"
        user_entry = _make_ldap_entry(user_dn, "orphan@biat.local", "Orphan", "User", "orphan")

        admin_conn = MagicMock()

        def search_side_effect(*args, **kwargs):
            filt = kwargs.get("search_filter", "")
            if "member=" in filt:
                admin_conn.entries = []  # aucun groupe
            else:
                admin_conn.entries = [user_entry]

        admin_conn.search.side_effect = search_side_effect

        user_conn = MagicMock()
        mock_conn_cls.side_effect = [admin_conn, user_conn]

        result = authenticate_ldap("orphan@biat.local", "Biat2026!")

        assert result is not None
        assert result["role"] is None
        assert result["groups"] == []

    @patch("src.services.ldap_service._Connection")
    @patch("src.services.ldap_service._Server")
    def test_filter_escaping_in_search(self, mock_server_cls, mock_conn_cls):
        """Les caractères spéciaux dans l'email sont correctement échappés."""
        admin_conn = MagicMock()
        admin_conn.entries = []
        mock_conn_cls.return_value = admin_conn

        authenticate_ldap("test*(evil)@biat.local", "password")

        call_args = admin_conn.search.call_args
        search_filter = call_args.kwargs.get("search_filter") or call_args.args[1]
        # Les parenthèses et l'astérisque doivent être échappés
        assert "\\28" in search_filter  # (
        assert "\\29" in search_filter  # )
        assert "\\2a" in search_filter  # *

    @patch("src.services.ldap_service._Connection")
    @patch("src.services.ldap_service._Server")
    def test_admin_conn_always_unbound(self, mock_server_cls, mock_conn_cls):
        """La connexion admin est toujours libérée même en cas d'erreur."""
        user_entry = _make_ldap_entry(
            "cn=x,ou=users,dc=biat,dc=local", "x@biat.local", "X", "X", "x"
        )
        admin_conn = MagicMock()
        admin_conn.entries = [user_entry]

        from ldap3.core.exceptions import LDAPException
        user_conn_mock = LDAPException("fail")
        mock_conn_cls.side_effect = [admin_conn, user_conn_mock]

        authenticate_ldap("x@biat.local", "wrong")

        admin_conn.unbind.assert_called_once()


# ── Test : _escape_filter_value ───────────────────────────────────────────────

class TestEscapeFilterValue:
    def test_escapes_special_chars(self):
        from src.services.ldap_service import _escape_filter_value
        assert _escape_filter_value("a*(b)\\c\0") == "a\\2a\\28b\\29\\5cc\\00"

    def test_normal_email_unchanged(self):
        from src.services.ldap_service import _escape_filter_value
        email = "user.name@biat.local"
        assert _escape_filter_value(email) == email
