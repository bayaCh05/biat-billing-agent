"""Seed demo users into the users table with bcrypt-hashed passwords.

Usage:
    python scripts/seed_users.py            # seed all 4 demo users
    python scripts/seed_users.py --dry-run  # show what would happen, no writes

Reads passwords from env vars (falls back to dev defaults):
    DEMO_COMPTABLE_PASSWORD   default: biat2026
    DEMO_CHEF_PASSWORD        default: biat2026
    DEMO_DIRECTION_PASSWORD   default: biat2026
    DEMO_ADMIN_PASSWORD       default: admin2026

Idempotent — skips any user whose email is already in the DB.
"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "backend"))
sys.path.insert(0, _ROOT)
os.environ.setdefault("DATABASE_URL", "sqlite:///./data/invoices.db")

from sqlalchemy import select

from api.auth import hash_password
from src.storage.db import build_engine, build_session_factory, init_db
from src.storage.orm_models_users import UserORM

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


def main() -> None:
    db_url = os.getenv("DATABASE_URL", "sqlite:///./data/invoices.db")
    engine = build_engine(db_url)
    init_db(engine)
    sf = build_session_factory(engine)

    inserted = 0
    skipped = 0

    with sf() as session:
        for u in DEMO_USERS:
            existing = session.execute(
                select(UserORM).where(UserORM.email == u["email"])
            ).scalar_one_or_none()

            if existing:
                print(f"  SKIP  {u['email']} (already exists, role={existing.role})")
                skipped += 1
                continue

            if DRY_RUN:
                print(f"  DRY   {u['email']} → role={u['role']}")
                continue

            user = UserORM(
                nom=u["nom"],
                prenom=u["prenom"],
                email=u["email"],
                hashed_password=hash_password(u["password"]),
                role=u["role"],
                departement=u["departement"],
                is_first_login=False,
                is_active=True,
            )
            session.add(user)
            print(f"  INSERT {u['email']} → role={u['role']}")
            inserted += 1

        if not DRY_RUN:
            session.commit()

    print()
    if DRY_RUN:
        print("Dry run — no changes written.")
    else:
        print(f"Done: {inserted} inserted, {skipped} skipped.")


if __name__ == "__main__":
    main()
