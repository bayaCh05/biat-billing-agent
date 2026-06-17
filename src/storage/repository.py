from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import and_, func, select, text
from sqlalchemy.orm import Session

from src.models.enums import ChargeNature, ChargeType, InvoiceStatus
from src.models.invoice import ConfidenceField, InvoiceRecord, LineItem, ValidationFlag
from src.storage.orm_models import (
    CONFIDENCE_FIELD_NAMES,
    InvoiceORM,
    LineItemORM,
    StatusHistoryORM,
    ValidationFlagORM,
)


class InvoiceRepository:
    """CRUD and query interface for InvoiceRecord.

    The public API works exclusively with Pydantic InvoiceRecord objects.
    ORM models are an internal concern — callers never see them.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    # ── Write ─────────────────────────────────────────────────────────────────

    def save(self, invoice: InvoiceRecord, changed_by: str = "agent") -> InvoiceRecord:
        """Insert or update an invoice. Writes a status_history row on status change."""
        existing: InvoiceORM | None = self.session.get(InvoiceORM, invoice.id)

        if existing is None:
            orm = self._to_orm(invoice)
            self.session.add(orm)
            self.session.add(
                StatusHistoryORM(
                    invoice_id=invoice.id,
                    from_status=None,
                    to_status=invoice.status.value,
                    changed_by=changed_by,
                )
            )
        else:
            if existing.status != invoice.status.value:
                self.session.add(
                    StatusHistoryORM(
                        invoice_id=invoice.id,
                        from_status=existing.status,
                        to_status=invoice.status.value,
                        changed_by=changed_by,
                    )
                )
            self._update_orm(existing, invoice)

        self.session.commit()
        return invoice

    def delete(self, invoice_id: str | UUID) -> None:
        """Hard-delete an invoice and its related rows (flags, line items, history)."""
        from sqlalchemy import delete as sa_delete
        uid = UUID(str(invoice_id)) if isinstance(invoice_id, str) else invoice_id
        uid_str = uid.hex  # SQLite stores UUIDs as hex strings without dashes
        # Delete child rows in FK order before the parent to satisfy constraints.
        for tbl in ("validation_flags", "line_items", "status_history"):
            self.session.execute(
                text(f"DELETE FROM {tbl} WHERE invoice_id = :id"), {"id": uid_str}
            )
        self.session.execute(
            text("DELETE FROM invoices WHERE id = :id"), {"id": uid_str}
        )
        self.session.commit()

    # ── Read ──────────────────────────────────────────────────────────────────

    def get_by_id(self, invoice_id: UUID) -> InvoiceRecord | None:
        orm = self.session.get(InvoiceORM, invoice_id)
        return self._to_pydantic(orm) if orm else None

    def get_by_hash(self, file_hash: str) -> InvoiceRecord | None:
        orm = self.session.execute(
            select(InvoiceORM).where(InvoiceORM.file_hash == file_hash)
        ).scalar_one_or_none()
        return self._to_pydantic(orm) if orm else None

    def get_by_status(self, status: InvoiceStatus) -> list[InvoiceRecord]:
        orms = self.session.execute(
            select(InvoiceORM).where(InvoiceORM.status == status.value)
        ).scalars().all()
        return [self._to_pydantic(o) for o in orms]

    def get_stuck_invoices(self, timeout_minutes: int) -> list[InvoiceRecord]:
        """Return invoices in transition states not updated in > timeout_minutes."""
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)
        transition_statuses = [
            InvoiceStatus.EXTRACTING, InvoiceStatus.CLASSIFYING,
            InvoiceStatus.VALIDATING, InvoiceStatus.EXPORTING,
            InvoiceStatus.JOURNALING,
        ]
        orms = self.session.execute(
            select(InvoiceORM).where(
                and_(
                    InvoiceORM.status.in_([s.value for s in transition_statuses]),
                    InvoiceORM.updated_at < cutoff,
                )
            )
        ).scalars().all()
        return [self._to_pydantic(o) for o in orms]

    def count_by_status(self, statuses: list[InvoiceStatus] | None = None) -> dict[str, int]:
        """Return {status_value: count} in a single GROUP BY query.

        If statuses is provided, only those statuses are counted.
        Also returns human_review_required totals for auto-approval rate calculation.
        """
        stmt = (
            select(InvoiceORM.status, func.count(InvoiceORM.id))
            .group_by(InvoiceORM.status)
        )
        if statuses:
            stmt = stmt.where(InvoiceORM.status.in_([s.value for s in statuses]))
        rows = self.session.execute(stmt).all()
        return {status: count for status, count in rows}

    def count_auto_approved(self, statuses: list[InvoiceStatus]) -> tuple[int, int]:
        """Return (total, auto_approved) for the given terminal statuses in 2 queries."""
        status_vals = [s.value for s in statuses]
        total = self.session.execute(
            select(func.count(InvoiceORM.id))
            .where(InvoiceORM.status.in_(status_vals))
        ).scalar_one() or 0
        auto = self.session.execute(
            select(func.count(InvoiceORM.id))
            .where(
                and_(
                    InvoiceORM.status.in_(status_vals),
                    InvoiceORM.human_review_required == False,  # noqa: E712
                )
            )
        ).scalar_one() or 0
        return total, auto

    def list_all(self) -> list[InvoiceRecord]:
        orms = self.session.execute(select(InvoiceORM)).scalars().all()
        return [self._to_pydantic(o) for o in orms]

    def get_flagged(self) -> list[InvoiceRecord]:
        orms = self.session.execute(
            select(InvoiceORM)
            .where(InvoiceORM.status == InvoiceStatus.FLAGGED.value)
            .order_by(InvoiceORM.received_at.asc())
        ).scalars().all()
        return [self._to_pydantic(o) for o in orms]

    def find_potential_duplicates(
        self,
        invoice_number: str,
        issuer_tax_id: str,
        window_days: int,
        exclude_id: UUID | None = None,
    ) -> list[InvoiceRecord]:
        """Return invoices with the same issuer+number within the duplicate window."""
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=window_days)
        conditions = [
            InvoiceORM.issuer_tax_id == issuer_tax_id,
            InvoiceORM.invoice_number == invoice_number,
            InvoiceORM.received_at >= cutoff,
            InvoiceORM.status != InvoiceStatus.REJECTED.value,
        ]
        if exclude_id is not None:
            conditions.append(InvoiceORM.id != exclude_id)
        orms = self.session.execute(
            select(InvoiceORM).where(and_(*conditions))
        ).scalars().all()
        return [self._to_pydantic(o) for o in orms]

    def find_near_duplicates(
        self,
        issuer_name: str,
        amount_ttc: float,
        window_days: int,
        exclude_id: UUID | None = None,
        relative_tolerance: float = 0.01,
    ) -> list[InvoiceRecord]:
        """Return invoices from the same issuer with a very close amount (within 1% by default)."""
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=window_days)
        tol = max(0.02, amount_ttc * relative_tolerance)
        conditions = [
            InvoiceORM.issuer_name == issuer_name,
            InvoiceORM.amount_ttc.between(amount_ttc - tol, amount_ttc + tol),
            InvoiceORM.received_at >= cutoff,
            InvoiceORM.status != InvoiceStatus.REJECTED.value,
        ]
        if exclude_id is not None:
            conditions.append(InvoiceORM.id != exclude_id)
        orms = self.session.execute(
            select(InvoiceORM).where(and_(*conditions))
        ).scalars().all()
        return [self._to_pydantic(o) for o in orms]

    def get_historical_amounts(self, issuer_tax_id: str) -> list[float]:
        """Return all past amount_ttc values for a given issuer (for anomaly detection)."""
        rows = self.session.execute(
            select(InvoiceORM.amount_ttc).where(
                and_(
                    InvoiceORM.issuer_tax_id == issuer_tax_id,
                    InvoiceORM.amount_ttc.is_not(None),
                    InvoiceORM.status != InvoiceStatus.REJECTED.value,
                )
            )
        ).scalars().all()
        return list(rows)

    def get_pending_payment(self) -> list[InvoiceRecord]:
        from src.models.enums import InvoiceDirection
        orms = self.session.execute(
            select(InvoiceORM).where(
                and_(
                    InvoiceORM.direction == InvoiceDirection.SUPPLIER.value,
                    InvoiceORM.status == InvoiceStatus.EXPORTED.value,
                    InvoiceORM.paid_at.is_(None),
                )
            )
        ).scalars().all()
        return [self._to_pydantic(o) for o in orms]

    def get_pending_collection(self) -> list[InvoiceRecord]:
        from src.models.enums import InvoiceDirection
        orms = self.session.execute(
            select(InvoiceORM).where(
                and_(
                    InvoiceORM.direction == InvoiceDirection.CLIENT.value,
                    InvoiceORM.status == InvoiceStatus.EXPORTED.value,
                    InvoiceORM.collected_at.is_(None),
                )
            )
        ).scalars().all()
        return [self._to_pydantic(o) for o in orms]

    def get_overdue(self) -> list[InvoiceRecord]:
        today = datetime.now(tz=timezone.utc).date()
        orms = self.session.execute(
            select(InvoiceORM).where(
                and_(
                    InvoiceORM.due_date < today,
                    InvoiceORM.paid_at.is_(None),
                    InvoiceORM.status == InvoiceStatus.EXPORTED.value,
                )
            )
        ).scalars().all()
        return [self._to_pydantic(o) for o in orms]

    # ── ORM ↔ Pydantic conversion ─────────────────────────────────────────────

    def _to_orm(self, invoice: InvoiceRecord) -> InvoiceORM:
        kwargs = self._scalar_kwargs(invoice)
        orm = InvoiceORM(**kwargs)
        orm.line_items = self._build_line_item_orms(invoice)
        orm.flags = self._build_flag_orms(invoice)
        return orm

    def _update_orm(self, orm: InvoiceORM, invoice: InvoiceRecord) -> None:
        for key, value in self._scalar_kwargs(invoice).items():
            setattr(orm, key, value)
        orm.line_items.clear()
        orm.line_items.extend(self._build_line_item_orms(invoice))
        orm.flags.clear()
        orm.flags.extend(self._build_flag_orms(invoice))

    def _scalar_kwargs(self, invoice: InvoiceRecord) -> dict:
        kwargs: dict = {
            "id": invoice.id,
            "file_hash": invoice.file_hash,
            "raw_file_path": invoice.raw_file_path,
            "file_mime_type": invoice.file_mime_type,
            "direction": invoice.direction.value,
            "status": invoice.status.value,
            "extraction_method": invoice.extraction_method.value if invoice.extraction_method else None,
            "retry_count": invoice.retry_count,
            "last_error": invoice.last_error,
            "currency": invoice.currency,
            "raw_extracted_json": invoice.raw_extracted_json,
            "cost_catalog_id": invoice.cost_catalog_id,
            "accounting_compte": invoice.accounting_compte,
            "accounting_label": invoice.accounting_label,
            "charge_nature": invoice.charge_nature.value if invoice.charge_nature else None,
            "charge_type": invoice.charge_type.value if invoice.charge_type else None,
            "matched_po_id": invoice.matched_po_id,
            "matched_contract_id": invoice.matched_contract_id,
            "matched_client_id": invoice.matched_client_id,
            "human_review_required": invoice.human_review_required,
            "human_review_notes": invoice.human_review_notes,
            "reviewed_by": invoice.reviewed_by,
            "reviewed_at": invoice.reviewed_at,
            "received_at": invoice.received_at,
            "extracted_at": invoice.extracted_at,
            "classified_at": invoice.classified_at,
            "validated_at": invoice.validated_at,
            "exported_at": invoice.exported_at,
            "export_reference": invoice.export_reference,
            "paid_at": invoice.paid_at,
            "collected_at": invoice.collected_at,
            "created_at": invoice.created_at,
            "updated_at": invoice.updated_at,
        }
        # Unpack all ConfidenceField objects into two columns each
        for field_name in CONFIDENCE_FIELD_NAMES:
            cf = getattr(invoice, field_name)
            kwargs[field_name] = cf.value
            kwargs[f"{field_name}_conf"] = cf.confidence if cf.value is not None else None
        return kwargs

    def _to_pydantic(self, orm: InvoiceORM) -> InvoiceRecord:
        from src.models.enums import ExtractionMethod, InvoiceDirection

        invoice = InvoiceRecord(
            id=orm.id,
            file_hash=orm.file_hash,
            raw_file_path=orm.raw_file_path,
            file_mime_type=orm.file_mime_type,
            direction=InvoiceDirection(orm.direction),
            status=InvoiceStatus(orm.status),
            extraction_method=ExtractionMethod(orm.extraction_method) if orm.extraction_method else None,
            retry_count=orm.retry_count,
            last_error=orm.last_error,
            currency=orm.currency,
            raw_extracted_json=orm.raw_extracted_json,
            cost_catalog_id=orm.cost_catalog_id,
            accounting_compte=orm.accounting_compte,
            accounting_label=orm.accounting_label,
            charge_nature=ChargeNature(orm.charge_nature) if orm.charge_nature else None,
            charge_type=ChargeType(orm.charge_type) if orm.charge_type else None,
            matched_po_id=orm.matched_po_id,
            matched_contract_id=orm.matched_contract_id,
            matched_client_id=orm.matched_client_id,
            human_review_required=orm.human_review_required,
            human_review_notes=orm.human_review_notes,
            reviewed_by=orm.reviewed_by,
            reviewed_at=orm.reviewed_at,
            received_at=orm.received_at or datetime.now(tz=timezone.utc),
            extracted_at=orm.extracted_at,
            classified_at=orm.classified_at,
            validated_at=orm.validated_at,
            exported_at=orm.exported_at,
            export_reference=orm.export_reference,
            paid_at=orm.paid_at,
            collected_at=orm.collected_at,
            created_at=orm.created_at or datetime.now(tz=timezone.utc),
            updated_at=orm.updated_at or datetime.now(tz=timezone.utc),
        )

        # Restore ConfidenceField objects
        for field_name in CONFIDENCE_FIELD_NAMES:
            value = getattr(orm, field_name)
            confidence = getattr(orm, f"{field_name}_conf") or 0.0
            setattr(invoice, field_name, ConfidenceField(value=value, confidence=confidence))

        # Restore line items
        invoice.line_items = [
            LineItem(
                line_number=li.line_number,
                description=li.description,
                quantity=li.quantity,
                unit_price=li.unit_price,
                line_total=li.line_total,
                tva_rate=li.tva_rate,
            )
            for li in orm.line_items
        ]

        # Restore validation flags
        from src.models.enums import FlagSeverity, FlagType
        invoice.flags = [
            ValidationFlag(
                flag_type=FlagType(f.flag_type),
                severity=FlagSeverity(f.severity),
                field_name=f.field_name,
                message=f.message,
                resolved=f.resolved,
                resolved_at=f.resolved_at,
                resolved_by=f.resolved_by,
            )
            for f in orm.flags
        ]

        return invoice

    # ── Related object builders ────────────────────────────────────────────────

    def _build_line_item_orms(self, invoice: InvoiceRecord) -> list[LineItemORM]:
        return [
            LineItemORM(
                invoice_id=invoice.id,
                line_number=li.line_number,
                description=li.description,
                quantity=li.quantity,
                unit_price=li.unit_price,
                line_total=li.line_total,
                tva_rate=li.tva_rate,
            )
            for li in invoice.line_items
        ]

    def _build_flag_orms(self, invoice: InvoiceRecord) -> list[ValidationFlagORM]:
        return [
            ValidationFlagORM(
                invoice_id=invoice.id,
                flag_type=f.flag_type.value,
                severity=f.severity.value,
                field_name=f.field_name,
                message=f.message,
                resolved=f.resolved,
                resolved_at=f.resolved_at,
                resolved_by=f.resolved_by,
            )
            for f in invoice.flags
        ]
