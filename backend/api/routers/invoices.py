"""Invoice endpoints — upload + pipeline, list, detail."""
from __future__ import annotations

import tempfile
from pathlib import Path
from uuid import UUID

import csv
import io

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from api.auth import get_current_user, require_role
from api.deps import get_session, get_components
from api.schemas import InvoiceOut, InvoiceSummary, ActionResultOut
from src.models.enums import InvoiceStatus
from src.models.invoice import InvoiceRecord
from src.storage.repository import InvoiceRepository
from src.utils.file_utils import sha256
from api.limiter import limiter, limit

router = APIRouter(prefix="/invoices", tags=["invoices"])

_COMPTABLE_OR_ADMIN = Depends(require_role("Comptable", "Admin"))


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
    current_user: dict = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    if current_user["role"] not in ("Comptable", "Admin"):
        raise HTTPException(403, "Accès refusé. Seul un Comptable peut soumettre des factures.")

    content = await file.read()

    # Validate file before processing
    from api.security.file_validator import validate as validate_file
    from src.models.audit import AuditLogCreate
    from src.services.audit_service import _ip, _ua
    from src.storage.documents.service_bridge import log_audit_event_native
    try:
        file_info = validate_file(file.filename or "invoice.pdf", content)
    except Exception as validation_err:
        await log_audit_event_native(AuditLogCreate(
            action="FILE_REJECTED", resource_type="InvoiceRecord", status="FAILURE",
            detail=str(validation_err),
            ip_address=_ip(request), user_agent=_ua(request),
            user_id=current_user.get("sub"),
            user_email=current_user.get("email"),
            user_role=current_user.get("role"),
        ))
        raise

    suffix = Path(file.filename or "invoice.pdf").suffix or ".pdf"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    # Persist a copy so the PDF can be served later
    uploads_dir = Path("data/uploads")
    uploads_dir.mkdir(parents=True, exist_ok=True)

    await log_audit_event_native(AuditLogCreate(
        action="INVOICE_UPLOADED", resource_type="InvoiceRecord", status="SUCCESS",
        detail=f"type={file_info['detected_type']} size={file_info['file_size_bytes']}B",
        ip_address=_ip(request), user_agent=_ua(request),
        user_id=current_user.get("sub"),
        user_email=current_user.get("email"),
        user_role=current_user.get("role"),
    ))

    from src.storage.sync_mongo_repository import SyncMongoInvoiceRepository
    repo = SyncMongoInvoiceRepository()

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
        persistent_path = str(uploads_dir / f"{file_hash}{suffix}")
        import shutil
        shutil.copy2(tmp_path, persistent_path)

        existing = repo.get_by_hash(file_hash)

        if existing:
            existing.status = InvoiceStatus.RECEIVED
            existing.retry_count = 0
            existing.last_error = None
            existing.flags = []
            existing.raw_file_path = persistent_path
            repo.save(existing)
            invoice = existing
        else:
            invoice = InvoiceRecord(
                file_hash=file_hash,
                raw_file_path=persistent_path,
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
async def list_invoices(
    status: str | None = None,
    limit: int = 100,
    session: Session = Depends(get_session),
):
    from src.storage.documents.service_bridge import list_invoices_mongo

    mongo_invoices = await list_invoices_mongo(limit)
    if mongo_invoices is not None:
        invoices = mongo_invoices
    else:
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
    "/export",
    summary="Exporter les factures en CSV",
    description="Exporte toutes les factures (ou filtrées par statut) en CSV — usage comptable et ERP.",
    response_class=StreamingResponse,
)
async def export_invoices_csv(
    status: str | None = Query(None, description="Filtrer par statut (optionnel)"),
    limit: int = Query(5000, description="Nombre maximum de lignes"),
    session: Session = Depends(get_session),
):
    from src.storage.documents.service_bridge import list_invoices_mongo

    mongo_invoices = await list_invoices_mongo(limit)
    if mongo_invoices is not None:
        invoices = mongo_invoices
    else:
        repo = InvoiceRepository(session)
        invoices = repo.list_all(limit=limit)
    if status:
        try:
            s = InvoiceStatus(status)
            invoices = [i for i in invoices if i.status == s]
        except ValueError:
            raise HTTPException(400, f"Unknown status: {status}")

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    writer.writerow([
        "id", "statut", "direction", "fournisseur", "num_facture", "date_facture",
        "montant_ht", "taux_tva", "montant_tva", "montant_ttc", "devise",
        "compte_pce", "libelle_pce", "revue_humaine", "date_reception",
    ])
    for inv in invoices:
        writer.writerow([
            str(inv.id),
            inv.status.value,
            inv.direction.value,
            inv.issuer_name.value or "",
            inv.invoice_number.value or "",
            inv.invoice_date.value.isoformat() if inv.invoice_date.value else "",
            inv.amount_ht.value or "",
            inv.tva_rate.value or "",
            inv.tva_amount.value or "",
            inv.amount_ttc.value or "",
            inv.currency,
            inv.accounting_compte or "",
            inv.accounting_label or "",
            "oui" if inv.human_review_required else "non",
            inv.received_at.isoformat(),
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=factures.csv"},
    )


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
async def get_invoice(
    invoice_id: str,
    session: Session = Depends(get_session),
):
    from src.storage.documents.service_bridge import _NOT_FOUND, get_invoice_mongo

    try:
        uid = UUID(invoice_id)
    except ValueError:
        raise HTTPException(400, "Invalid UUID")

    mongo_inv = await get_invoice_mongo(uid)
    if mongo_inv is _NOT_FOUND:
        raise HTTPException(404, "Invoice not found")
    if mongo_inv is not None:
        return InvoiceOut.from_record(mongo_inv)

    repo = InvoiceRepository(session)
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
async def update_status(
    invoice_id: str,
    new_status: str,
    _: None = _COMPTABLE_OR_ADMIN,
):
    from src.storage.documents.service_bridge import update_invoice_status_native

    try:
        UUID(invoice_id)
        status = InvoiceStatus(new_status)
    except ValueError as e:
        raise HTTPException(400, str(e))

    inv = await update_invoice_status_native(invoice_id, status.value)
    if not inv:
        raise HTTPException(404, "Invoice not found")
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
async def get_pipeline_status(
    invoice_id: str,
    session: Session = Depends(get_session),
):
    from src.storage.documents.service_bridge import _NOT_FOUND, get_invoice_mongo

    try:
        uid = UUID(invoice_id)
    except ValueError:
        raise HTTPException(400, "Invalid UUID")

    use_mongo = True
    mongo_inv = await get_invoice_mongo(uid)
    if mongo_inv is _NOT_FOUND:
        raise HTTPException(404, "Invoice not found")
    if mongo_inv is not None:
        inv = mongo_inv
    else:
        use_mongo = False
        repo = InvoiceRepository(session)
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
        from src.storage.documents.service_bridge import get_journal_entry_for_invoice_mongo

        mongo_je = await get_journal_entry_for_invoice_mongo(invoice_id) if use_mongo else None
        # mongo_je == {} (trouvé mais vide) est traité comme un échec, pas comme
        # "pas d'écriture" : un statut JOURNALED/EXPORTED/PAID implique toujours
        # une écriture existante, donc un résultat vide est suspect — on retombe
        # sur SQL par sécurité plutôt que d'afficher "aucune écriture" à tort.
        if mongo_je:
            journal_entry = {k: v for k, v in mongo_je.items() if k != "summary"}
            steps[3]["summary"] = mongo_je["summary"]
        else:
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
                # SQLite stocke source_invoice_id sans tirets (CHAR(32) brut) —
                # bug préexistant : invoice_id (paramètre d'URL) est toujours au
                # format avec tirets (str(UUID)), donc cette requête ne matchait
                # jamais rien avant cette normalisation.
                {"iid": invoice_id.replace("-", "")},
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


@router.get(
    "/{invoice_id}/pdf",
    summary="Télécharger le PDF original de la facture",
)
async def get_invoice_pdf(
    invoice_id: UUID,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    from src.storage.documents.service_bridge import _NOT_FOUND, get_invoice_mongo

    mongo_inv = await get_invoice_mongo(invoice_id)
    if mongo_inv is _NOT_FOUND:
        raise HTTPException(404, "Facture introuvable")
    if mongo_inv is not None:
        inv = mongo_inv
    else:
        repo = InvoiceRepository(session)
        inv = repo.get_by_id(invoice_id)
        if not inv:
            raise HTTPException(404, "Facture introuvable")
    path = Path(inv.raw_file_path) if inv.raw_file_path else None
    if not path or not path.exists():
        raise HTTPException(404, "Fichier PDF non disponible")
    media = "application/pdf" if path.suffix.lower() == ".pdf" else "application/octet-stream"
    return FileResponse(str(path), media_type=media, filename=path.name)
