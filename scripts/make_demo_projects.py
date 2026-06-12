"""Insert demo project data: 3 chartes, phases, a fiche mensuelle, and asset links."""
from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.agent.config_loader import load_config
from src.billing.project_repository import ProjectRepository
from src.capex.asset_repository import AssetRepository
from src.models.cost_allocation import AssetProjectLink
from src.models.project import (
    AvanceProgrammee,
    CharteProjet,
    FicheMensuelle,
    FicheStatus,
    Phase,
    PhaseStatus,
)
from src.storage.db import build_engine, build_session_factory, init_db

cfg     = load_config()
engine  = build_engine(cfg["storage"]["db_url"])
init_db(engine)
sf      = build_session_factory(engine)

project_repo = ProjectRepository(sf())
asset_repo   = AssetRepository(sf())

today = date.today()

# ── 1. CharteProjet records ───────────────────────────────────────────────────

CHARTES = [
    CharteProjet(
        id="CHR-2026-0001",
        project_id="PRJ-CBK",
        project_name="Migration Core Banking",
        client="BIAT",
        valid_from=date(2026, 1, 1),
        valid_until=date(2026, 12, 31),
        budget_jh=240.0,
        taux_jh=850.0,
        is_active=True,
    ),
    CharteProjet(
        id="CHR-2026-0002",
        project_id="PRJ-PCD",
        project_name="Portail Client Digital",
        client="BIAT",
        valid_from=date(2026, 2, 1),
        valid_until=date(2026, 12, 31),
        budget_jh=180.0,
        taux_jh=850.0,
        is_active=True,
    ),
    CharteProjet(
        id="CHR-2026-0003",
        project_id="PRJ-IC",
        project_name="Infrastructure Cloud",
        client="BIAT",
        valid_from=date(2026, 3, 1),
        valid_until=date(2027, 3, 31),
        budget_jh=120.0,
        taux_jh=850.0,
        is_active=True,
    ),
]

print("Saving chartes…")
for c in CHARTES:
    project_repo.save_charte(c)
    print(f"  ✓ {c.id} — {c.project_name}")

# ── 2. Phases ─────────────────────────────────────────────────────────────────

PHASES = [
    # CBK — 3 phases, 2 closed
    Phase(id="PH-CBK-01", project_id="PRJ-CBK", name="Analyse et audit du SI existant",
          planned_jh=40.0, consumed_jh=38.0, status=PhaseStatus.CLOSED,
          closed_date=date(2026, 3, 31),
          livrables=["Rapport d'audit SI", "Cartographie applicative"]),
    Phase(id="PH-CBK-02", project_id="PRJ-CBK", name="Conception architecture cible",
          planned_jh=60.0, consumed_jh=55.5, status=PhaseStatus.CLOSED,
          closed_date=date(2026, 5, 30),
          livrables=["DAT Architecture", "Plan de migration v1"]),
    Phase(id="PH-CBK-03", project_id="PRJ-CBK", name="Développement et tests d'intégration",
          planned_jh=140.0, consumed_jh=0.0, status=PhaseStatus.OPEN),

    # PCD — 2 phases, 1 closed
    Phase(id="PH-PCD-01", project_id="PRJ-PCD", name="UX Research et maquettage",
          planned_jh=30.0, consumed_jh=28.0, status=PhaseStatus.CLOSED,
          closed_date=date(2026, 4, 15),
          livrables=["Rapport UX", "Maquettes Figma validées", "Cahier des charges UI"]),
    Phase(id="PH-PCD-02", project_id="PRJ-PCD", name="Développement front-end React",
          planned_jh=150.0, consumed_jh=0.0, status=PhaseStatus.OPEN),

    # IC — 2 phases, 1 closed
    Phase(id="PH-IC-01", project_id="PRJ-IC", name="Évaluation et choix du provider cloud",
          planned_jh=20.0, consumed_jh=18.0, status=PhaseStatus.CLOSED,
          closed_date=date(2026, 5, 15),
          livrables=["Benchmark AWS/Azure/OVH", "Recommandation technique", "Devis comparatifs"]),
    Phase(id="PH-IC-02", project_id="PRJ-IC", name="Déploiement infrastructure IaC",
          planned_jh=100.0, consumed_jh=0.0, status=PhaseStatus.OPEN),
]

print("\nSaving phases…")
for p in PHASES:
    project_repo.save_phase(p)
    status = "✅ Clôturée" if p.status == PhaseStatus.CLOSED else "🔵 Ouverte"
    print(f"  {status}  {p.id} — {p.name}")

# ── 3. FicheMensuelle for current month ───────────────────────────────────────

closed_phase_ids = [p.id for p in PHASES if p.status == PhaseStatus.CLOSED]

fiche = FicheMensuelle(
    id=f"FICHE-{today.year}-{today.month:02d}-DEMO",
    period_month=today.month,
    period_year=today.year,
    prepared_by="Demo Script",
    prepared_at=datetime.now(timezone.utc),
    phases_cloturees=closed_phase_ids,
    avances=[
        AvanceProgrammee(
            project_id="PRJ-IC",
            charte_id="CHR-2026-0003",
            description="Avance sur déploiement infrastructure Q3 2026",
            montant_ht=25500.0,
            schedule_reference="PLAN-IC-Q3-2026",
        )
    ],
    status=FicheStatus.DRAFT,
)

print(f"\nSaving fiche mensuelle {fiche.id}…")
project_repo.save_fiche(fiche)
print(f"  ✓ {len(closed_phase_ids)} phases clôturées + 1 avance")

# ── 4. AssetProjectLink — distribute existing assets ─────────────────────────

assets = asset_repo.list_all(include_fully_depreciated=True)
if not assets:
    print("\n⚠️  No assets found in DB — skipping AssetProjectLink creation.")
    print("   Add assets via the Immobilisations page first.")
else:
    print(f"\nDistributing {len(assets)} asset(s) across projects…")

    # Simple distribution: spread assets across 3 projects
    PROJECT_IDS = ["PRJ-CBK", "PRJ-PCD", "PRJ-IC"]
    # Default split: 50% CBK / 30% PCD / 20% IC for all assets
    SPLITS = [
        ("PRJ-CBK", 50.0),
        ("PRJ-PCD", 30.0),
        ("PRJ-IC",  20.0),
    ]

    for asset in assets:
        print(f"  {asset.designation} ({asset.id})")
        for pid, pct in SPLITS:
            link = AssetProjectLink(
                asset_id=str(asset.id),
                project_id=pid,
                allocation_pct=pct,
            )
            asset_repo.save_link(link)
            print(f"    → {pid}: {pct}%")

print("\n✅ Demo data loaded successfully.")
print(f"\n   Chartes  : {len(CHARTES)}")
print(f"   Phases   : {len(PHASES)} ({len(closed_phase_ids)} clôturées)")
print(f"   Fiche    : {fiche.id} (DRAFT — {today.month:02d}/{today.year})")
print(f"   Assets   : {len(assets)} linked to 3 projects")
print("\nNext: open the Facturation page → Tab 1 to see chartes,")
print("      Tab 2 to generate the monthly invoice.")
