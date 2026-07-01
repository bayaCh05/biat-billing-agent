"""Invoice endpoints — upload + pipeline, list, detail."""
from __future__ import annotations

import tempfile
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from api.deps import get_session, get_components
from api.schemas import InvoiceOut, InvoiceSummary, ActionResultOut
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
    content = await file.read()

    # Validate file before processing
    from api.security.file_validator import validate as validate_file
    from src.models.audit import AuditLogCreate
    from src.services.audit_service import log_action, _ip, _ua
    try:
        file_info = validate_file(file.filename or "invoice.pdf", content)
    except Exception as validation_err:
        log_action(session, AuditLogCreate(
            action="FILE_REJECTED", resource_type="InvoiceRecord", status="FAILURE",
            detail=str(validation_err),
            ip_address=request.client.host if request.client else None,
        ))
        session.commit()
        raise

    suffix = Path(file.filename or "invoice.pdf").suffix or ".pdf"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    log_action(session, AuditLogCreate(
        action="FILE_UPLOADED", resource_type="InvoiceRecord", status="SUCCESS",
        detail=f"type={file_info['detected_type']} size={file_info['file_size_bytes']}B",
        ip_address=request.client.host if request.client else None,
    ))

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

        # Run through AI orchestrator (extraction → classification → anomaly → accounting)
        from src.ai_agents.orchestrator import AIOrchestrator
        orchestrator = AIOrchestrator(components, session)
        orchestrator.process_invoice(invoice)

        # Re-fetch invoice from DB to get final persisted state
        invoice = repo.get_by_id(invoice.id) or invoice
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


@router.get(
    "/{invoice_id}/pipeline-status",
    summary="Statut temps réel du pipeline IA",
    description=(
        "Retourne l'état actuel de chaque étape du pipeline IA pour une facture : "
        "extraction, classification, anomalies, comptabilité. "
        "Utilisé par le tracker temps réel dans l'interface."
    ),
)
def get_pipeline_status(
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

    status = inv.status.value

    def _step(num, name, done_statuses, running_statuses):
        if status in done_statuses:
            return {"step": num, "name": name, "status": "done"}
        if status in running_statuses:
            return {"step": num, "name": name, "status": "running"}
        if status in ("EXTRACTION_FAILED", "ERROR"):
            return {"step": num, "name": name, "status": "failed"}
        return {"step": num, "name": name, "status": "waiting"}

    extracted = ["EXTRACTED", "CLASSIFYING", "CLASSIFIED", "VALIDATING",
                 "VALIDATED", "FLAGGED", "JOURNALED", "EXPORTED", "PAID"]
    classified = ["CLASSIFIED", "VALIDATING", "VALIDATED", "FLAGGED", "JOURNALED", "EXPORTED", "PAID"]
    validated = ["VALIDATED", "FLAGGED", "JOURNALED", "EXPORTED", "PAID"]
    journaled = ["JOURNALED", "EXPORTED", "PAID"]

    steps = [
        _step(1, "Extraction PDF", extracted, ["EXTRACTING", "RECEIVED"]),
        _step(2, "Classification PCE", classified, ["CLASSIFYING"]),
        _step(3, "Détection anomalies", validated + ["FLAGGED"], ["VALIDATING"]),
        _step(4, "Écriture comptable", journaled, ["EXPORTING"]),
    ]

    # Add summaries from AI fields
    steps[0]["summary"] = inv.extraction_method.value if inv.extraction_method else None
    steps[1]["summary"] = (
        f"Compte {inv.accounting_compte} via {inv.classification_pass}"
        if inv.accounting_compte else None
    )
    steps[1]["reason"] = inv.classification_reason

    # Step 3: anomaly count
    flag_count = len(inv.flags) if inv.flags else 0
    error_count = sum(1 for f in (inv.flags or []) if getattr(f, "severity", None) and f.severity.value == "ERROR")
    if steps[2]["status"] in ("done", "running"):
        steps[2]["summary"] = (
            f"{flag_count} anomalie(s) dont {error_count} erreur(s)" if flag_count
            else "Aucune anomalie détectée"
        )

    # Step 4: fetch journal entry lines
    journal_entry = None
    if status in ("JOURNALED", "EXPORTED", "PAID"):
        from sqlalchemy import text as sql_text
        rows = session.execute(
            sql_text(
                "SELECT je.id, je.reference, je.date_ecriture, je.description, "
                "je.accounting_explanation, "
                "jl.compte, jl.libelle, jl.debit, jl.credit "
                "FROM journal_entries je "
                "JOIN journal_lines jl ON jl.entry_id = je.id "
                "WHERE je.source_invoice_id = :iid "
                "ORDER BY jl.debit DESC"
            ),
            {"iid": invoice_id},
        ).fetchall()

        if rows:
            total_debit = sum(float(r[7] or 0) for r in rows)
            total_credit = sum(float(r[8] or 0) for r in rows)
            is_balanced = abs(total_debit - total_credit) < 0.005
            journal_entry = {
                "id": str(rows[0][0]),
                "reference": rows[0][1],
                "date_ecriture": str(rows[0][2]),
                "description": rows[0][3],
                "accounting_explanation": rows[0][4],
                "is_balanced": is_balanced,
                "lines": [
                    {
                        "compte": r[5] or "",
                        "libelle": r[6] or "",
                        "debit": float(r[7] or 0),
                        "credit": float(r[8] or 0),
                    }
                    for r in rows
                ],
            }
            steps[3]["summary"] = (
                f"Écriture {rows[0][1]} — {'équilibrée ✓' if is_balanced else 'DÉSÉQUILIBRÉE ⚠'}"
            )

    from src.ai_agents.ollama_client import OllamaClient
    degraded = not OllamaClient.get().is_available()

    return {
        "invoice_id": invoice_id,
        "final_status": status,
        "steps": steps,
        "degraded_mode": degraded,
        "human_review_required": inv.human_review_required,
        "journal_entry": journal_entry,
    }
