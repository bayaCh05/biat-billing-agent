"""Client invoice (facturation) endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.deps import get_session, get_config
from api.schemas import ClientTemplateOut, GenerateInvoiceRequest, GeneratedInvoiceOut
from src.billing.template_loader import TemplateLoader
from src.billing.invoice_builder import InvoiceBuilder
from src.billing.invoice_numbering import InvoiceNumberer
from src.billing.client_invoice_store import ClientInvoiceRepository

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/templates", response_model=list[ClientTemplateOut])
def list_templates(cfg: dict = Depends(get_config)):
    loader = TemplateLoader(cfg["billing"]["templates_file"])
    result = []
    for tpl in loader.list_templates():
        # Look up the client this template is for
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


@router.post("/generate", response_model=GeneratedInvoiceOut)
def generate_invoice(
    body: GenerateInvoiceRequest,
    session: Session = Depends(get_session),
    cfg: dict = Depends(get_config),
):
    loader = TemplateLoader(cfg["billing"]["templates_file"])
    tpl = next((t for t in loader.list_templates() if t.id == body.template_id), None)
    if not tpl:
        raise HTTPException(404, f"Template {body.template_id} not found")

    repo = ClientInvoiceRepository(session)
    numberer = InvoiceNumberer(repo)
    builder = InvoiceBuilder(loader=loader, numberer=numberer)

    invoice = builder.build(
        client_code=tpl.default_client_id or body.template_id,
        year=body.year,
        month=body.month,
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
