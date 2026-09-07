"""Rebaseline ponctuel — HMAC des documents audit_logs (MongoDB) devenus
non-vérifiables suite à la rotation de AUDIT_HMAC_SECRET/JWT_SECRET du
2026-07-10 (commit 2775772). Voir docs/audit_hmac_incident.md section 7.

Miroir Mongo de scripts/rebaseline_audit_hmac.py (SQLite, 2026-07-15) — même
gap, découvert plus tard côté Mongo car ce store n'avait jusqu'ici aucun
mécanisme de rebaseline (AuditLogDocument n'avait pas les 3 champs).

Ne recalcule JAMAIS row_hash (le hash d'origine, calculé à l'écriture, reste
tel quel pour toujours). Pour chaque document dont verify_row_status_from_doc()
retourne "failed", calcule un rebaseline_hash séparé (même formule, secret
actuel) et l'enregistre avec un horodatage et un motif explicites.
verify_integrity_native() (src/storage/documents/service_bridge.py) traite
ensuite ces documents comme "rebaselined", jamais comme "tampered" — mais si
un document rebaselined est modifié après coup, rebaseline_hash cessera lui
aussi de correspondre : le contrôle d'intégrité reste actif pour l'avenir.

Écrit via pymongo brut (get_pymongo_collection() + update_one), jamais via
Document.save() — _id est stocké comme string simple sur audit_logs, pas
comme UUID Beanie natif (voir CLAUDE.md "Conventions").

Idempotent — un document déjà vérifiable (row_hash OK) ou déjà rebaselined
(rebaseline_hash déjà cohérent) est laissé intact.

Usage:
    python scripts/rebaseline_audit_hmac_mongo.py            # applique
    python scripts/rebaseline_audit_hmac_mongo.py --dry-run  # affiche seulement
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).parent.parent))

import api.auth  # noqa: F401  (charge .env, même convention que les autres scripts)

from api.security.audit_integrity import compute_row_hash_from_doc, verify_row_status_from_doc
from src.storage.sync_mongo_repository import _get_db

_REASON = (
    "Rebaseline Mongo post-rotation AUDIT_HMAC_SECRET/JWT_SECRET du 2026-07-10 "
    "(commit 2775772) — gap découvert et comblé le 2026-09-07, voir "
    "docs/audit_hmac_incident.md section 7. row_hash d'origine conservé sans "
    "modification."
)


def main() -> None:
    dry_run = "--dry-run" in sys.argv

    coll = _get_db()["audit_logs"]
    docs = list(coll.find({}))

    to_rebaseline = [d for d in docs if verify_row_status_from_doc(d) == "failed" and d.get("row_hash")]
    already_rebaselined = sum(1 for d in docs if verify_row_status_from_doc(d) == "rebaselined")
    already_valid = sum(1 for d in docs if verify_row_status_from_doc(d) == "original")

    print(f"Total documents : {len(docs)}")
    print(f"  déjà valides (row_hash d'origine) : {already_valid}")
    print(f"  déjà rebaselined                  : {already_rebaselined}")
    print(f"  à rebaseliner maintenant           : {len(to_rebaseline)}")

    if not to_rebaseline:
        print("Rien à faire.")
        return

    if dry_run:
        for d in to_rebaseline:
            print(f"  (dry-run) {d.get('created_at')}  {d.get('action')}  {d.get('_id')}")
        print("(--dry-run : aucune écriture effectuée)")
        return

    now = datetime.now(timezone.utc)
    for d in to_rebaseline:
        coll.update_one(
            {"_id": d["_id"]},
            {"$set": {
                "rebaseline_hash": compute_row_hash_from_doc(d),
                "rebaselined_at": now,
                "rebaseline_reason": _REASON,
            }},
        )

    print(f"✓ {len(to_rebaseline)} document(s) rebaselined. row_hash d'origine inchangé sur tous.")


if __name__ == "__main__":
    main()
