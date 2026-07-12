"""Seed demo users into MongoDB with bcrypt-hashed passwords.

Usage:
    python scripts/seed_users.py            # seed all 4 demo users
    python scripts/seed_users.py --dry-run  # show what would happen, no writes

Reads passwords from env vars (falls back to dev defaults):
    DEMO_COMPTABLE_PASSWORD   default: biat2026
    DEMO_CHEF_PASSWORD        default: biat2026
    DEMO_DIRECTION_PASSWORD   default: biat2026
    DEMO_ADMIN_PASSWORD       default: admin2026

Idempotent — skips any user whose email already exists.
"""
from __future__ import annotations

import asyncio
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "backend"))
sys.path.insert(0, _ROOT)

from api.auth import hash_password
from src.storage.mongodb import close_mongodb, init_beanie

DRY_RUN = "--dry-run" in sys.argv

DEMO_USERS = [
    {
        "email":      "comptable@biat-it.tn",
        "password":   os.getenv("DEMO_COMPTABLE_PASSWORD", "biat2026"),
        "role":       "Comptable",
        "nom":        "Compte",
        "prenom":     "Demo",
        "departement": "Comptabilité",
    },
    {
        "email":      "chef@biat-it.tn",
        "password":   os.getenv("DEMO_CHEF_PASSWORD", "biat2026"),
        "role":       "Chef de Projet",
        "nom":        "Chef",
        "prenom":     "Demo",
        "departement": "DSI",
    },
    {
        "email":      "directeur@biat-it.tn",
        "password":   os.getenv("DEMO_DIRECTION_PASSWORD", "biat2026"),
        "role":       "Direction",
        "nom":        "Directeur",
        "prenom":     "Demo",
        "departement": "Direction",
    },
    {
        "email":      "admin@biat-it.tn",
        "password":   os.getenv("DEMO_ADMIN_PASSWORD", "admin2026"),
        "role":       "Admin",
        "nom":        "Admin",
        "prenom":     "Système",
        "departement": "IT",
    },
]


async def main() -> None:
    if not await init_beanie():
        print("MONGODB_URI non défini ou connexion impossible — abandon.")
        sys.exit(1)

    from src.storage.documents.service_bridge import create_user_native, get_user_by_email_native

    inserted = 0
    skipped = 0

    for u in DEMO_USERS:
        existing = await get_user_by_email_native(u["email"])
        if existing:
            print(f"  SKIP  {u['email']} (already exists, role={existing.role})")
            skipped += 1
            continue

        if DRY_RUN:
            print(f"  DRY   {u['email']} → role={u['role']}")
            continue

        created = await create_user_native(
            nom=u["nom"], prenom=u["prenom"], email=u["email"],
            hashed_password=hash_password(u["password"]),
            role=u["role"], departement=u["departement"],
            is_first_login=False,
        )
        if created is None:
            print(f"  SKIP  {u['email']} (already exists — race)")
            skipped += 1
        else:
            print(f"  INSERT {u['email']} → role={u['role']}")
            inserted += 1

    await close_mongodb()

    print()
    if DRY_RUN:
        print("Dry run — no changes written.")
    else:
        print(f"Done: {inserted} inserted, {skipped} skipped.")


if __name__ == "__main__":
    asyncio.run(main())
