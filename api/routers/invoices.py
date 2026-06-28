"""Invoice endpoints — upload + pipeline, list, detail."""
from __future__ import annotations

import tempfile
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from api.deps import get_session, get_components
from api.schemas import InvoiceOut, InvoiceSummary, ActionResultOut
from src.agent.pipeline import extract, classify, validate, export_file, post_journal
from src.models.enums import InvoiceStatus
from src.models.invoice import InvoiceRecord
from src.storage.repository import InvoiceRepository
from src.utils.file_utils import sha256
from api.limiter import limiter, limit

router = APIRouter(prefix="/invoices", tags=["invoices"])


@router.post(
    "/upload",
    response_model=InvoiceOut,
    summary="Soumettre une facture fournisseur",
    description=(
        "Upload un fichier PDF ou image d'une facture fournisseur et déclenche le pipeline complet : "
        "extraction OCR+LLM → classification catalogue PCE → validation (montants, TVA, doublons) → export. "
        "Chaque champ extrait est accompagné d'un score de confiance (0–1). "
        "En mode `live=false`, un mock LLM est utilisé (tests et démo uniquement). "
        "Limité à 10 uploads par minute."
    ),
    response_description="InvoiceRecord complet avec statut final du pipeline et scores de confiance",
    responses={429: {"description": "Trop de tentatives — réessayer dans 60 secondes"}},
)
@limiter.limit(limit("10/minute"))
async def upload_invoice(
    request: Request,
    file: UploadFile = File(...),
    live: bool = Form(True),
    session: Session = Depends(get_session),
):
    suffix = Path(file.filename or "invoice.pdf").suffix or ".pdf"
    content = await file.read()

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    repo = InvoiceRepository(session)

    if live:
        components = get_components()
    else:
        from src.extraction.llm_extractor import LLMBackendBase
        import json

        _MOCK = json.dumps({
            "issuer_name":    {"value": "TECHNOVA SOLUTIONS SARL", "confidence": 0.95, "source": None},
            "issuer_tax_id":  {"value": "1472583D/A/M/000",        "confidence": 0.92, "source": None},
            "recipient_name": {"value": "BIAT IT",                 "confidence": 0.95, "source": None},
            "recipient_tax_id": {"value": "0000217V/A/M/000",      "confidence": 0.90, "source": None},
            "invoice_number": {"value": "FAC-2026-0147",           "confidence": 0.98, "source": None},
            "invoice_date":   {"value": "2026-06-15",              "confidence": 0.95, "source": None},
            "due_date":       {"value": "2026-07-15",              "confidence": 0.90, "source": None},
            "amount_ht":      {"value": 14500.0, "confidence": 0.95, "source": None},
            "tva_rate":       {"value": 19.0,    "confidence": 0.99, "source": None},
            "tva_amount":     {"value": 2755.0,  "confidence": 0.95, "source": None},
            "amount_ttc":     {"value": 17255.0, "confidence": 0.95, "source": None},
            "currency":       {"value": "TND",   "confidence": 1.0,  "source": None},
            "line_items": [],
        })

        class _Mock(LLMBackendBase):
            def complete(self, system, user): return _MOCK

        from src.agent.config_loader import build_pipeline_components
        components, _ = build_pipeline_components(llm_backend=_Mock())

    try:
        file_hash = sha256(tmp_path)
        existing = repo.get_by_hash(file_hash)

        if existing:
            existing.status = InvoiceStatus.RECEIVED
            existing.retry_count = 0
            existing.last_error = None
            existing.flags = []
            existing.raw_file_path = tmp_path
            repo.save(existing)
            invoice = existing
        else:
            invoice = InvoiceRecord(
                file_hash=file_hash,
                raw_file_path=tmp_path,
                status=InvoiceStatus.RECEIVED,
            )
            repo.save(invoice)

        invoice = extract(invoice, components)
        if invoice.status not in {InvoiceStatus.EXTRACTION_FAILED, InvoiceStatus.ERROR}:
            invoice = classify(invoice, components)
            invoice = validate(invoice, components)
            if invoice.status == InvoiceStatus.VALIDATED:
                invoice = export_file(invoice, components)
            if invoice.status == InvoiceStatus.EXPORTED:
                invoice = post_journal(invoice, components)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
        components.close()

    return InvoiceOut.from_record(invoice)


@router.get(
    "",
    response_model=list[InvoiceSummary],
    summary="Lister les factures",
    description=(
        "Retourne la liste des factures fournisseurs, triées par date de réception décroissante. "
        "Filtrage optionnel par statut (RECEIVED, EXTRACTED, CLASSIFIED, VALIDATED, FLAGGED, EXPORTED, PAID, etc.). "
        "Limité à `limit` entrées (défaut 100)."
    ),
    response_description="Liste de résumés de factures avec statut et montants",
)
def list_invoices(
    status: str | None = None,
    limit: int = 100,
    session: Session = Depends(get_session),
):
    repo = InvoiceRepository(session)
    invoices = repo.list_all(limit=limit)
    if status:
        try:
            s = InvoiceStatus(status)
            invoices = [i for i in invoices if i.status == s]
        except ValueError:
            raise HTTPException(400, f"Unknown status: {status}")
    return [InvoiceSummary.from_record(inv) for inv in invoices]


@router.get(
    "/{invoice_id}",
    response_model=InvoiceOut,
    summary="Détails d'une facture",
    description=(
        "Retourne tous les champs d'une facture : données extraites avec scores de confiance, "
        "lignes de détail, flags de validation (erreurs, avertissements), historique de statuts."
    ),
    response_description="InvoiceRecord complet avec champs ConfidenceField et flags",
    responses={404: {"description": "Facture non trouvée"}},
)
def get_invoice(
    invoice_id: str,
    session: Session = Depends(get_session),
):
    repo = InvoiceRepository(session)
    try:
        uid = UUID(invoice_id)
    except ValueError:
        raise HTTPException(400, "Invalid UUID")
    inv = repo.get_by_id(uid)
    if not inv:
        raise HTTPException(404, "Invoice not found")
    return InvoiceOut.from_record(inv)


@router.patch(
    "/{invoice_id}/status",
    response_model=ActionResultOut,
    summary="Mettre à jour le statut",
    description="Force manuellement le statut d'une facture. Utilisé par la file de révision et les scripts de correction.",
    response_description="ID de la facture, action effectuée et nouveau statut",
    responses={
        400: {"description": "Statut invalide"},
        404: {"description": "Facture non trouvée"},
    },
)
def update_status(
    invoice_id: str,
    new_status: str,
    session: Session = Depends(get_session),
):
    repo = InvoiceRepository(session)
    try:
        uid = UUID(invoice_id)
        status = InvoiceStatus(new_status)
    except ValueError as e:
        raise HTTPException(400, str(e))
    inv = repo.get_by_id(uid)
    if not inv:
        raise HTTPException(404, "Invoice not found")
    inv.status = status
    repo.save(inv)
    return ActionResultOut(id=invoice_id, action="status_updated", new_status=new_status)
