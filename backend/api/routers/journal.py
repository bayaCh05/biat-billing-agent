"""Journal entries endpoints."""
from __future__ import annotations

import csv
import io
import logging
from datetime import date

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from api.auth import require_role
from api.schemas import JournalEntryOut, JournalLineOut

router = APIRouter(prefix="/journal", tags=["journal"])

_log = logging.getLogger(__name__)

_COMPTABLE = Depends(require_role("Comptable"))


@router.get(
    "",
    response_model=list[JournalEntryOut],
    summary="Lister les écritures comptables",
    description=(
        "Retourne les écritures du journal PCE tunisien. "
        "Filtre par plage de dates (`start` et `end`) ou les `limit` dernières entrées (défaut 200). "
        "Chaque écriture respecte l'équilibre débit = crédit (double entrée). "
        "Comptes : 401 Fournisseurs, 4366 TVA déductible, 6xxx Charges, 2xxx Immobilisations."
    ),
    response_description="Liste d'écritures avec leurs lignes débit/crédit",
)
async def list_entries(
    start: date | None = None,
    end: date | None = None,
    limit: int = 200,
    _: dict = _COMPTABLE,
):
    from src.storage.documents.service_bridge import list_journal_entries_mongo

    entries = await list_journal_entries_mongo(start, end, limit)
    if entries is None:
        # Journal entries are written Mongo-only (see CLAUDE.md) — the old
        # SQLite fallback here could only ever serve permanently stale data.
        _log.warning("list_entries: MongoDB indisponible — retour d'une liste vide.")
        entries = []

    result = []
    for entry in entries:
        result.append(JournalEntryOut(
            id=str(entry.id),
            reference=entry.reference,
            date_ecriture=entry.date_ecriture,
            description=entry.description,
            source_invoice_id=str(entry.source_invoice_id) if entry.source_invoice_id else None,
            accounting_explanation=getattr(entry, "accounting_explanation", None),
            lines=[
                JournalLineOut(
                    compte=line.compte or '',
                    libelle=line.libelle or '',
                    debit=float(line.debit or 0),
                    credit=float(line.credit or 0),
                )
                for line in entry.lines
            ],
        ))
    return result


@router.get(
    "/export",
    summary="Exporter le journal en CSV",
    description="Exporte les écritures comptables en CSV — compatible ERP et Excel.",
    response_class=StreamingResponse,
)
async def export_journal_csv(
    start: date | None = Query(None),
    end: date | None = Query(None),
    limit: int = Query(5000),
    _: dict = _COMPTABLE,
):
    from src.storage.documents.service_bridge import list_journal_entries_mongo

    entries = await list_journal_entries_mongo(start, end, limit)
    if entries is None:
        # Journal entries are written Mongo-only (see CLAUDE.md) — the old
        # SQLite fallback here could only ever serve permanently stale data.
        _log.warning("export_journal_csv: MongoDB indisponible — export vide.")
        entries = []

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    writer.writerow([
        "reference", "date_ecriture", "description",
        "compte", "libelle_ligne", "debit", "credit", "source_facture_id",
    ])
    for entry in entries:
        for line in entry.lines:
            writer.writerow([
                entry.reference,
                entry.date_ecriture.isoformat(),
                entry.description,
                line.compte or "",
                line.libelle or "",
                round(float(line.debit or 0), 3),
                round(float(line.credit or 0), 3),
                str(entry.source_invoice_id) if entry.source_invoice_id else "",
            ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=journal.csv"},
    )
