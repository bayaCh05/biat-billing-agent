"""Rebaseline ponctuel — HMAC des lignes audit_logs (SQLite) devenues
non-vérifiables suite à l'introduction d'un vrai AUDIT_HMAC_SECRET le
2026-09-07 (Option B, voir docs/audit_hmac_incident.md section 8).

Ne recalcule JAMAIS row_hash (le hash d'origine, calculé à l'écriture,
reste tel quel pour toujours — c'est la seule preuve d'intégrité honnête
pour la période antérieure à la rotation). Pour chaque ligne dont
verify_row_status() échoue ("failed"), calcule un nouveau rebaseline_hash
(même formule, secret actuel) et l'enregistre avec un horodatage et un
motif explicites.

Générations multiples : ce script a déjà tourné une première fois le
2026-07-15 (rotation JWT_SECRET du 2026-07-10, commit 2775772) — 569
lignes ont donc déjà un rebaseline_hash. Introduire un AUDIT_HMAC_SECRET
dédié le 2026-09-07 est une SECONDE rotation, qui invaliderait aussi ce
premier rebaseline_hash. Avant d'écraser un rebaseline_hash déjà présent,
ce script l'archive (avec rebaselined_at/rebaseline_reason) dans
prior_rebaseline_hash / prior_rebaselined_at / prior_rebaseline_reason —
jamais écrasés une fois posés — pour ne jamais perdre la trace du premier
rebaseline. Voir migration b3c4d5e6f7a8.

verify_row_status() (api/security/audit_integrity.py) traite ensuite ces
lignes comme "rebaselined", jamais comme "tampered" — mais si une ligne
rebaselined est modifiée après coup, rebaseline_hash cessera lui aussi de
correspondre : le contrôle d'intégrité reste actif pour l'avenir.

Idempotent — une ligne déjà vérifiable (row_hash OK) ou déjà rebaselined
sous le secret courant (rebaseline_hash déjà cohérent) est laissée intacte.

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
    "Rebaseline post-introduction d'un AUDIT_HMAC_SECRET dédié le 2026-09-07 "
    "(Option B) — voir docs/audit_hmac_incident.md section 8. row_hash "
    "d'origine conservé sans modification ; tout rebaseline_hash antérieur "
    "est archivé dans prior_rebaseline_hash avant d'être remplacé."
)


def main() -> None:
    dry_run = "--dry-run" in sys.argv

    engine = build_engine("sqlite:///./data/invoices.db")
    with Session(engine) as session:
        rows = session.execute(select(AuditLogORM)).scalars().all()

        to_rebaseline = [r for r in rows if verify_row_status(r) == "failed" and r.row_hash]
        already_rebaselined = sum(1 for r in rows if verify_row_status(r) == "rebaselined")
        already_valid = sum(1 for r in rows if verify_row_status(r) == "original")
        superseding = sum(1 for r in to_rebaseline if r.rebaseline_hash)

        print(f"Total lignes : {len(rows)}")
        print(f"  déjà valides (row_hash d'origine) : {already_valid}")
        print(f"  déjà rebaselined (secret actuel)   : {already_rebaselined}")
        print(f"  à rebaseliner maintenant           : {len(to_rebaseline)}")
        print(f"    dont avec un rebaseline_hash antérieur à archiver : {superseding}")

        if not to_rebaseline:
            print("Rien à faire.")
            return

        if dry_run:
            print("(--dry-run : aucune écriture effectuée)")
            return

        now = datetime.now(timezone.utc)
        for row in to_rebaseline:
            if row.rebaseline_hash and not row.prior_rebaseline_hash:
                row.prior_rebaseline_hash = row.rebaseline_hash
                row.prior_rebaselined_at = row.rebaselined_at
                row.prior_rebaseline_reason = row.rebaseline_reason
            row.rebaseline_hash = compute_row_hash(row)
            row.rebaselined_at = now
            row.rebaseline_reason = _REASON
        session.commit()

        print(
            f"✓ {len(to_rebaseline)} ligne(s) rebaselined "
            f"({superseding} avec archivage d'un rebaseline_hash antérieur). "
            "row_hash d'origine inchangé sur toutes."
        )


if __name__ == "__main__":
    main()
