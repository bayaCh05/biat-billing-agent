"""Unit tests for ProjectRepository — chartes, phases, fiches mensuelles."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy.orm import Session

from sqlalchemy import create_engine
from src.billing.project_repository import ProjectRepository
from src.models.project import (
    AvanceProgrammee,
    CharteProjet,
    FicheMensuelle,
    FicheStatus,
    Phase,
    PhaseStatus,
)
from src.storage.db import Base, init_db


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    init_db(engine)
    s = Session(engine)
    yield s
    s.close()
    engine.dispose()


@pytest.fixture()
def repo(session):
    return ProjectRepository(session)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _charte(**kwargs) -> CharteProjet:
    defaults = dict(
        id="CHR-2026-TEST",
        project_id="PRJ-TEST",
        project_name="Projet Test",
        valid_from=date(2026, 1, 1),
        budget_jh=100.0,
        taux_jh=850.0,
        is_active=True,
    )
    defaults.update(kwargs)
    return CharteProjet(**defaults)


def _phase(id="PH-001", project_id="PRJ-TEST", status=PhaseStatus.OPEN, **kwargs) -> Phase:
    defaults = dict(
        id=id,
        project_id=project_id,
        name="Phase Test",
        planned_jh=20.0,
        status=status,
    )
    defaults.update(kwargs)
    return Phase(**defaults)


def _fiche(id="FICHE-2026-06-001", month=6, year=2026,
           phase_ids=None, status=FicheStatus.DRAFT,
           prepared_by: str | None = None) -> FicheMensuelle:
    return FicheMensuelle(
        id=id,
        period_month=month,
        period_year=year,
        prepared_by=prepared_by or id,   # use id as prepared_by to stay unique
        prepared_at=datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc),
        phases_cloturees=phase_ids or [],
        avances=[],
        status=status,
    )


# ── CharteProjet ──────────────────────────────────────────────────────────────

class TestCharteProjet:
    def test_save_and_get(self, repo):
        c = _charte()
        repo.save_charte(c)

        got = repo.get_charte("CHR-2026-TEST")
        assert got is not None
        assert got.id == "CHR-2026-TEST"
        assert got.project_id == "PRJ-TEST"
        assert got.project_name == "Projet Test"
        assert got.budget_jh == 100.0
        assert got.taux_jh == 850.0
        assert got.is_active is True
        assert got.valid_from == date(2026, 1, 1)

    def test_get_missing_returns_none(self, repo):
        assert repo.get_charte("CHR-DOES-NOT-EXIST") is None

    def test_list_active_chartes_includes_active(self, repo):
        repo.save_charte(_charte(id="CHR-A", project_id="PRJ-A", is_active=True))
        repo.save_charte(_charte(id="CHR-B", project_id="PRJ-B", is_active=True))
        actives = repo.list_active_chartes()
        ids = [c.id for c in actives]
        assert "CHR-A" in ids
        assert "CHR-B" in ids

    def test_charte_inactive_not_in_list(self, repo):
        repo.save_charte(_charte(id="CHR-ACTIVE",   project_id="PRJ-X", is_active=True))
        repo.save_charte(_charte(id="CHR-INACTIVE", project_id="PRJ-Y", is_active=False))

        actives = repo.list_active_chartes()
        ids = [c.id for c in actives]
        assert "CHR-ACTIVE" in ids
        assert "CHR-INACTIVE" not in ids

    def test_update_charte(self, repo):
        repo.save_charte(_charte())
        updated = _charte(project_name="Nouveau nom", taux_jh=900.0)
        repo.save_charte(updated)

        got = repo.get_charte("CHR-2026-TEST")
        assert got.project_name == "Nouveau nom"
        assert got.taux_jh == 900.0


# ── Phase ─────────────────────────────────────────────────────────────────────

class TestPhase:
    def test_save_and_get(self, repo):
        repo.save_phase(_phase())
        got = repo.get_phase("PH-001")
        assert got is not None
        assert got.id == "PH-001"
        assert got.project_id == "PRJ-TEST"
        assert got.status == PhaseStatus.OPEN
        assert got.consumed_jh == 0.0
        assert got.livrables == []

    def test_get_missing_returns_none(self, repo):
        assert repo.get_phase("PH-DOES-NOT-EXIST") is None

    def test_save_and_close_phase(self, repo):
        repo.save_phase(_phase(id="PH-CLOSE"))

        closed = repo.close_phase(
            phase_id="PH-CLOSE",
            closed_date=date(2026, 6, 30),
            consumed_jh=5.0,
            livrables=["Livrable A", "Livrable B"],
        )

        assert closed.status == PhaseStatus.CLOSED
        assert closed.consumed_jh == 5.0
        assert closed.livrables == ["Livrable A", "Livrable B"]
        assert closed.closed_date == date(2026, 6, 30)

    def test_close_phase_persists(self, repo):
        repo.save_phase(_phase(id="PH-PERSIST"))
        repo.close_phase("PH-PERSIST", date(2026, 6, 30), 8.0, ["Doc finale"])

        reloaded = repo.get_phase("PH-PERSIST")
        assert reloaded.status == PhaseStatus.CLOSED
        assert reloaded.consumed_jh == 8.0
        assert reloaded.livrables == ["Doc finale"]

    def test_close_already_closed_raises(self, repo):
        repo.save_phase(_phase(id="PH-DBL"))
        repo.close_phase("PH-DBL", date(2026, 6, 30), 5.0, [])
        with pytest.raises(ValueError, match="already closed"):
            repo.close_phase("PH-DBL", date(2026, 6, 30), 5.0, [])

    def test_close_missing_phase_raises(self, repo):
        with pytest.raises(ValueError, match="not found"):
            repo.close_phase("PH-GHOST", date(2026, 6, 30), 5.0, [])

    def test_list_phases_by_project_all(self, repo):
        for i in range(3):
            repo.save_phase(_phase(id=f"PH-{i}", project_id="PRJ-LIST"))

        phases = repo.list_phases_by_project("PRJ-LIST")
        assert len(phases) == 3

    def test_list_phases_by_project_filtered(self, repo):
        repo.save_phase(_phase(id="PH-O1", project_id="PRJ-F", status=PhaseStatus.OPEN))
        repo.save_phase(_phase(id="PH-C1", project_id="PRJ-F", status=PhaseStatus.OPEN))
        repo.save_phase(_phase(id="PH-C2", project_id="PRJ-F", status=PhaseStatus.OPEN))

        # Close two of them
        repo.close_phase("PH-C1", date(2026, 5, 31), 10.0, [])
        repo.close_phase("PH-C2", date(2026, 6, 30), 15.0, [])

        all_phases = repo.list_phases_by_project("PRJ-F")
        assert len(all_phases) == 3

        closed = repo.list_phases_by_project("PRJ-F", status=PhaseStatus.CLOSED)
        assert len(closed) == 2
        assert all(p.status == PhaseStatus.CLOSED for p in closed)

        open_phases = repo.list_phases_by_project("PRJ-F", status=PhaseStatus.OPEN)
        assert len(open_phases) == 1
        assert open_phases[0].id == "PH-O1"

    def test_list_phases_different_projects_isolated(self, repo):
        repo.save_phase(_phase(id="PH-A", project_id="PRJ-A"))
        repo.save_phase(_phase(id="PH-B", project_id="PRJ-B"))

        assert len(repo.list_phases_by_project("PRJ-A")) == 1
        assert len(repo.list_phases_by_project("PRJ-B")) == 1

    def test_livrables_roundtrip(self, repo):
        repo.save_phase(_phase(id="PH-LIV"))
        repo.close_phase("PH-LIV", date(2026, 6, 30), 3.0,
                         ["Rapport d'audit", "Cartographie applicative", "Plan de migration"])

        got = repo.get_phase("PH-LIV")
        assert got.livrables == ["Rapport d'audit", "Cartographie applicative", "Plan de migration"]


# ── FicheMensuelle ────────────────────────────────────────────────────────────

class TestFicheMensuelle:
    def test_save_and_get(self, repo):
        repo.save_fiche(_fiche())

        got = repo.get_fiche("FICHE-2026-06-001")
        assert got is not None
        assert got.id == "FICHE-2026-06-001"
        assert got.period_month == 6
        assert got.period_year == 2026
        assert got.status == FicheStatus.DRAFT
        assert got.phases_cloturees == []
        assert got.avances == []

    def test_get_missing_returns_none(self, repo):
        assert repo.get_fiche("FICHE-GHOST") is None

    def test_save_fiche_with_phases(self, repo):
        repo.save_phase(_phase(id="PH-F1"))
        repo.save_phase(_phase(id="PH-F2"))

        fiche = _fiche(phase_ids=["PH-F1", "PH-F2"])
        repo.save_fiche(fiche)

        got = repo.get_fiche("FICHE-2026-06-001")
        assert sorted(got.phases_cloturees) == ["PH-F1", "PH-F2"]

    def test_save_fiche_with_avances(self, repo):
        fiche = FicheMensuelle(
            id="FICHE-AV-001",
            period_month=6,
            period_year=2026,
            prepared_by="Test",
            prepared_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
            phases_cloturees=[],
            avances=[
                AvanceProgrammee(
                    project_id="PRJ-TEST",
                    charte_id="CHR-2026-TEST",
                    description="Avance Q3",
                    montant_ht=15000.0,
                    schedule_reference="PLAN-Q3-2026",
                )
            ],
            status=FicheStatus.DRAFT,
        )
        repo.save_fiche(fiche)

        got = repo.get_fiche("FICHE-AV-001")
        assert len(got.avances) == 1
        assert got.avances[0].montant_ht == 15000.0
        assert got.avances[0].schedule_reference == "PLAN-Q3-2026"

    def test_save_and_submit_fiche(self, repo):
        repo.save_fiche(_fiche())

        submitted = repo.submit_fiche("FICHE-2026-06-001")
        assert submitted.status == FicheStatus.SUBMITTED

        # Persisted
        got = repo.get_fiche("FICHE-2026-06-001")
        assert got.status == FicheStatus.SUBMITTED

    def test_submit_already_submitted_raises(self, repo):
        repo.save_fiche(_fiche())
        repo.submit_fiche("FICHE-2026-06-001")

        with pytest.raises(ValueError):
            repo.submit_fiche("FICHE-2026-06-001")

    def test_submit_missing_fiche_raises(self, repo):
        with pytest.raises(ValueError, match="not found"):
            repo.submit_fiche("FICHE-GHOST")

    def test_list_fiches_by_year(self, repo):
        repo.save_fiche(_fiche(id="F1", month=5, year=2026))
        repo.save_fiche(_fiche(id="F2", month=6, year=2026))
        repo.save_fiche(_fiche(id="F3", month=6, year=2026))
        repo.save_fiche(_fiche(id="F4", month=1, year=2025))

        result_2026 = repo.list_fiches(2026)
        assert len(result_2026) == 3
        assert {f.id for f in result_2026} == {"F1", "F2", "F3"}

        result_2025 = repo.list_fiches(2025)
        assert len(result_2025) == 1

    def test_list_fiches_by_year_and_month(self, repo):
        repo.save_fiche(_fiche(id="F-MAY",  month=5, year=2026))
        repo.save_fiche(_fiche(id="F-JUN1", month=6, year=2026))
        repo.save_fiche(_fiche(id="F-JUN2", month=6, year=2026))

        all_2026 = repo.list_fiches(2026)
        assert len(all_2026) == 3

        june = repo.list_fiches(2026, month=6)
        assert len(june) == 2
        assert all(f.period_month == 6 for f in june)

        may = repo.list_fiches(2026, month=5)
        assert len(may) == 1
        assert may[0].id == "F-MAY"

    def test_list_fiches_empty_year(self, repo):
        assert repo.list_fiches(2099) == []

    def test_update_fiche_replaces_phases(self, repo):
        repo.save_phase(_phase(id="OLD-PH"))
        repo.save_phase(_phase(id="NEW-PH"))

        repo.save_fiche(_fiche(phase_ids=["OLD-PH"]))
        updated = _fiche(phase_ids=["NEW-PH"])
        repo.save_fiche(updated)

        got = repo.get_fiche("FICHE-2026-06-001")
        assert got.phases_cloturees == ["NEW-PH"]

    def test_mark_as_billed(self, repo):
        repo.save_fiche(_fiche())
        repo.submit_fiche("FICHE-2026-06-001")

        billed = repo.mark_as_billed("FICHE-2026-06-001", "FAC-IT-2026-0042")

        assert billed.status == FicheStatus.BILLED
        assert billed.invoice_number == "FAC-IT-2026-0042"

        # Persisted
        got = repo.get_fiche("FICHE-2026-06-001")
        assert got.status == FicheStatus.BILLED
        assert got.invoice_number == "FAC-IT-2026-0042"

    def test_mark_as_billed_not_submitted_raises(self, repo):
        repo.save_fiche(_fiche())   # DRAFT status

        with pytest.raises(ValueError, match="SUBMITTED"):
            repo.mark_as_billed("FICHE-2026-06-001", "FAC-IT-2026-0042")

    def test_mark_as_billed_missing_fiche_raises(self, repo):
        with pytest.raises(ValueError, match="not found"):
            repo.mark_as_billed("FICHE-GHOST", "FAC-IT-2026-0042")
