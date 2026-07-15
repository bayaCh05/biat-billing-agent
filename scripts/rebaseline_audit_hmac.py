"""Rebaseline ponctuel — HMAC des lignes audit_logs (SQLite) devenues
non-vérifiables suite à la rotation de AUDIT_HMAC_SECRET/JWT_SECRET du
2026-07-10 (commit 2775772). Voir docs/audit_hmac_incident.md.

Ne recalcule JAMAIS row_hash (le hash d'origine, calculé à l'écriture,
reste tel quel pour toujours — c'est la seule preuve d'intégrité honnête
pour la période antérieure à la rotation). Pour chaque ligne dont
verify_row_hash() échoue, calcule un rebaseline_hash séparé (même formule,
secret actuel) et l'enregistre avec un horodatage et un motif explicites.
verify_row_status() (api/security/audit_integrity.py) traite ensuite ces
lignes comme "rebaselined", jamais comme "tampered" — mais si une ligne
rebaselined est modifiée après coup, rebaseline_hash cessera lui aussi de
correspondre : le contrôle d'intégrité reste actif pour l'avenir.

Idempotent — une ligne déjà vérifiable (row_hash OK) ou déjà rebaselined
(rebaseline_hash déjà cohérent) est laissée intacte.

Usage:
    python scripts/rebaseline_audit_hmac.py            # applique
    python scripts/rebaseline_audit_hmac.py --dry-run   # affiche seulement
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).parent.parent))

import api.auth  # noqa: F401  (charge .env, même convention que les autres scripts)

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.security.audit_integrity import compute_row_hash, verify_row_status
from src.storage.db import build_engine
from src.storage.orm_models_audit import AuditLogORM

_REASON = (
    "Rebaseline post-rotation AUDIT_HMAC_SECRET/JWT_SECRET du 2026-07-10 "
    "(commit 2775772) — voir docs/audit_hmac_incident.md. row_hash d'origine "
    "conservé sans modification."
)


def main() -> None:
    dry_run = "--dry-run" in sys.argv

    engine = build_engine("sqlite:///./data/invoices.db")
    with Session(engine) as session:
        rows = session.execute(select(AuditLogORM)).scalars().all()

        to_rebaseline = [r for r in rows if verify_row_status(r) == "failed" and r.row_hash]
        already_rebaselined = sum(1 for r in rows if verify_row_status(r) == "rebaselined")
        already_valid = sum(1 for r in rows if verify_row_status(r) == "original")

        print(f"Total lignes : {len(rows)}")
        print(f"  déjà valides (row_hash d'origine) : {already_valid}")
        print(f"  déjà rebaselined                  : {already_rebaselined}")
        print(f"  à rebaseliner maintenant           : {len(to_rebaseline)}")

        if not to_rebaseline:
            print("Rien à faire.")
            return

        if dry_run:
            print("(--dry-run : aucune écriture effectuée)")
            return

        now = datetime.now(timezone.utc)
        for row in to_rebaseline:
            row.rebaseline_hash = compute_row_hash(row)
            row.rebaselined_at = now
            row.rebaseline_reason = _REASON
        session.commit()

        print(f"✓ {len(to_rebaseline)} ligne(s) rebaselined. row_hash d'origine inchangé sur toutes.")


if __name__ == "__main__":
    main()
