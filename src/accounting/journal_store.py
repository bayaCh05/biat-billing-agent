"""Persistance du journal comptable (SQLAlchemy).

JournalEntryORM / JournalLineORM : tables SQL.
JournalRepository : API CRUD — ne retourne que des objets Pydantic.
"""
from __future__ import annotations

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, String, Text, func, select, and_
from sqlalchemy import Uuid
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from src.models.journal import JournalEntry, JournalLine
from src.storage.db import Base


# ── ORM ───────────────────────────────────────────────────────────────────────

class JournalLineORM(Base):
    __tablename__ = "journal_lines"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    entry_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("journal_entries.id", ondelete="CASCADE"),
        nullable=False,
    )
    compte: Mapped[str] = mapped_column(String(16), nullable=False)
    libelle: Mapped[str] = mapped_column(Text, nullable=False)
    debit: Mapped[float | None] = mapped_column(Float)
    credit: Mapped[float | None] = mapped_column(Float)

    entry: Mapped["JournalEntryORM"] = relationship("JournalEntryORM", back_populates="lines")


class JournalEntryORM(Base):
    __tablename__ = "journal_entries"
    __table_args__ = (
        Index("idx_journal_date", "date_ecriture"),
        Index("idx_journal_invoice", "source_invoice_id"),
        Index("idx_journal_reference", "reference"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    reference: Mapped[str] = mapped_column(String(128), nullable=False)
    date_ecriture: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    source_invoice_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    source_asset_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())

    lines: Mapped[list[JournalLineORM]] = relationship(
        "JournalLineORM",
        back_populates="entry",
        cascade="all, delete-orphan",
        order_by="JournalLineORM.id",
    )


# ── Repository ────────────────────────────────────────────────────────────────

class JournalRepository:
    """CRUD pour les écritures comptables.

    L'API publique ne manipule que des objets Pydantic JournalEntry.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, entry: JournalEntry) -> JournalEntry:
        existing = self.session.get(JournalEntryORM, entry.id)
        if existing is None:
            orm = self._to_orm(entry)
            self.session.add(orm)
        else:
            existing.reference = entry.reference
            existing.date_ecriture = entry.date_ecriture
            existing.description = entry.description
            existing.source_invoice_id = entry.source_invoice_id
            existing.source_asset_id = entry.source_asset_id
            existing.lines.clear()
            existing.lines.extend(self._build_line_orms(entry))
        self.session.commit()
        return entry

    def get_by_id(self, entry_id: UUID) -> JournalEntry | None:
        orm = self.session.get(JournalEntryORM, entry_id)
        return self._to_pydantic(orm) if orm else None

    def get_by_invoice(self, invoice_id: UUID) -> list[JournalEntry]:
        orms = self.session.execute(
            select(JournalEntryORM).where(
                JournalEntryORM.source_invoice_id == invoice_id
            )
        ).scalars().all()
        return [self._to_pydantic(o) for o in orms]

    def get_by_date_range(self, start: date, end: date) -> list[JournalEntry]:
        orms = self.session.execute(
            select(JournalEntryORM).where(
                and_(
                    JournalEntryORM.date_ecriture >= start,
                    JournalEntryORM.date_ecriture <= end,
                )
            ).order_by(JournalEntryORM.date_ecriture)
        ).scalars().all()
        return [self._to_pydantic(o) for o in orms]

    def list_entries(
        self,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[JournalEntry]:
        """Return all journal entries ordered by date descending, with optional pagination."""
        q = select(JournalEntryORM).order_by(JournalEntryORM.date_ecriture.desc())
        if offset:
            q = q.offset(offset)
        if limit is not None:
            q = q.limit(limit)
        orms = self.session.execute(q).scalars().all()
        return [self._to_pydantic(o) for o in orms]

    def get_by_compte(self, compte: str, start: date, end: date) -> list[JournalEntry]:
        """Retourne toutes les écritures touchant un compte donné sur la période."""
        orms = self.session.execute(
            select(JournalEntryORM)
            .join(JournalLineORM, JournalLineORM.entry_id == JournalEntryORM.id)
            .where(
                and_(
                    JournalLineORM.compte == compte,
                    JournalEntryORM.date_ecriture >= start,
                    JournalEntryORM.date_ecriture <= end,
                )
            )
            .distinct()
        ).scalars().all()
        return [self._to_pydantic(o) for o in orms]

    # ── ORM ↔ Pydantic ────────────────────────────────────────────────────────

    def _to_orm(self, entry: JournalEntry) -> JournalEntryORM:
        orm = JournalEntryORM(
            id=entry.id,
            reference=entry.reference,
            date_ecriture=entry.date_ecriture,
            description=entry.description,
            source_invoice_id=entry.source_invoice_id,
            source_asset_id=entry.source_asset_id,
            created_at=entry.created_at,
        )
        orm.lines = self._build_line_orms(entry)
        return orm

    @staticmethod
    def _build_line_orms(entry: JournalEntry) -> list[JournalLineORM]:
        return [
            JournalLineORM(
                entry_id=entry.id,
                compte=line.compte,
                libelle=line.libelle,
                debit=line.debit,
                credit=line.credit,
            )
            for line in entry.lines
        ]

    @staticmethod
    def _to_pydantic(orm: JournalEntryORM) -> JournalEntry:
        return JournalEntry(
            id=orm.id,
            reference=orm.reference,
            date_ecriture=orm.date_ecriture,
            description=orm.description,
            source_invoice_id=orm.source_invoice_id,
            source_asset_id=orm.source_asset_id,
            created_at=orm.created_at or datetime.utcnow(),
            lines=[
                JournalLine(
                    compte=line.compte,
                    libelle=line.libelle,
                    debit=line.debit,
                    credit=line.credit,
                )
                for line in orm.lines
            ],
        )
