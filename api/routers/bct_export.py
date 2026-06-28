"""BCT export compliance endpoints — Banque Centrale de Tunisie, Circulaire 2025-13."""
from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import date, datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.auth import require_role
from api.deps import get_session
from api.limiter import limiter, limit
from src.billing.client_invoice_store import ClientInvoiceRepository
from src.services.bct_compliance_service import (
    check_repatriation_status,
    generate_bct_export_report,
)
from src.services.export_signature_service import (
    generate_export_signature,
    verify_export_signature,
)
from src.storage.orm_models_audit import AuditLogORM

router = APIRouter(prefix="/export", tags=["bct-export"])

_ALLOWED = Depends(require_role("Comptable", "Direction", "Admin"))


# ── Schemas ───────────────────────────────────────────────────────────────────

class BCTAgingItem(BaseModel):
    invoice_number:         str
    client_name:            str
    currency:               str
    amount_tnd:             float
    shipment_date:          str | None
    repatriation_deadline:  str | None
    days_remaining_or_overdue: int | None
    status:                 str
    payment_guarantee_type: str | None


class VerifyResult(BaseModel):
    valid:   bool
    message: str


class MarkRepat(BaseModel):
    repatriation_date: date | None = None  # defaults to today if omitted


# ── Helpers ───────────────────────────────────────────────────────────────────

def _log(session: Session, action: str, actor: str, entity_id: str | None = None, detail: str | None = None) -> None:
    session.add(AuditLogORM(action=action, actor=actor, entity_id=entity_id, detail=detail))
    session.commit()


def _build_csv(report: dict) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=[
        "invoice_number", "client_name", "currency", "foreign_amount",
        "exchange_rate", "amount_tnd", "shipment_date", "repatriation_deadline",
        "repatriation_date", "days_remaining_or_overdue", "domiciliation_bank",
        "domiciliation_number", "payment_guarantee_type", "status",
    ])
    writer.writeheader()
    for row in report["invoices"]:
        writer.writerow(row)
    return buf.getvalue().encode("utf-8-sig")  # BOM for Excel compatibility


def _quarter_label(start: date, end: date) -> str:
    q = (start.month - 1) // 3 + 1
    return f"{start.year}_Q{q}"


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get(
    "/bct-report",
    summary="Générer le rapport BCT export (ZIP signé)",
    description=(
        "Génère un rapport BCT de rapatriement pour la période sélectionnée. "
        "Retourne un ZIP contenant le CSV des factures export et la signature SHA-256. "
        "Accessible aux rôles Comptable et Direction uniquement."
    ),
    response_description="Fichier ZIP : CSV + signature JSON",
    responses={403: {"description": "Accès refusé"}},
)
@limiter.limit(limit("10/minute"))
def get_bct_report(
    request: Request,
    from_: date = None,
    to: date = None,
    session: Session = Depends(get_session),
    user: dict = _ALLOWED,
):
    today = date.today()
    period_start = from_ or date(today.year, 1, 1)
    period_end   = to or today

    report = generate_bct_export_report(session, period_start, period_end)
    csv_bytes = _build_csv(report)
    label = _quarter_label(period_start, period_end)

    sig_meta = {
        "user_email":     user.get("sub", user.get("email", "unknown")),
        "period":         report["period"],
        "record_count":   report["total_export_invoices"],
        "total_amount_tnd": sum(r["amount_tnd"] or 0 for r in report["invoices"]),
        "overdue_count":  report["overdue_count"],
    }
    signature = generate_export_signature(csv_bytes, sig_meta)

    # Build in-memory ZIP
    zip_buf = io.BytesIO()
    csv_name = f"bct_rapport_{label}.csv"
    sig_name = f"bct_rapport_{label}_signature.json"
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(csv_name, csv_bytes)
        zf.writestr(sig_name, json.dumps(signature, ensure_ascii=False, indent=2))
    zip_buf.seek(0)

    _log(
        session,
        action="BCT_REPORT_GENERATED",
        actor=user.get("sub", "unknown"),
        detail=f"period={report['period']} invoices={report['total_export_invoices']} overdue={report['overdue_count']}",
    )

    if report["overdue_count"] > 0:
        _log(
            session,
            action="BCT_OVERDUE_DETECTED",
            actor=user.get("sub", "system"),
            detail=f"overdue_count={report['overdue_count']} period={report['period']}",
        )

    zip_name = f"bct_report_{label}.zip"
    return StreamingResponse(
        zip_buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_name}"'},
    )


