"""Unit tests for MonthlyInvoiceBuilder — monthly ClientInvoice construction."""
from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import MagicMock

import pytest

from src.billing.monthly_invoice_builder import MonthlyInvoiceBuilder
from src.models.client_invoice import ClientInvoice
from src.models.project import (
    AvanceProgrammee,
    CharteProjet,
    FicheMensuelle,
    FicheStatus,
    Phase,
    PhaseStatus,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def builder():
    return MonthlyInvoiceBuilder(
        issuer_name="BIAT IT",
        issuer_tax_id="0000999B/A/M/000",
        issuer_address="Zone Urbaine Nord, Tunis",
    )


@pytest.fixture()
def sample_charte():
    return CharteProjet(
        id="CHR-2026-001",
        project_id="PROJ-CORE",
        project_name="Migration Core Banking",
        client="BIAT",
        valid_from=date(2026, 1, 1),
        budget_jh=120.0,
        taux_jh=800.0,
        is_active=True,
    )


@pytest.fixture()
def closed_phase():
    return Phase(
        id="PH-001",
        project_id="PROJ-CORE",
        name="Phase 1 - Analyse",
        planned_jh=20.0,
        consumed_jh=18.0,
        status=PhaseStatus.CLOSED,
        closed_date=date(2026, 6, 1),
        livrables=["Cahier des charges", "Matrice des besoins"],
    )


def _project_repo(charte=None, phase=None):
    """Return a MagicMock ProjectRepository wired with the given objects."""
    repo = MagicMock()
    repo.get_phase.return_value = phase
    repo.get_charte_for_project.return_value = charte
    return repo


def _numberer(number="FAC-IT-2026-0001"):
    n = MagicMock()
    n.next_number.return_value = number
    return n


def _fiche(phase_ids=None, avances=None, id="FICHE-2026-06-001"):
    return FicheMensuelle(
        id=id,
        period_month=6,
        period_year=2026,
        prepared_by="BIAT IT",
        prepared_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        phases_cloturees=phase_ids or [],
        avances=avances or [],
        status=FicheStatus.SUBMITTED,
    )


# ── Phase line items ──────────────────────────────────────────────────────────

class TestPhaseLine:
    def test_single_phase_produces_one_line(self, builder, sample_charte, closed_phase):
        fiche = _fiche(phase_ids=["PH-001"])
        repo = _project_repo(charte=sample_charte, phase=closed_phase)

        inv = builder.build_from_fiche(fiche, repo, _numberer())

        assert len(inv.line_items) == 1

    def test_phase_line_amount(self, builder, sample_charte, closed_phase):
        fiche = _fiche(phase_ids=["PH-001"])
        repo = _project_repo(charte=sample_charte, phase=closed_phase)

        inv = builder.build_from_fiche(fiche, repo, _numberer())
        line = inv.line_items[0]

        assert line.quantity == 18.0
        assert line.unit_price == 800.0
        assert line.line_total == pytest.approx(14_400.0)   # 18 × 800
        assert line.compte_produit == "7061"
        assert line.charte_reference == "CHR-2026-001"
        assert line.phase_id == "PH-001"

    def test_phase_line_description_contains_jh(self, builder, sample_charte, closed_phase):
        fiche = _fiche(phase_ids=["PH-001"])
        repo = _project_repo(charte=sample_charte, phase=closed_phase)

        inv = builder.build_from_fiche(fiche, repo, _numberer())
        line = inv.line_items[0]
        desc = line.description

        assert "18" in desc
        assert "JH" in desc
        assert "Cahier des charges" in desc
        # Charte reference is stored on the line object, not embedded in description text
        assert line.charte_reference == "CHR-2026-001"

    def test_phase_line_tva_is_zero(self, builder, sample_charte, closed_phase):
        fiche = _fiche(phase_ids=["PH-001"])
        repo = _project_repo(charte=sample_charte, phase=closed_phase)

        line = builder.build_from_fiche(fiche, repo, _numberer()).line_items[0]

        assert line.tva_rate == 0.0
        assert line.tva_amount == 0.0

    def test_zero_jh_phase_excluded(self, builder, sample_charte):
        zero_phase = Phase(
            id="PH-ZERO",
            project_id="PROJ-CORE",
            name="Empty phase",
            planned_jh=10.0,
            consumed_jh=0.0,
            status=PhaseStatus.CLOSED,
        )
        fiche = _fiche(phase_ids=["PH-ZERO"])
        repo = _project_repo(charte=sample_charte, phase=zero_phase)

        with pytest.raises(ValueError, match="no billable lines"):
            builder.build_from_fiche(fiche, repo, _numberer())

    def test_missing_phase_skipped(self, builder, sample_charte):
        fiche = _fiche(phase_ids=["PH-GHOST"])
        repo = _project_repo(charte=sample_charte, phase=None)   # phase not found

        with pytest.raises(ValueError, match="no billable lines"):
            builder.build_from_fiche(fiche, repo, _numberer())

    def test_missing_charte_skipped(self, builder, closed_phase):
        fiche = _fiche(phase_ids=["PH-001"])
        repo = _project_repo(charte=None, phase=closed_phase)    # charte not found

        with pytest.raises(ValueError, match="no billable lines"):
            builder.build_from_fiche(fiche, repo, _numberer())


# ── Avance lines ──────────────────────────────────────────────────────────────

class TestAvanceLine:
    def _avance(self, project_id="PROJ-PORTAL", montant_ht=15_000.0,
                ref="PLAN-2026-Q3"):
        return AvanceProgrammee(
            project_id=project_id,
            charte_id="CHR-2026-002",
            description="Avance sur développement portail",
            montant_ht=montant_ht,
            schedule_reference=ref,
        )

    def test_avance_only_produces_one_line(self, builder):
        fiche = _fiche(avances=[self._avance()])
        repo = MagicMock()

        inv = builder.build_from_fiche(fiche, repo, _numberer())

        assert len(inv.line_items) == 1

    def test_avance_line_fields(self, builder):
        fiche = _fiche(avances=[self._avance()])
        repo = MagicMock()

        line = builder.build_from_fiche(fiche, repo, _numberer()).line_items[0]

        assert line.compte_produit == "4191"
        assert line.line_total == pytest.approx(15_000.0)
        assert line.unit_price == pytest.approx(15_000.0)
        assert line.quantity == 1
        assert line.tva_rate == 0.0
        assert line.charte_reference == "CHR-2026-002"

    def test_avance_description_contains_reference(self, builder):
        fiche = _fiche(avances=[self._avance(ref="PLAN-2026-Q3")])
        repo = MagicMock()

        desc = builder.build_from_fiche(fiche, repo, _numberer()).line_items[0].description

        assert "PLAN-2026-Q3" in desc


# ── Mixed phase + avance ──────────────────────────────────────────────────────

class TestMixed:
    def test_total_ht_phase_plus_avance(self, builder, sample_charte, closed_phase):
        avance = AvanceProgrammee(
            project_id="PROJ-PORTAL",
            charte_id="CHR-2026-002",
            description="Avance Q3",
            montant_ht=15_000.0,
            schedule_reference="PLAN-Q3",
        )
        fiche = _fiche(phase_ids=["PH-001"], avances=[avance])
        repo = _project_repo(charte=sample_charte, phase=closed_phase)

        inv = builder.build_from_fiche(fiche, repo, _numberer())

        assert len(inv.line_items) == 2
        # 18 JH × 800 = 14 400  +  15 000  =  29 400
        assert inv.amount_ht == pytest.approx(29_400.0)

    def test_two_phases_summed(self, builder, sample_charte):
        phase_a = Phase(id="PH-A", project_id="PROJ-CORE", name="Phase A",
                        planned_jh=10.0, consumed_jh=10.0, status=PhaseStatus.CLOSED)
        phase_b = Phase(id="PH-B", project_id="PROJ-CORE", name="Phase B",
                        planned_jh=5.0,  consumed_jh=5.0,  status=PhaseStatus.CLOSED)

        repo = MagicMock()
        repo.get_phase.side_effect = lambda pid: phase_a if pid == "PH-A" else phase_b
        repo.get_charte_for_project.return_value = sample_charte

        fiche = _fiche(phase_ids=["PH-A", "PH-B"])
        inv = builder.build_from_fiche(fiche, repo, _numberer())

        assert len(inv.line_items) == 2
        assert inv.amount_ht == pytest.approx(12_000.0)   # (10 + 5) × 800


# ── Invoice-level assertions ──────────────────────────────────────────────────

class TestInvoiceMeta:
    def test_client_is_always_biat(self, builder, sample_charte, closed_phase):
        fiche = _fiche(phase_ids=["PH-001"])
        repo = _project_repo(charte=sample_charte, phase=closed_phase)

        inv = builder.build_from_fiche(fiche, repo, _numberer())

        assert "BIAT" in inv.client_name

    def test_invoice_number_format(self, builder, sample_charte, closed_phase):
        fiche = _fiche(phase_ids=["PH-001"])
        repo = _project_repo(charte=sample_charte, phase=closed_phase)
        numberer = _numberer("FAC-IT-2026-0042")

        inv = builder.build_from_fiche(fiche, repo, numberer)

        assert inv.invoice_number == "FAC-IT-2026-0042"
        assert inv.invoice_number.startswith("FAC-IT-")

    def test_notes_contains_fiche_id(self, builder, sample_charte, closed_phase):
        fiche = _fiche(phase_ids=["PH-001"], id="FICHE-2026-06-XYZ")
        repo = _project_repo(charte=sample_charte, phase=closed_phase)

        inv = builder.build_from_fiche(fiche, repo, _numberer())

        assert "FICHE-2026-06-XYZ" in (inv.notes or "")

    def test_issuer_fields(self, builder, sample_charte, closed_phase):
        fiche = _fiche(phase_ids=["PH-001"])
        repo = _project_repo(charte=sample_charte, phase=closed_phase)

        inv = builder.build_from_fiche(fiche, repo, _numberer())

        assert inv.issuer_name == "BIAT IT"
        assert inv.issuer_tax_id == "0000999B/A/M/000"

    def test_tva_zero_means_ht_equals_ttc(self, builder, sample_charte, closed_phase):
        fiche = _fiche(phase_ids=["PH-001"])
        repo = _project_repo(charte=sample_charte, phase=closed_phase)

        inv = builder.build_from_fiche(fiche, repo, _numberer())

        assert inv.tva_amount == pytest.approx(0.0)
        assert inv.amount_ht == pytest.approx(inv.amount_ttc)

    def test_empty_fiche_raises_value_error(self, builder):
        fiche = _fiche(phase_ids=[], avances=[])
        repo = MagicMock()

        with pytest.raises(ValueError, match="no billable lines"):
            builder.build_from_fiche(fiche, repo, _numberer())
