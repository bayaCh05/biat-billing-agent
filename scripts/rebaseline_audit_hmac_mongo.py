"""Rebaseline ponctuel — HMAC des documents audit_logs (MongoDB) devenus
non-vérifiables suite à l'introduction d'un vrai AUDIT_HMAC_SECRET le
2026-09-07 (Option B, voir docs/audit_hmac_incident.md section 8).

Miroir Mongo de scripts/rebaseline_audit_hmac.py (SQLite) — même logique,
mêmes garanties, y compris l'archivage de génération (voir ce fichier pour
le détail : ce script a d'abord tourné le 2026-09-07 juste après l'ajout
du mécanisme de rebaseline côté Mongo, quand il n'y avait encore rien à
rebaseliner — voir section 7 — puis une seconde fois le même jour une fois
AUDIT_HMAC_SECRET introduit, ce qui invalide tous les documents jusque-là
"original").

Ne recalcule JAMAIS row_hash. Avant d'écraser un rebaseline_hash déjà
présent sur un document, l'archive dans prior_rebaseline_hash /
prior_rebaselined_at / prior_rebaseline_reason (jamais réécrasés une fois
posés), pour ne jamais perdre la trace d'un rebaseline précédent.

Écrit via pymongo brut (get_pymongo_collection() + update_one), jamais via
Document.save() — _id est stocké comme string simple sur audit_logs, pas
comme UUID Beanie natif (voir CLAUDE.md "Conventions").

Idempotent — un document déjà vérifiable (row_hash OK) ou déjà rebaselined
sous le secret courant (rebaseline_hash déjà cohérent) est laissé intact.

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
    "Rebaseline Mongo post-introduction d'un AUDIT_HMAC_SECRET dédié le "
    "2026-09-07 (Option B) — voir docs/audit_hmac_incident.md section 8. "
    "row_hash d'origine conservé sans modification ; tout rebaseline_hash "
    "antérieur est archivé dans prior_rebaseline_hash avant d'être remplacé."
)


def main() -> None:
    dry_run = "--dry-run" in sys.argv

    coll = _get_db()["audit_logs"]
    docs = list(coll.find({}))

    to_rebaseline = [d for d in docs if verify_row_status_from_doc(d) == "failed" and d.get("row_hash")]
    already_rebaselined = sum(1 for d in docs if verify_row_status_from_doc(d) == "rebaselined")
    already_valid = sum(1 for d in docs if verify_row_status_from_doc(d) == "original")
    superseding = sum(1 for d in to_rebaseline if d.get("rebaseline_hash"))

    print(f"Total documents : {len(docs)}")
    print(f"  déjà valides (row_hash d'origine) : {already_valid}")
    print(f"  déjà rebaselined (secret actuel)   : {already_rebaselined}")
    print(f"  à rebaseliner maintenant           : {len(to_rebaseline)}")
    print(f"    dont avec un rebaseline_hash antérieur à archiver : {superseding}")

    if not to_rebaseline:
        print("Rien à faire.")
        return

    if dry_run:
        for d in to_rebaseline:
            tag = " (archivage)" if d.get("rebaseline_hash") else ""
            print(f"  (dry-run) {d.get('created_at')}  {d.get('action')}  {d.get('_id')}{tag}")
        print("(--dry-run : aucune écriture effectuée)")
        return

    now = datetime.now(timezone.utc)
    for d in to_rebaseline:
        update = {
            "rebaseline_hash": compute_row_hash_from_doc(d),
            "rebaselined_at": now,
            "rebaseline_reason": _REASON,
        }
        if d.get("rebaseline_hash") and not d.get("prior_rebaseline_hash"):
            update["prior_rebaseline_hash"] = d["rebaseline_hash"]
            update["prior_rebaselined_at"] = d.get("rebaselined_at")
            update["prior_rebaseline_reason"] = d.get("rebaseline_reason")
        coll.update_one({"_id": d["_id"]}, {"$set": update})

    print(
        f"✓ {len(to_rebaseline)} document(s) rebaselined "
        f"({superseding} avec archivage d'un rebaseline_hash antérieur). "
        "row_hash d'origine inchangé sur tous."
    )


if __name__ == "__main__":
    main()
