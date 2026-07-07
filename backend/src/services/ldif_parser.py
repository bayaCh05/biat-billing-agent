"""Parseur de fichiers LDIF pour le mock LDAP de BIAT IT.

Utilisé uniquement en mode développement/test — ne remplace pas
un vrai serveur LDAP en production.

Limitations connues :
- Ne gère pas la continuation de ligne LDIF (ligne suivante commençant par espace)
- Ne gère pas les attributs binaires non-UTF-8
- Ne gère pas la syntaxe URL (attr:< file://...)
"""
from __future__ import annotations

import base64
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Attributs qui peuvent apparaître plusieurs fois dans une entrée
_MULTI_VALUE_ATTRS = {"objectclass"}

# Correspondance nom d'attribut LDIF → clé du dictionnaire retourné
_ATTR_MAP = {
    "dn":               "dn",
    "uid":              "uid",
    "cn":               "cn",
    "sn":               "sn",
    "givenname":        "given_name",
    "mail":             "mail",
    "userpassword":     "user_password",
    "departmentnumber": "department_number",
    "objectclass":      "object_class",
}


def _decode_base64(value: str) -> str:
    """Décode une valeur encodée en base64 (syntaxe LDIF avec '::').

    Retourne la valeur originale si le décodage échoue.
    """
    try:
        return base64.b64decode(value.strip()).decode("utf-8")
    except Exception:
        logger.debug("ldif_parser: échec décodage base64 pour la valeur '%s'", value[:30])
        return value.strip()


def _parse_entry(lines: list[str]) -> dict:
    """Parse un bloc LDIF (liste de lignes) en dictionnaire.

    Retourne un dict avec les clés définies dans _ATTR_MAP.
    Les attributs multi-valeurs (objectClass) sont des listes.
    """
    entry: dict = {}

    for line in lines:
        # Ignorer les commentaires LDIF
        if line.startswith("#"):
            continue

        # Séparateur base64 '::' en priorité, puis séparateur normal ':'
        if "::" in line:
            attr_raw, _, value_raw = line.partition("::")
            value = _decode_base64(value_raw)
        elif ":" in line:
            attr_raw, _, value_raw = line.partition(":")
            value = value_raw.strip()
        else:
            continue

        attr = attr_raw.strip().lower()
        mapped_key = _ATTR_MAP.get(attr)
        if mapped_key is None:
            # Attribut non reconnu — on l'ignore silencieusement
            continue

        if attr in _MULTI_VALUE_ATTRS:
            # Accumuler en liste
            entry.setdefault(mapped_key, []).append(value)
        else:
            entry[mapped_key] = value

    return entry


def parse_ldif(filepath: str) -> list[dict]:
    """Lit un fichier LDIF et retourne la liste des entrées sous forme de dicts.

    Chaque entrée correspond à un bloc séparé par une ligne vide.
    Les entrées sans attribut 'uid' sont ignorées (ex: entrées OU/DC racine).

    Args:
        filepath: Chemin absolu ou relatif vers le fichier .ldif

    Returns:
        Liste de dicts, un par entrée utilisateur valide.

    Raises:
        FileNotFoundError: Si le fichier n'existe pas.
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Fichier LDIF introuvable : {filepath}")

    entries: list[dict] = []
    current_block: list[str] = []

    with path.open(encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.rstrip("\n\r")

            if line == "":
                # Fin de bloc — traiter l'entrée accumulée
                if current_block:
                    entry = _parse_entry(current_block)
                    if "uid" in entry:
                        entries.append(entry)
                    current_block = []
            else:
                current_block.append(line)

    # Traiter le dernier bloc si le fichier ne se termine pas par une ligne vide
    if current_block:
        entry = _parse_entry(current_block)
        if "uid" in entry:
            entries.append(entry)

    logger.info("ldif_parser: %d entrée(s) chargée(s) depuis %s", len(entries), path.name)
    return entries
