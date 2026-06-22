"""Journal entries endpoints."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.deps import get_session
from api.schemas import JournalEntryOut, JournalLineOut
from src.accounting.journal_store import JournalRepository

router = APIRouter(prefix="/journal", tags=["journal"])


@router.get("", response_model=list[JournalEntryOut])
def list_entries(
    start: date | None = None,
    end: date | None = None,
    limit: int = 200,
    session: Session = Depends(get_session),
):
    repo = JournalRepository(session)
    if start and end:
        entries = repo.get_by_date_range(start, end)
    else:
        entries = repo.list_entries(limit=limit)

    result = []
    for entry in entries:
        result.append(JournalEntryOut(
            id=str(entry.id),
            reference=entry.reference,
            date_ecriture=entry.date_ecriture,
            description=entry.description,
            source_invoice_id=str(entry.source_invoice_id) if entry.source_invoice_id else None,
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
