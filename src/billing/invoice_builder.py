"""Construction des factures client à partir de modèles de service ou manuellement."""
from __future__ import annotations

from datetime import date, timedelta

from src.billing.invoice_numbering import InvoiceNumberer
from src.billing.template_loader import TemplateLoader
from src.models.client_invoice import ClientInvoice, ClientLineItem


class InvoiceBuilder:
    """Construit des ClientInvoice à partir de modèles ou de données manuelles."""

    def __init__(self, loader: TemplateLoader, numberer: InvoiceNumberer) -> None:
        self._loader   = loader
        self._numberer = numberer

    # ── Public API ────────────────────────────────────────────────────────────

    def from_template(
        self,
        template_id:   str,
        invoice_date:  date,
        client_id:     str | None = None,
        quantity:      float | None = None,
        unit_price:    float | None = None,
        notes:         str | None = None,
    ) -> ClientInvoice:
        """Créer une facture à partir d'un modèle de service.

        Args:
            template_id:  Identifiant du modèle (voir client_templates.yaml).
            invoice_date: Date d'émission.
            client_id:    Écrase le client par défaut du modèle si fourni.
            quantity:     Écrase la quantité par défaut.
            unit_price:   Écrase le prix unitaire par défaut.
            notes:        Mentions libres ajoutées en bas de facture.
        """
        tmpl   = self._loader.get_template(template_id)
        cid    = client_id  or tmpl.default_client_id
        client = self._loader.get_client(cid)

        qty  = quantity   if quantity   is not None else tmpl.default_quantity
        uprc = unit_price if unit_price is not None else tmpl.default_unit_price

        line = self._make_line(
            description    = tmpl.description,
            quantity       = qty,
            unit_price     = uprc,
            tva_rate       = tmpl.tva_rate,
            compte_produit = tmpl.compte_produit,
        )

        return self._build(
            invoice_date       = invoice_date,
            client             = client,
            line_items         = [line],
            notes              = notes,
            source_template_id = template_id,
        )

    def manual(
        self,
        client_id:    str,
        invoice_date: date,
        line_items:   list[dict],
        notes:        str | None = None,
    ) -> ClientInvoice:
        """Créer une facture entièrement personnalisée.

        Each dict in line_items must contain:
            description, unit_price, and optionally:
            quantity (default 1.0), tva_rate (default 19.0),
            compte_produit (default "7061")
        """
        client = self._loader.get_client(client_id)
        lines  = [
            self._make_line(
                description    = item["description"],
                quantity       = float(item.get("quantity",       1.0)),
                unit_price     = float(item["unit_price"]),
                tva_rate       = float(item.get("tva_rate",       19.0)),
                compte_produit = str(item.get("compte_produit",  "7061")),
            )
            for item in line_items
        ]
        return self._build(
            invoice_date = invoice_date,
            client       = client,
            line_items   = lines,
            notes        = notes,
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _make_line(
        description:    str,
        quantity:       float,
        unit_price:     float,
        tva_rate:       float,
        compte_produit: str,
    ) -> ClientLineItem:
        line_total = round(quantity * unit_price, 3)
        tva_amount = round(line_total * tva_rate / 100, 3)
        return ClientLineItem(
            description    = description,
            quantity       = quantity,
            unit_price     = unit_price,
            line_total     = line_total,
            tva_rate       = tva_rate,
            tva_amount     = tva_amount,
            compte_produit = compte_produit,
        )

    def _build(
        self,
        invoice_date:       date,
        client,
        line_items:         list[ClientLineItem],
        notes:              str | None = None,
        source_template_id: str | None = None,
    ) -> ClientInvoice:
        issuer          = self._loader.issuer
        invoice_number  = self._numberer.next_number(invoice_date)
        due_date        = invoice_date + timedelta(days=client.payment_terms_days)

        return ClientInvoice(
            invoice_number     = invoice_number,
            invoice_date       = invoice_date,
            due_date           = due_date,
            issuer_name        = issuer.name,
            issuer_tax_id      = issuer.tax_id,
            issuer_address     = issuer.address,
            client_id          = client.id,
            client_name        = client.name,
            client_tax_id      = client.tax_id,
            client_address     = client.address,
            line_items         = line_items,
            notes              = notes,
            source_template_id = source_template_id,
        )