@router.get(
    "/bct-aging",
    response_model=list[BCTAgingItem],
    summary="Factures export en alerte BCT",
    description=(
        "Retourne toutes les factures export non encore rapatriées "
        "dont le statut BCT est WARNING ou OVERDUE. "
        "Utilisé par le widget de conformité du tableau de bord Direction."
    ),
    response_description="Liste des factures export avec leur statut de rapatriement",
)
def get_bct_aging(
    session: Session = Depends(get_session),
    user: dict = _ALLOWED,
):
    repo = ClientInvoiceRepository(session)
    invoices = repo.list_exports_warning_overdue()

    result = []
    for inv in invoices:
        rep = check_repatriation_status(inv)
        status = rep.get("status", "OK")
        if status not in ("WARNING", "OVERDUE"):
            continue
        days_val = rep.get("days_remaining") or (-rep.get("days_overdue", 0))
        result.append(BCTAgingItem(
            invoice_number=inv.invoice_number,
            client_name=inv.client_name,
            currency=inv.currency,
            amount_tnd=inv.amount_ttc,
            shipment_date=inv.shipment_date.isoformat() if inv.shipment_date else None,
            repatriation_deadline=inv.repatriation_deadline.isoformat() if inv.repatriation_deadline else None,
            days_remaining_or_overdue=days_val,
            status=status,
            payment_guarantee_type=inv.payment_guarantee_type,
        ))
    return result


@router.post(
    "/bct-report/verify",
    response_model=VerifyResult,
    summary="Vérifier l'intégrité d'un rapport BCT",
    description=(
        "Accepte un multipart avec le fichier CSV et la signature JSON. "
        "Recompute le SHA-256 et retourne le résultat de la vérification."
    ),
    response_description="Résultat de la vérification d'intégrité",
)
async def verify_bct_report(
    report_file:    UploadFile = File(...),
    signature_file: UploadFile = File(...),
    session: Session = Depends(get_session),
    user: dict = _ALLOWED,
):
    csv_bytes  = await report_file.read()
    sig_bytes  = await signature_file.read()
    try:
        signature = json.loads(sig_bytes)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Fichier de signature JSON invalide.")

    valid = verify_export_signature(csv_bytes, signature)
    _log(
        session,
        action="EXPORT_VERIFIED",
        actor=user.get("sub", "unknown"),
        detail=f"valid={valid} file={report_file.filename}",
    )
    return VerifyResult(
        valid=valid,
        message="Rapport intègre — aucune altération détectée." if valid
                else "ALERTE : Le rapport a été modifié depuis sa génération.",
    )


@router.patch(
    "/client-invoices/{invoice_id}/mark-repatriated",
    summary="Confirmer le rapatriement d'une facture export",
    description=(
        "Enregistre la date de rapatriement effective sur la facture export. "
        "Accessible au rôle Comptable uniquement. "
        "Génère une entrée dans le journal d'audit BCT."
    ),
    response_description="Confirmation avec date de rapatriement enregistrée",
    responses={
        404: {"description": "Facture non trouvée"},
        400: {"description": "Facture non export ou déjà rapatriée"},
        403: {"description": "Accès refusé"},
    },
)
def mark_repatriated(
    invoice_id: str,
    body: MarkRepat = MarkRepat(),
    session: Session = Depends(get_session),
    user: dict = Depends(require_role("Comptable", "Admin")),
):
    from src.billing.client_invoice_store import ClientInvoiceORM
    try:
        uid = UUID(invoice_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="UUID invalide.")

    orm = session.get(ClientInvoiceORM, uid)
    if orm is None:
        raise HTTPException(status_code=404, detail="Facture non trouvée.")
    if not orm.is_export:
        raise HTTPException(status_code=400, detail="Cette facture n'est pas une facture export.")

    repat_date = body.repatriation_date or date.today()
    orm.repatriation_date = repat_date
    session.commit()

    _log(
        session,
        action="REPATRIATION_CONFIRMED",
        actor=user.get("sub", "unknown"),
        entity_id=invoice_id,
        detail=f"repatriation_date={repat_date}",
    )

    return {
        "invoice_id":        invoice_id,
        "repatriation_date": repat_date.isoformat(),
        "message":           "Rapatriement enregistré avec succès.",
    }
