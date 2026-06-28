"""CRUD repository for project chartes, phases, and monthly billing fiches."""
from __future__ import annotations

import json
from datetime import date
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from src.models.project import (
    AvanceProgrammee,
    CharteProjet,
    FicheMensuelle,
    FicheStatus,
    Phase,
    PhaseStatus,
)
from src.storage.orm_models_projects import (
    AvanceProgrammeeORM,
    CharteProjetORM,
    FicheMensuelleORM,
    FichePhaseORM,
    PhaseORM,
)


class ProjectRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # ── CharteProjet ──────────────────────────────────────────────────────────

    def save_charte(self, charte: CharteProjet) -> None:
        existing = self.session.get(CharteProjetORM, charte.id)
        if existing is None:
            self.session.add(self._charte_to_orm(charte))
        else:
            self._update_charte_orm(existing, charte)
        self.session.commit()

    def get_charte(self, id: str) -> CharteProjet | None:
        orm = self.session.get(CharteProjetORM, id)
        return self._charte_to_pydantic(orm) if orm else None

    def list_active_chartes(self) -> list[CharteProjet]:
        orms = self.session.execute(
            select(CharteProjetORM).where(CharteProjetORM.is_active == True)  # noqa: E712
        ).scalars().all()
        return [self._charte_to_pydantic(o) for o in orms]

    def get_charte_for_project(self, project_id: str) -> CharteProjet | None:
        orm = self.session.execute(
            select(CharteProjetORM)
            .where(CharteProjetORM.project_id == project_id,
                   CharteProjetORM.is_active == True)  # noqa: E712
            .order_by(CharteProjetORM.valid_from.desc())
            .limit(1)
        ).scalar_one_or_none()
        return self._charte_to_pydantic(orm) if orm else None

    # ── Phase ─────────────────────────────────────────────────────────────────

    def save_phase(self, phase: Phase) -> None:
        existing = self.session.get(PhaseORM, phase.id)
        if existing is None:
            self.session.add(self._phase_to_orm(phase))
        else:
            self._update_phase_orm(existing, phase)
        self.session.commit()

    def get_phase(self, id: str) -> Phase | None:
        orm = self.session.get(PhaseORM, id)
        return self._phase_to_pydantic(orm) if orm else None

    def list_phases_by_project(
        self,
        project_id: str,
        status: PhaseStatus | None = None,
    ) -> list[Phase]:
        stmt = select(PhaseORM).where(PhaseORM.project_id == project_id)
        if status is not None:
            stmt = stmt.where(PhaseORM.status == status.value)
        orms = self.session.execute(stmt).scalars().all()
        return [self._phase_to_pydantic(o) for o in orms]

    def close_phase(
        self,
        phase_id: str,
        closed_date: date,
        consumed_jh: float,
        livrables: list[str],
    ) -> Phase:
        orm = self.session.get(PhaseORM, phase_id)
        if orm is None:
            raise ValueError(f"Phase not found: {phase_id}")
        if orm.status == PhaseStatus.CLOSED.value:
            raise ValueError(f"Phase {phase_id} is already closed")
        orm.status = PhaseStatus.CLOSED.value
        orm.closed_date = closed_date
        orm.consumed_jh = consumed_jh
        orm.livrables = json.dumps(livrables, ensure_ascii=False)
        self.session.commit()
        return self._phase_to_pydantic(orm)

    # ── FicheMensuelle ────────────────────────────────────────────────────────

    def save_fiche(self, fiche: FicheMensuelle) -> None:
        existing = self.session.get(FicheMensuelleORM, fiche.id)
        if existing is None:
            orm = self._fiche_to_orm(fiche)
            self.session.add(orm)
        else:
            self._update_fiche_orm(existing, fiche)
            # Rebuild phase links
            self.session.execute(
                FichePhaseORM.__table__.delete().where(
                    FichePhaseORM.fiche_id == fiche.id
                )
            )
            for pid in fiche.phases_cloturees:
                self.session.add(FichePhaseORM(fiche_id=fiche.id, phase_id=pid))
            # Rebuild avances
            self.session.execute(
                AvanceProgrammeeORM.__table__.delete().where(
                    AvanceProgrammeeORM.fiche_id == fiche.id
                )
            )
            for av in fiche.avances:
                self.session.add(self._avance_to_orm(fiche.id, av))
        self.session.commit()

    def get_fiche(self, id: str) -> FicheMensuelle | None:
        orm = self.session.get(FicheMensuelleORM, id)
        if orm is None:
            return None
        return self._fiche_to_pydantic(orm)

    def list_fiches(self, year: int, month: int | None = None) -> list[FicheMensuelle]:
        # PERF: eager loading to avoid N+1 queries
        stmt = (
            select(FicheMensuelleORM)
            .options(
                selectinload(FicheMensuelleORM.phase_links),
                selectinload(FicheMensuelleORM.avances),
            )
            .where(FicheMensuelleORM.period_year == year)
        )
        if month is not None:
            stmt = stmt.where(FicheMensuelleORM.period_month == month)
        stmt = stmt.order_by(FicheMensuelleORM.period_month)
        orms = self.session.execute(stmt).scalars().all()
        return [self._fiche_to_pydantic(o) for o in orms]

    def submit_fiche(self, fiche_id: str) -> FicheMensuelle:
        orm = self.session.get(FicheMensuelleORM, fiche_id)
        if orm is None:
            raise ValueError(f"Fiche not found: {fiche_id}")
        if orm.status != FicheStatus.DRAFT.value:
            raise ValueError(f"Fiche {fiche_id} is not in DRAFT status")
        orm.status = FicheStatus.SUBMITTED.value
        self.session.commit()
        return self._fiche_to_pydantic(orm)

    def mark_as_billed(self, fiche_id: str, invoice_number: str) -> FicheMensuelle:
        orm = self.session.get(FicheMensuelleORM, fiche_id)
        if orm is None:
            raise ValueError(f"Fiche {fiche_id} not found")
        if orm.status != FicheStatus.SUBMITTED.value:
            raise ValueError(
                f"Cannot bill fiche {fiche_id} in status '{orm.status}' "
                "(must be SUBMITTED)"
            )
        orm.status = FicheStatus.BILLED.value
        orm.invoice_number = invoice_number
        self.session.commit()
        return self._fiche_to_pydantic(orm)

    # ── ORM ↔ Pydantic: CharteProjet ─────────────────────────────────────────

    @staticmethod
    def _charte_to_orm(c: CharteProjet) -> CharteProjetORM:
        return CharteProjetORM(
            id=c.id,
            project_id=c.project_id,
            project_name=c.project_name,
            client=c.client,
            valid_from=c.valid_from,
            valid_until=c.valid_until,
            budget_jh=c.budget_jh,
            taux_jh=c.taux_jh,
            is_active=c.is_active,
        )

    @staticmethod
    def _update_charte_orm(orm: CharteProjetORM, c: CharteProjet) -> None:
        orm.project_id   = c.project_id
        orm.project_name = c.project_name
        orm.client       = c.client
        orm.valid_from   = c.valid_from
        orm.valid_until  = c.valid_until
        orm.budget_jh    = c.budget_jh
        orm.taux_jh      = c.taux_jh
        orm.is_active    = c.is_active

    @staticmethod
    def _charte_to_pydantic(orm: CharteProjetORM) -> CharteProjet:
        return CharteProjet(
            id=orm.id,
            project_id=orm.project_id,
            project_name=orm.project_name,
            client=orm.client,
            valid_from=orm.valid_from,
            valid_until=orm.valid_until,
            budget_jh=orm.budget_jh,
            taux_jh=orm.taux_jh,
            is_active=orm.is_active,
        )

    # ── ORM ↔ Pydantic: Phase ─────────────────────────────────────────────────

    @staticmethod
    def _phase_to_orm(p: Phase) -> PhaseORM:
        return PhaseORM(
            id=p.id,
            project_id=p.project_id,
            name=p.name,
            description=p.description,
            planned_jh=p.planned_jh,
            consumed_jh=p.consumed_jh,
            status=p.status.value,
            closed_date=p.closed_date,
            livrables=json.dumps(p.livrables, ensure_ascii=False),
        )

    @staticmethod
    def _update_phase_orm(orm: PhaseORM, p: Phase) -> None:
        orm.project_id  = p.project_id
        orm.name        = p.name
        orm.description = p.description
        orm.planned_jh  = p.planned_jh
        orm.consumed_jh = p.consumed_jh
        orm.status      = p.status.value
        orm.closed_date = p.closed_date
        orm.livrables   = json.dumps(p.livrables, ensure_ascii=False)

    @staticmethod
    def _phase_to_pydantic(orm: PhaseORM) -> Phase:
        try:
            livrables = json.loads(orm.livrables) if orm.livrables else []
        except (json.JSONDecodeError, TypeError):
            livrables = []
        return Phase(
            id=orm.id,
            project_id=orm.project_id,
            name=orm.name,
            description=orm.description or "",
            planned_jh=orm.planned_jh,
            consumed_jh=orm.consumed_jh,
            status=PhaseStatus(orm.status),
            closed_date=orm.closed_date,
            livrables=livrables,
        )

    # ── ORM ↔ Pydantic: FicheMensuelle ────────────────────────────────────────

    def _fiche_to_orm(self, f: FicheMensuelle) -> FicheMensuelleORM:
        orm = FicheMensuelleORM(
            id=f.id,
            period_month=f.period_month,
            period_year=f.period_year,
            prepared_by=f.prepared_by,
            prepared_at=f.prepared_at,
            status=f.status.value,
            invoice_number=f.invoice_number,
        )
        for pid in f.phases_cloturees:
            orm.phase_links.append(FichePhaseORM(fiche_id=f.id, phase_id=pid))
        for av in f.avances:
            orm.avances.append(self._avance_to_orm(f.id, av))
        return orm

    @staticmethod
    def _update_fiche_orm(orm: FicheMensuelleORM, f: FicheMensuelle) -> None:
        orm.period_month    = f.period_month
        orm.period_year     = f.period_year
        orm.prepared_by     = f.prepared_by
        orm.prepared_at     = f.prepared_at
        orm.status          = f.status.value
        orm.invoice_number  = f.invoice_number

    def _fiche_to_pydantic(self, orm: FicheMensuelleORM) -> FicheMensuelle:
        phase_ids = [lnk.phase_id for lnk in orm.phase_links]
        avances = [
            AvanceProgrammee(
                project_id=av.project_id,
                charte_id=av.charte_id,
                description=av.description,
                montant_ht=av.montant_ht,
                schedule_reference=av.schedule_reference,
            )
            for av in orm.avances
        ]
        return FicheMensuelle(
            id=orm.id,
            period_month=orm.period_month,
            period_year=orm.period_year,
            prepared_by=orm.prepared_by,
            prepared_at=orm.prepared_at,
            phases_cloturees=phase_ids,
            avances=avances,
            status=FicheStatus(orm.status),
            invoice_number=orm.invoice_number,
        )

    @staticmethod
    def _avance_to_orm(fiche_id: str, av: AvanceProgrammee) -> AvanceProgrammeeORM:
        return AvanceProgrammeeORM(
            id=uuid4(),
            fiche_id=fiche_id,
            project_id=av.project_id,
            charte_id=av.charte_id,
            description=av.description,
            montant_ht=av.montant_ht,
            schedule_reference=av.schedule_reference,
        )
