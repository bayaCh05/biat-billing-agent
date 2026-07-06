"""Integration test: full project billing flow end-to-end.

Strategy:
  - In-memory SQLite (init_db creates all tables via create_all for :memory: URLs)
  - Real ProjectRepository, ClientInvoiceRepository, InvoiceNumberer
  - Real MonthlyInvoiceBuilder (no mocks)
  - No LLM, no PDF, no Ollama required
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy.orm import Session

from src.billing.client_invoice_store import ClientInvoiceRepository
from src.billing.invoice_numbering import InvoiceNumberer
from src.billing.monthly_invoice_builder import MonthlyInvoiceBuilder
from src.billing.project_repository import ProjectRepository
from src.models.project import (
    AvanceProgrammee,
    CharteProjet,
    FicheMensuelle,
    FicheStatus,
    Phase,
    PhaseStatus,
)
from src.storage.db import build_engine, init_db


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def db_session():
    # build_engine("sqlite:///:memory:") enables StaticPool so all sessions
    # share the same connection — required for in-memory SQLite.
    # init_db() detects :memory: and calls Base.metadata.create_all().
    engine = build_engine("sqlite:///:memory:")
    init_db(engine)
    s = Session(engine)
    yield s
    s.close()
    engine.dispose()


@pytest.fixture()
def project_repo(db_session):
    return ProjectRepository(db_session)


@pytest.fixture()
def numberer(db_session):
    return InvoiceNumberer(ClientInvoiceRepository(db_session))


@pytest.fixture()
def builder():
    return MonthlyInvoiceBuilder(
        issuer_name="BIAT IT",
        issuer_tax_id="0000999B/A/M/000",
        issuer_address="Zone Urbaine Nord, Tunis",
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_full_billing_flow(project_repo, builder, numberer):
    """Charte → phase → close → fiche → submit → invoice."""

    # 1. Create charte
    charte = CharteProjet(
        id="CHR-E2E-001",
        project_id="P-E2E",
        project_name="Test Project E2E",
        client="BIAT",
        valid_from=date(2026, 1, 1),
        budget_jh=50.0,
        taux_jh=800.0,
        is_active=True,
    )
    project_repo.save_charte(charte)

    # 2. Create and close a phase
    phase = Phase(
        id="PH-E2E-01",
        project_id="P-E2E",
        name="Analyse",
        planned_jh=10.0,
        consumed_jh=0.0,
        status=PhaseStatus.OPEN,
        livrables=[],
    )
    project_repo.save_phase(phase)
    project_repo.close_phase(
        "PH-E2E-01",
        date(2026, 6, 1),
        consumed_jh=8.0,
        livrables=["Rapport d'analyse"],
    )

    # 3. Build fiche as DRAFT and submit it
    fiche = FicheMensuelle(
        id="FICHE-E2E-001",
        period_month=6,
        period_year=2026,
        prepared_by="test-e2e",
        prepared_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        phases_cloturees=["PH-E2E-01"],
        avances=[],
        status=FicheStatus.DRAFT,
    )
    project_repo.save_fiche(fiche)
    submitted_fiche = project_repo.submit_fiche("FICHE-E2E-001")
    assert submitted_fiche.status == FicheStatus.SUBMITTED

    # 4. Build invoice from submitted fiche
    invoice = builder.build_from_fiche(submitted_fiche, project_repo, numberer)

    # 5. Core assertions
    assert len(invoice.line_items) == 1
    line = invoice.line_items[0]

    assert line.quantity == pytest.approx(8.0)
    assert line.unit_price == pytest.approx(800.0)
    assert line.line_total == pytest.approx(6_400.0)   # 8 × 800
    assert invoice.amount_ht == pytest.approx(6_400.0)

    assert "BIAT" in invoice.client_name
    assert invoice.invoice_number.startswith("FAC-IT-")
    assert "FICHE-E2E-001" in (invoice.notes or "")


def test_billing_flow_with_avance(project_repo, builder, numberer):
    """Phase + advance line — both appear in invoice, totals correct."""

    charte = CharteProjet(
        id="CHR-E2E-002",
        project_id="P-AV",
        project_name="Project Avance",
        client="BIAT",
        valid_from=date(2026, 1, 1),
        budget_jh=100.0,
        taux_jh=850.0,
        is_active=True,
    )
    project_repo.save_charte(charte)
    project_repo.save_phase(Phase(
        id="PH-AV-01", project_id="P-AV", name="Phase A",
        planned_jh=20.0, consumed_jh=0.0, status=PhaseStatus.OPEN,
    ))
    project_repo.close_phase("PH-AV-01", date(2026, 6, 15), 12.0, ["Doc A"])

    fiche = FicheMensuelle(
        id="FICHE-AV-001",
        period_month=6,
        period_year=2026,
        prepared_by="test-e2e-av",
        prepared_at=datetime(2026, 6, 15, tzinfo=timezone.utc),
        phases_cloturees=["PH-AV-01"],
        avances=[
            AvanceProgrammee(
                project_id="P-AV",
                charte_id="CHR-E2E-002",
                description="Avance Q3",
                montant_ht=20_000.0,
                schedule_reference="PLAN-2026-Q3",
            )
        ],
        status=FicheStatus.SUBMITTED,
    )
    project_repo.save_fiche(fiche)

    invoice = builder.build_from_fiche(fiche, project_repo, numberer)

    assert len(invoice.line_items) == 2

    phase_line  = next(l for l in invoice.line_items if l.compte_produit == "7061")
    avance_line = next(l for l in invoice.line_items if l.compte_produit == "4191")

    assert phase_line.line_total  == pytest.approx(12 * 850)   # 10 200
    assert avance_line.line_total == pytest.approx(20_000.0)
    assert invoice.amount_ht      == pytest.approx(12 * 850 + 20_000.0)

    # B2B intra-group: TVA must be 0
    assert invoice.tva_amount == pytest.approx(0.0)
    assert invoice.amount_ttc == pytest.approx(invoice.amount_ht)


def test_invoice_number_increments(db_session, project_repo, builder, numberer):
    """Sequential invoice builds using a saved first invoice produce distinct numbers.

    InvoiceNumberer reads MAX(sequence) from ClientInvoiceRepository — the first
    invoice must be persisted before building the second so the numberer can see it.
    """
    import re
    from src.billing.client_invoice_store import ClientInvoiceRepository

    client_inv_repo = ClientInvoiceRepository(db_session)

    charte = CharteProjet(
        id="CHR-SEQ", project_id="P-SEQ", project_name="Seq",
        client="BIAT", valid_from=date(2026, 1, 1),
        budget_jh=50.0, taux_jh=800.0, is_active=True,
    )
    project_repo.save_charte(charte)

    for i in range(1, 3):
        project_repo.save_phase(Phase(
            id=f"PH-SEQ-{i}", project_id="P-SEQ", name=f"Phase {i}",
            planned_jh=5.0, consumed_jh=0.0, status=PhaseStatus.OPEN,
        ))
        project_repo.close_phase(f"PH-SEQ-{i}", date(2026, 6, i), 5.0, [])

    fiche1 = FicheMensuelle(
        id="FICHE-SEQ-1", period_month=5, period_year=2026,
        prepared_by="seq-1",
        prepared_at=datetime(2026, 5, 31, tzinfo=timezone.utc),
        phases_cloturees=["PH-SEQ-1"], avances=[],
        status=FicheStatus.SUBMITTED,
    )
    fiche2 = FicheMensuelle(
        id="FICHE-SEQ-2", period_month=6, period_year=2026,
        prepared_by="seq-2",
        prepared_at=datetime(2026, 6, 30, tzinfo=timezone.utc),
        phases_cloturees=["PH-SEQ-2"], avances=[],
        status=FicheStatus.SUBMITTED,
    )
    project_repo.save_fiche(fiche1)
    project_repo.save_fiche(fiche2)

    inv1 = builder.build_from_fiche(fiche1, project_repo, numberer)
    # Persist inv1 so InvoiceNumberer can read the MAX sequence for the next call
    client_inv_repo.save(inv1)

    inv2 = builder.build_from_fiche(fiche2, project_repo, numberer)

    assert inv1.invoice_number != inv2.invoice_number
    pattern = re.compile(r"^FAC-IT-\d{4}-\d{4}$")
    assert pattern.match(inv1.invoice_number)
    assert pattern.match(inv2.invoice_number)


def test_empty_fiche_raises(project_repo, builder, numberer):
    """A fiche with no phases and no avances must raise ValueError."""
    fiche = FicheMensuelle(
        id="FICHE-EMPTY",
        period_month=6, period_year=2026,
        prepared_by="test-empty",
        prepared_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        phases_cloturees=[], avances=[],
        status=FicheStatus.SUBMITTED,
    )
    project_repo.save_fiche(fiche)

    with pytest.raises(ValueError, match="no billable lines"):
        builder.build_from_fiche(fiche, project_repo, numberer)
