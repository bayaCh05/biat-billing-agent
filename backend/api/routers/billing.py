"""Client invoice (facturation) endpoints."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.auth import require_role
from api.deps import get_session, get_config
from api.schemas import ClientTemplateOut, ClientInvoiceOut, GenerateInvoiceRequest, GeneratedInvoiceOut
from src.billing.template_loader import TemplateLoader
from src.billing.invoice_builder import InvoiceBuilder
from src.billing.invoice_numbering import InvoiceNumberer
from src.billing.client_invoice_store import ClientInvoiceRepository

router = APIRouter(prefix="/billing", tags=["client-invoices"])

_COMPTABLE_CHEF = Depends(require_role("Comptable", "Chef de Projet"))


@router.get(
    "/templates",
    response_model=list[ClientTemplateOut],
    summary="Lister les modèles de facturation",
    description=(
        "Retourne les modèles de facturation intra-groupe définis dans `client_templates.yaml`. "
        "Chaque modèle contient le client cible, la description du service et le prix unitaire HT."
    ),
    response_description="Liste des modèles disponibles pour la génération de factures",
)
def list_templates(_: dict = _COMPTABLE_CHEF, cfg: dict = Depends(get_config)):
    loader = TemplateLoader(cfg["billing"]["templates_file"])
    result = []
    for tpl in loader.list_templates():
        client_id = tpl.default_client_id
        try:
            client = loader.get_client(client_id) if client_id else None
        except KeyError:
            client = None

        result.append(ClientTemplateOut(
            id=tpl.id,
            client_code=client_id or tpl.id,
            client_name=client.name if client else tpl.label,
            service_description=tpl.description,
            unit_price_ht=tpl.default_unit_price,
            tva_rate=tpl.tva_rate,
        ))
    return result


@router.get(
    "/invoices",
    response_model=list[ClientInvoiceOut],
    summary="Lister les factures émises",
    description=(
        "Retourne toutes les factures client émises par BIAT IT, "
        "triées par date d'émission décroissante. "
        "Statuts : DRAFT, SENT, PAID."
    ),
    response_description="Liste des factures client avec montants HT, TVA, TTC et dates",
)
async def list_client_invoices(_: dict = _COMPTABLE_CHEF, session: Session = Depends(get_session)):
    from src.storage.documents.service_bridge import list_client_invoices_mongo

    mongo_invoices = await list_client_invoices_mongo()
    if mongo_invoices is not None:
        invoices = mongo_invoices
    else:
        repo = ClientInvoiceRepository(session)
        invoices = repo.list_all()
    return [
        ClientInvoiceOut(
            invoice_number=inv.invoice_number,
            client_name=inv.client_name,
            invoice_date=inv.invoice_date.isoformat(),
            due_date=inv.due_date.isoformat(),
            amount_ht=inv.amount_ht,
            tva_amount=inv.tva_amount,
            amount_ttc=inv.amount_ttc,
            status=inv.status.value if hasattr(inv.status, "value") else str(inv.status),
            sent_at=inv.sent_at.isoformat() if inv.sent_at else None,
            paid_at=inv.paid_at.isoformat() if inv.paid_at else None,
        )
        for inv in invoices
    ]


@router.post(
    "/generate",
    response_model=GeneratedInvoiceOut,
    summary="Générer une facture client",
    description=(
        "Génère une facture client à partir d'un modèle intra-groupe. "
        "Le numéro est attribué automatiquement au format FAC-IT-YYYY-NNNN. "
        "La facture est persistée en base avec le statut DRAFT."
    ),
    response_description="Facture générée avec son numéro et montants",
    responses={404: {"description": "Modèle de facturation non trouvé"}},
)
async def generate_invoice(
    body: GenerateInvoiceRequest,
    _: dict = _COMPTABLE_CHEF,
    cfg: dict = Depends(get_config),
):
    from src.storage.sync_mongo_repository import SyncMongoClientInvoiceRepository

    loader = TemplateLoader(cfg["billing"]["templates_file"])
    tpl = next((t for t in loader.list_templates() if t.id == body.template_id), None)
    if not tpl:
        raise HTTPException(404, f"Template {body.template_id} not found")

    repo = SyncMongoClientInvoiceRepository()
    numberer = InvoiceNumberer(repo)
    builder = InvoiceBuilder(loader=loader, numberer=numberer)

    invoice_date = date(body.year, body.month, 1)
    invoice = builder.from_template(
        template_id=body.template_id,
        invoice_date=invoice_date,
    )
    repo.save(invoice)

    return GeneratedInvoiceOut(
        invoice_number=invoice.invoice_number,
        client_name=invoice.client_name,
        amount_ht=invoice.amount_ht,
        tva_amount=invoice.tva_amount,
        amount_ttc=invoice.amount_ttc,
        status=invoice.status.value if hasattr(invoice.status, "value") else str(invoice.status),
    )
