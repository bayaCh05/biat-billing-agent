"""SQLAlchemy ORM for budget lines, roadmap items, livrables, and risks."""
from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy import Uuid
from sqlalchemy.orm import Mapped, mapped_column

from src.storage.db import Base


class LigneBudgetORM(Base):
    __tablename__ = "lignes_budget"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    projet_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    categorie: Mapped[str] = mapped_column(String(128), nullable=False)
    montant_prevu: Mapped[float] = mapped_column(Float, nullable=False)
    montant_consomme: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    devise: Mapped[str] = mapped_column(String(8), nullable=False, default="TND")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class FeuilleDeRouteORM(Base):
    __tablename__ = "feuilles_de_route"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    titre: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    date_debut: Mapped[date] = mapped_column(Date, nullable=False)
    date_fin: Mapped[date] = mapped_column(Date, nullable=False)
    projet_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    responsable_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    statut: Mapped[str] = mapped_column(String(16), nullable=False, default="PLANIFIE")
    priorite: Mapped[str] = mapped_column(String(8), nullable=False, default="MOYENNE")
    annee: Mapped[int] = mapped_column(Integer, nullable=False, default=2026)


class LivrableORM(Base):
    __tablename__ = "livrables"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    phase_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("phases.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    titre: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    date_livraison_prevue: Mapped[date] = mapped_column(Date, nullable=False)
    date_livraison_reelle: Mapped[date | None] = mapped_column(Date, nullable=True)
    statut: Mapped[str] = mapped_column(String(16), nullable=False, default="EN_ATTENTE")
    fichier_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")


class RisqueORM(Base):
    __tablename__ = "risques"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    titre: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    type_risque: Mapped[str] = mapped_column(String(32), nullable=False, default="AUTRE")
    probabilite: Mapped[str] = mapped_column(String(16), nullable=False)
    impact: Mapped[str] = mapped_column(String(16), nullable=False)
    niveau_criticite: Mapped[str] = mapped_column(String(16), nullable=False)
    statut: Mapped[str] = mapped_column(String(24), nullable=False, default="IDENTIFIE")
    plan_mitigation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    responsable_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    date_identification: Mapped[date] = mapped_column(Date, nullable=False)
    date_echeance_mitigation: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_cloture: Mapped[date | None] = mapped_column(Date, nullable=True)
    feuille_route_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("feuilles_de_route.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    projet_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
