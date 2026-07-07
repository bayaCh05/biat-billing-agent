"""Tests unitaires pour ldif_parser et mock_ldap_auth.

Toutes les dépendances externes sont évitées : les fichiers LDIF
sont créés en mémoire via tmp_path (fixture pytest).
"""
from __future__ import annotations

import pytest
from pathlib import Path

from src.services.ldif_parser import parse_ldif
from src.services.mock_ldap_auth import MockLDAPAuth, _map_role


# ---------------------------------------------------------------------------
# Helpers — contenu LDIF inline pour les tests
# ---------------------------------------------------------------------------

_LDIF_PLAIN = """\
dn: uid=jdoe,ou=users,dc=biat,dc=local
objectClass: inetOrgPerson
objectClass: organizationalPerson
cn: Jean Doe
sn: Doe
givenName: Jean
uid: jdoe
mail: jdoe@biat.local
userPassword: secret123
departmentNumber: 300
"""

# cn encodé en base64 : "Karim Bouaziz"
_LDIF_BASE64 = """\
dn: uid=kbouaziz,ou=users,dc=biat,dc=local
objectClass: inetOrgPerson
cn:: S2FyaW0gQm91YXppeg==
sn: Bouaziz
givenName: Karim
uid: kbouaziz
mail: kbouaziz@biat.local
userPassword: pass456
departmentNumber: 100
"""

# Entrée OU sans uid — doit être ignorée
_LDIF_NO_UID = """\
dn: ou=users,dc=biat,dc=local
objectClass: organizationalUnit
ou: users

dn: uid=valid,ou=users,dc=biat,dc=local
objectClass: inetOrgPerson
cn: Valid User
uid: valid
mail: valid@biat.local
userPassword: pw
departmentNumber: 200
"""

# Deux utilisateurs dans un même fichier pour tester le mapping des rôles
_LDIF_MULTI = """\
dn: uid=direction,ou=users,dc=biat,dc=local
objectClass: inetOrgPerson
cn: Dir User
uid: direction
mail: dir@biat.local
userPassword: pw
departmentNumber: 100

dn: uid=chef,ou=users,dc=biat,dc=local
objectClass: inetOrgPerson
cn: Chef User
uid: chef
mail: chef@biat.local
userPassword: pw
departmentNumber: 200

dn: uid=comptable,ou=users,dc=biat,dc=local
objectClass: inetOrgPerson
cn: Compta User
uid: comptable
mail: compta@biat.local
userPassword: pw
departmentNumber: 300

dn: uid=adminuser,ou=users,dc=biat,dc=local
objectClass: inetOrgPerson
cn: Admin User
uid: adminuser
mail: admin@biat.local
userPassword: pw
departmentNumber: 900

dn: uid=inconnu_dept,ou=users,dc=biat,dc=local
objectClass: inetOrgPerson
cn: Inconnu Dept
uid: inconnu_dept
mail: inc@biat.local
userPassword: pw
departmentNumber: 999
"""


def _write_ldif(tmp_path: Path, filename: str, content: str) -> Path:
    """Écrit le contenu LDIF dans un fichier temporaire et retourne son chemin."""
    p = tmp_path / filename
    p.write_text(content, encoding="utf-8")
    return p


# ===========================================================================
# Tests — ldif_parser
# ===========================================================================

class TestParseLdif:

    def test_parse_plain(self, tmp_path):
        """Parse un LDIF sans base64 et vérifie les champs principaux."""
        p = _write_ldif(tmp_path, "plain.ldif", _LDIF_PLAIN)
        entries = parse_ldif(str(p))

        assert len(entries) == 1
        e = entries[0]
        assert e["uid"] == "jdoe"
        assert e["cn"] == "Jean Doe"
        assert e["sn"] == "Doe"
        assert e["given_name"] == "Jean"
        assert e["mail"] == "jdoe@biat.local"
        assert e["user_password"] == "secret123"
        assert e["department_number"] == "300"

    def test_parse_base64(self, tmp_path):
        """Les valeurs encodées en base64 (attr::) doivent être décodées."""
        p = _write_ldif(tmp_path, "base64.ldif", _LDIF_BASE64)
        entries = parse_ldif(str(p))

        assert len(entries) == 1
        # "S2FyaW0gQm91YXppeg==" → "Karim Bouaziz"
        assert entries[0]["cn"] == "Karim Bouaziz"

    def test_parse_objectclass_is_list(self, tmp_path):
        """objectClass doit être une liste même s'il y a plusieurs occurrences."""
        p = _write_ldif(tmp_path, "plain.ldif", _LDIF_PLAIN)
        entries = parse_ldif(str(p))

        oc = entries[0]["object_class"]
        assert isinstance(oc, list)
        assert "inetOrgPerson" in oc
        assert "organizationalPerson" in oc

    def test_parse_ignores_entries_without_uid(self, tmp_path):
        """Les entrées sans attribut uid (ex: OU racine) doivent être ignorées."""
        p = _write_ldif(tmp_path, "mixed.ldif", _LDIF_NO_UID)
        entries = parse_ldif(str(p))

        # Seule l'entrée 'valid' doit être retournée
        assert len(entries) == 1
        assert entries[0]["uid"] == "valid"

    def test_parse_file_not_found(self, tmp_path):
        """parse_ldif doit lever FileNotFoundError si le fichier est absent."""
        with pytest.raises(FileNotFoundError):
            parse_ldif(str(tmp_path / "inexistant.ldif"))

    def test_parse_empty_file(self, tmp_path):
        """Un fichier vide doit retourner une liste vide sans erreur."""
        p = _write_ldif(tmp_path, "empty.ldif", "")
        entries = parse_ldif(str(p))
        assert entries == []


