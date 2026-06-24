"""Client invoice (facturation) endpoints."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.deps import get_session, get_config
from api.schemas import ClientTemplateOut, ClientInvoiceOut, GenerateInvoiceRequest, GeneratedInvoiceOut
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


@router.get("/invoices", response_model=list[ClientInvoiceOut])
def list_client_invoices(session: Session = Depends(get_session)):
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
