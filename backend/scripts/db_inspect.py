"""CLI d'inspection MongoDB — lecture seule, aucune écriture possible.

Usage :
    # Lister les collections + nombre de documents par collection
    MONGODB_URI=mongodb://localhost:27017 python backend/scripts/db_inspect.py list

    # find() filtré basique
    python backend/scripts/db_inspect.py find users --filter '{"email": "admin@biat.local"}'
    python backend/scripts/db_inspect.py find invoices --filter '{"status": "FLAGGED"}' --limit 5
    python backend/scripts/db_inspect.py find audit_logs --sort -created_at --limit 3

Sécurité :
    - Lecture seule : aucune commande d'écriture n'est exposée.
    - DATA RESIDENCY : avertit si MONGODB_URI ne pointe pas vers une instance
      locale (voir CLAUDE.md — aucune donnée de facturation réelle sur un
      cluster distant/cloud).

Variables d'environnement :
    MONGODB_URI  — URI de connexion (défaut : mongodb://localhost:27017)
    MONGODB_DB   — Nom de la base (défaut : biat_billing)
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from bson import json_util
from pymongo import ASCENDING, DESCENDING, MongoClient

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_DB = os.getenv("MONGODB_DB", "biat_billing")

_LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")


def _warn_if_not_local(uri: str) -> None:
    if not any(h in uri for h in _LOCAL_HOSTS):
        print(
            f"  ⚠  MONGODB_URI ne semble pas pointer vers une instance locale : {uri}\n"
            "     DATA RESIDENCY : ne pas inspecter de données de facturation réelles "
            "sur un cluster distant/cloud (voir CLAUDE.md).",
            file=sys.stderr,
        )


def _connect() -> MongoClient:
    client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5_000)
    client.admin.command("ping")  # échoue vite si Mongo est injoignable
    return client


def cmd_list(args: argparse.Namespace) -> None:
    client = _connect()
    db = client[MONGODB_DB]
    names = sorted(db.list_collection_names())

    if not names:
        print(f"Aucune collection dans la base '{MONGODB_DB}'.")
        return

    print(f"┌─ Base '{MONGODB_DB}' — {len(names)} collection(s) ──────────────────")
    total = 0
    for name in names:
        count = db[name].count_documents({})
        total += count
        print(f"  {name:<32} {count:>8}")
    print(f"├─ TOTAL {total:>39}")
    client.close()


def cmd_find(args: argparse.Namespace) -> None:
    client = _connect()
    db = client[MONGODB_DB]

    if args.collection not in db.list_collection_names():
        print(f"Collection '{args.collection}' introuvable dans '{MONGODB_DB}'.", file=sys.stderr)
        client.close()
        sys.exit(1)

    try:
        query = json.loads(args.filter) if args.filter else {}
    except json.JSONDecodeError as exc:
        print(f"--filter n'est pas un JSON valide : {exc}", file=sys.stderr)
        client.close()
        sys.exit(1)

    projection = None
    if args.fields:
        projection = {f.strip(): 1 for f in args.fields.split(",") if f.strip()}

    cursor = db[args.collection].find(query, projection)

    if args.sort:
        field = args.sort.lstrip("-")
        direction = DESCENDING if args.sort.startswith("-") else ASCENDING
        cursor = cursor.sort(field, direction)

    cursor = cursor.limit(min(args.limit, 200))

    docs = list(cursor)
    if not docs:
        print("(aucun document trouvé)")
    else:
        print(json_util.dumps(docs, indent=2, ensure_ascii=False))
    print(f"\n{len(docs)} document(s) affiché(s) (limit={args.limit}).")
    client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspection MongoDB en lecture seule")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="Liste les collections et compte les documents")
    p_list.set_defaults(func=cmd_list)

    p_find = sub.add_parser("find", help="find() filtré basique sur une collection")
    p_find.add_argument("collection", help="Nom de la collection")
    p_find.add_argument("--filter", help='Filtre JSON, ex: \'{"status": "FLAGGED"}\'')
    p_find.add_argument("--limit", type=int, default=10, help="Nombre max de documents (défaut 10, max 200)")
    p_find.add_argument("--fields", help="Champs à projeter, séparés par des virgules")
    p_find.add_argument("--sort", help="Champ de tri, préfixer par '-' pour décroissant, ex: -created_at")
    p_find.set_defaults(func=cmd_find)

    args = parser.parse_args()
    _warn_if_not_local(MONGODB_URI)
    try:
        args.func(args)
    except Exception as exc:
        print(f"Connexion MongoDB impossible ({MONGODB_URI}) : {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