# ===========================================================================
# Tests — mock_ldap_auth
# ===========================================================================

@pytest.fixture(autouse=True)
def reset_singleton():
    """Réinitialise le singleton MockLDAPAuth avant chaque test."""
    MockLDAPAuth.reset()
    yield
    MockLDAPAuth.reset()


class TestMockLDAPAuth:

    def test_auth_success(self, tmp_path):
        """Authentification réussie → dict avec les bons champs."""
        _write_ldif(tmp_path, "users.ldif", _LDIF_PLAIN)
        auth = MockLDAPAuth.get(ldif_dir=tmp_path)

        result = auth.authenticate("jdoe", "secret123")

        assert result is not None
        assert result["uid"] == "jdoe"
        assert result["cn"] == "Jean Doe"
        assert result["mail"] == "jdoe@biat.local"
        assert result["role"] == "Comptable"
        # Le mot de passe ne doit jamais être retourné
        assert "user_password" not in result
        assert "password" not in result

    def test_auth_wrong_password(self, tmp_path):
        """Mauvais mot de passe → None."""
        _write_ldif(tmp_path, "users.ldif", _LDIF_PLAIN)
        auth = MockLDAPAuth.get(ldif_dir=tmp_path)

        assert auth.authenticate("jdoe", "mauvais_mdp") is None

    def test_auth_unknown_uid(self, tmp_path):
        """UID inexistant → None."""
        _write_ldif(tmp_path, "users.ldif", _LDIF_PLAIN)
        auth = MockLDAPAuth.get(ldif_dir=tmp_path)

        assert auth.authenticate("inexistant", "secret123") is None

    def test_auth_empty_credentials(self, tmp_path):
        """uid ou password vide → None sans exception."""
        _write_ldif(tmp_path, "users.ldif", _LDIF_PLAIN)
        auth = MockLDAPAuth.get(ldif_dir=tmp_path)

        assert auth.authenticate("", "secret123") is None
        assert auth.authenticate("jdoe", "") is None
        assert auth.authenticate("", "") is None

    def test_auth_role_mapping(self, tmp_path):
        """Chaque departmentNumber doit produire le bon rôle applicatif."""
        _write_ldif(tmp_path, "users.ldif", _LDIF_MULTI)
        auth = MockLDAPAuth.get(ldif_dir=tmp_path)

        assert auth.authenticate("direction",  "pw")["role"] == "Direction"
        assert auth.authenticate("chef",       "pw")["role"] == "Chef_Projet"
        assert auth.authenticate("comptable",  "pw")["role"] == "Comptable"
        assert auth.authenticate("adminuser",  "pw")["role"] == "Admin"
        # departmentNumber inconnu → rôle par défaut
        assert auth.authenticate("inconnu_dept", "pw")["role"] == "Comptable"

    def test_auth_base64_cn(self, tmp_path):
        """Authentification avec une entrée dont le cn est encodé en base64."""
        _write_ldif(tmp_path, "users.ldif", _LDIF_BASE64)
        auth = MockLDAPAuth.get(ldif_dir=tmp_path)

        result = auth.authenticate("kbouaziz", "pass456")
        assert result is not None
        assert result["cn"] == "Karim Bouaziz"
        assert result["role"] == "Direction"

    def test_loads_multiple_ldif_files(self, tmp_path):
        """Tous les fichiers .ldif du dossier doivent être chargés."""
        _write_ldif(tmp_path, "a_users.ldif", _LDIF_PLAIN)
        _write_ldif(tmp_path, "b_users.ldif", _LDIF_BASE64)
        auth = MockLDAPAuth.get(ldif_dir=tmp_path)

        assert auth.user_count == 2
        assert auth.authenticate("jdoe",    "secret123") is not None
        assert auth.authenticate("kbouaziz", "pass456")  is not None

    def test_missing_ldif_dir(self, tmp_path):
        """Un dossier LDIF inexistant ne doit pas lever d'exception — index vide."""
        auth = MockLDAPAuth.get(ldif_dir=tmp_path / "inexistant")
        assert auth.user_count == 0
        assert auth.authenticate("anyone", "pw") is None


# ===========================================================================
# Tests — fonction _map_role (unité isolée)
# ===========================================================================

class TestMapRole:

    def test_known_departments(self):
        assert _map_role("100") == "Direction"
        assert _map_role("200") == "Chef_Projet"
        assert _map_role("300") == "Comptable"
        assert _map_role("900") == "Admin"

    def test_unknown_department_returns_default(self):
        assert _map_role("999") == "Comptable"
        assert _map_role("0")   == "Comptable"

    def test_none_returns_default(self):
        assert _map_role(None) == "Comptable"

    def test_whitespace_stripped(self):
        assert _map_role("  100  ") == "Direction"
