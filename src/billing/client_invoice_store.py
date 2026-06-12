"""ORM et dépôt pour les factures émises (ClientInvoice)."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from src.models.client_invoice import ClientInvoice, ClientInvoiceStatus, ClientLineItem
from src.storage.db import Base


# ── ORM models ────────────────────────────────────────────────────────────────

class ClientLineItemORM(Base):
    __tablename__ = "client_line_items"

    id:             Mapped[int]   = mapped_column(Integer, primary_key=True, autoincrement=True)
    invoice_id:     Mapped[UUID]  = mapped_column(ForeignKey("client_invoices.id", ondelete="CASCADE"))
    description:    Mapped[str]   = mapped_column(Text)
    quantity:       Mapped[float] = mapped_column(Float)
    unit_price:     Mapped[float] = mapped_column(Float)
    line_total:     Mapped[float] = mapped_column(Float)
    tva_rate:       Mapped[float] = mapped_column(Float)
    tva_amount:     Mapped[float] = mapped_column(Float)
    compte_produit: Mapped[str]   = mapped_column(String(16))


class ClientInvoiceORM(Base):
    __tablename__ = "client_invoices"

    id:             Mapped[UUID]   = mapped_column(primary_key=True)
    invoice_number: Mapped[str]    = mapped_column(String(32), unique=True, index=True)
    invoice_date:   Mapped[object] = mapped_column(Date, index=True)
    due_date:       Mapped[object] = mapped_column(Date)

    issuer_name:    Mapped[str]        = mapped_column(Text)
    issuer_tax_id:  Mapped[str]        = mapped_column(String(32))
    issuer_address: Mapped[str | None] = mapped_column(Text)

    client_id:      Mapped[str]        = mapped_column(String(64), index=True)
    client_name:    Mapped[str]        = mapped_column(Text)
    client_tax_id:  Mapped[str]        = mapped_column(String(32))
    client_address: Mapped[str | None] = mapped_column(Text)

    amount_ht:  Mapped[float] = mapped_column(Float)
    tva_amount: Mapped[float] = mapped_column(Float)
    amount_ttc: Mapped[float] = mapped_column(Float)

    status:             Mapped[str]        = mapped_column(String(16), index=True)
    source_template_id: Mapped[str | None] = mapped_column(String(64))
    notes:              Mapped[str | None] = mapped_column(Text)
    pdf_path:           Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at:    Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_at:    Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    line_items: Mapped[list[ClientLineItemORM]] = relationship(
        "ClientLineItemORM",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


# ── Repository ────────────────────────────────────────────────────────────────

class ClientInvoiceRepository:

    def __init__(self, session: Session) -> None:
        self.session = session

    # ── Write ─────────────────────────────────────────────────────────────────

    def save(self, invoice: ClientInvoice) -> ClientInvoice:
        existing = self.session.get(ClientInvoiceORM, invoice.id)
        if existing is None:
            orm = self._to_orm(invoice)
            self.session.add(orm)
        else:
            self._update_orm(existing, invoice)
        self.session.commit()
        return invoice

    def update_status(
        self,
        invoice_id: UUID,
        status: ClientInvoiceStatus,
        *,
        sent_at:  datetime | None = None,
        paid_at:  datetime | None = None,
        pdf_path: str | None      = None,
    ) -> None:
        orm = self.session.get(ClientInvoiceORM, invoice_id)
        if orm is None:
            raise KeyError(f"ClientInvoice {invoice_id} introuvable")
        orm.status = status.value
        if sent_at  is not None: orm.sent_at  = sent_at
        if paid_at  is not None: orm.paid_at  = paid_at
        if pdf_path is not None: orm.pdf_path = pdf_path
        self.session.commit()

    # ── Read ──────────────────────────────────────────────────────────────────

    def get_by_id(self, invoice_id: UUID) -> ClientInvoice | None:
        orm = self.session.get(ClientInvoiceORM, invoice_id)
        return self._to_pydantic(orm) if orm else None

    def get_by_number(self, number: str) -> ClientInvoice | None:
        orm = self.session.execute(
            select(ClientInvoiceORM).where(ClientInvoiceORM.invoice_number == number)
        ).scalar_one_or_none()
        return self._to_pydantic(orm) if orm else None

    def list_all(self) -> list[ClientInvoice]:
        orms = self.session.execute(
            select(ClientInvoiceORM).order_by(ClientInvoiceORM.invoice_date.desc())
        ).scalars().all()
        return [self._to_pydantic(o) for o in orms]

    def list_by_status(self, status: ClientInvoiceStatus) -> list[ClientInvoice]:
        orms = self.session.execute(
            select(ClientInvoiceORM)
            .where(ClientInvoiceORM.status == status.value)
            .order_by(ClientInvoiceORM.invoice_date.desc())
        ).scalars().all()
        return [self._to_pydantic(o) for o in orms]

    def get_max_sequence(self, year: int) -> int:
        """Return the highest sequence number used for the given year (0 if none)."""
        from src.billing.invoice_numbering import InvoiceNumberer
        prefix = f"FAC-IT-{year}-"
        orms = self.session.execute(
            select(ClientInvoiceORM.invoice_number)
            .where(ClientInvoiceORM.invoice_number.like(f"{prefix}%"))
        ).scalars().all()
        max_seq = 0
        for num in orms:
            parsed = InvoiceNumberer.parse_sequence(num)
            if parsed and parsed[0] == year:
                max_seq = max(max_seq, parsed[1])
        return max_seq

    # ── Conversion ────────────────────────────────────────────────────────────

    def _to_orm(self, inv: ClientInvoice) -> ClientInvoiceORM:
        orm            = ClientInvoiceORM(**self._scalar_kwargs(inv))
        orm.line_items = [self._line_to_orm(inv.id, li) for li in inv.line_items]
        return orm

    def _update_orm(self, orm: ClientInvoiceORM, inv: ClientInvoice) -> None:
        for k, v in self._scalar_kwargs(inv).items():
            setattr(orm, k, v)
        orm.line_items.clear()
        orm.line_items.extend(self._line_to_orm(inv.id, li) for li in inv.line_items)

    @staticmethod
    def _scalar_kwargs(inv: ClientInvoice) -> dict:
        return {
            "id":                 inv.id,
            "invoice_number":     inv.invoice_number,
            "invoice_date":       inv.invoice_date,
            "due_date":           inv.due_date,
            "issuer_name":        inv.issuer_name,
            "issuer_tax_id":      inv.issuer_tax_id,
            "issuer_address":     inv.issuer_address or None,
            "client_id":          inv.client_id,
            "client_name":        inv.client_name,
            "client_tax_id":      inv.client_tax_id,
            "client_address":     inv.client_address or None,
            "amount_ht":          inv.amount_ht,
            "tva_amount":         inv.tva_amount,
            "amount_ttc":         inv.amount_ttc,
            "status":             inv.status.value,
            "source_template_id": inv.source_template_id,
            "notes":              inv.notes,
            "pdf_path":           inv.pdf_path,
            "created_at":         inv.created_at,
            "sent_at":            inv.sent_at,
            "paid_at":            inv.paid_at,
        }

    @staticmethod
    def _line_to_orm(invoice_id: UUID, li: ClientLineItem) -> ClientLineItemORM:
        return ClientLineItemORM(
            invoice_id     = invoice_id,
            description    = li.description,
            quantity       = li.quantity,
            unit_price     = li.unit_price,
            line_total     = li.line_total,
            tva_rate       = li.tva_rate,
            tva_amount     = li.tva_amount,
            compte_produit = li.compte_produit,
        )

    @staticmethod
    def _to_pydantic(orm: ClientInvoiceORM) -> ClientInvoice:
        return ClientInvoice(
            id                 = orm.id,
            invoice_number     = orm.invoice_number,
            invoice_date       = orm.invoice_date,
            due_date           = orm.due_date,
            issuer_name        = orm.issuer_name,
            issuer_tax_id      = orm.issuer_tax_id,
            issuer_address     = orm.issuer_address or "",
            client_id          = orm.client_id,
            client_name        = orm.client_name,
            client_tax_id      = orm.client_tax_id,
            client_address     = orm.client_address or "",
            line_items         = [
                ClientLineItem(
                    description    = li.description,
                    quantity       = li.quantity,
                    unit_price     = li.unit_price,
                    line_total     = li.line_total,
                    tva_rate       = li.tva_rate,
                    tva_amount     = li.tva_amount,
                    compte_produit = li.compte_produit,
                )
                for li in orm.line_items
            ],
            amount_ht          = orm.amount_ht,
            tva_amount         = orm.tva_amount,
            amount_ttc         = orm.amount_ttc,
            status             = ClientInvoiceStatus(orm.status),
            source_template_id = orm.source_template_id,
            notes              = orm.notes,
            pdf_path           = orm.pdf_path,
            created_at         = orm.created_at or datetime.now(timezone.utc),
            sent_at            = orm.sent_at,
            paid_at            = orm.paid_at,
        )
