"""Tests unitaires du module cost_catalog."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.cost_catalog.catalog import CostCatalog
from src.models.enums import ChargeFlux, ChargeNature, ChargeType, Recurrence

CATALOG_PATH = Path("config/cost_catalog.yaml")

# Catalogue minimal inline pour les tests (indépendant du fichier YAML)
_YAML_CONTENT = """
entries:
  - id: maintenance_informatique
    label: Maintenance et support informatique
    compte: "6112"
    nature: fixe
    type_charge: OPEX
    tva_rate: 19
    recurrence: mensuelle
    flux: fournisseur
    keywords: [maintenance informatique, support informatique, infogérance, TMA]

  - id: licences_saas
    label: Licences logiciels et abonnements SaaS
    compte: "6133"
    nature: fixe
    type_charge: OPEX
    tva_rate: 19
    recurrence: mensuelle
    flux: fournisseur
    keywords: [logiciel, licence, SaaS, abonnement logiciel]

  - id: electricite_steg
    label: Électricité (STEG)
    compte: "6241"
    nature: semi_variable
    type_charge: OPEX
    tva_rate: 19
    recurrence: mensuelle
    flux: fournisseur
    keywords: [électricité, STEG, énergie électrique]

  - id: prestations_si
    label: Prestations de services informatiques
    compte: "7061"
    nature: variable
    type_charge: OPEX
    tva_rate: 19
    recurrence: mensuelle
    flux: client
    keywords: [prestation informatique, service informatique, forfait mensuel]

  - id: materiel_informatique
    label: Matériel informatique
    compte: "2183"
    nature: fixe
    type_charge: CAPEX
    tva_rate: 19
    recurrence: ponctuelle
    flux: fournisseur
    keywords: [serveur, ordinateur, PC, écran, switch]
"""


@pytest.fixture
def catalog(tmp_path) -> CostCatalog:
    yaml_file = tmp_path / "test_catalog.yaml"
    yaml_file.write_text(_YAML_CONTENT, encoding="utf-8")
    return CostCatalog.from_yaml(yaml_file)


# ── Chargement ────────────────────────────────────────────────────────────────

class TestCatalogLoading:
    def test_loads_all_entries(self, catalog):
        assert len(catalog) == 5

    def test_entry_fields_parsed(self, catalog):
        entry = catalog.get("maintenance_informatique")
        assert entry is not None
        assert entry.compte == "6112"
        assert entry.nature == ChargeNature.FIXE
        assert entry.type_charge == ChargeType.OPEX
        assert entry.tva_rate == 19.0
        assert entry.recurrence == Recurrence.MENSUELLE
        assert entry.flux == ChargeFlux.FOURNISSEUR

    def test_capex_entry_parsed(self, catalog):
        entry = catalog.get("materiel_informatique")
        assert entry is not None
        assert entry.type_charge == ChargeType.CAPEX
        assert entry.compte == "2183"

    def test_client_flux_parsed(self, catalog):
        entry = catalog.get("prestations_si")
        assert entry is not None
        assert entry.flux == ChargeFlux.CLIENT

    def test_load_production_catalog(self):
        """Le fichier de production doit se charger sans erreur."""
        if not CATALOG_PATH.exists():
            pytest.skip("config/cost_catalog.yaml not found")
        cat = CostCatalog.from_yaml(CATALOG_PATH)
        assert len(cat) > 20, "Le catalogue de production doit avoir au moins 20 entrées"


# ── Validation tva_rate au chargement ───────────────────────────────────────────

class TestCatalogTvaValidation:
    """tva_rates_allowed est optionnel — quand fourni, chaque tva_rate du
    catalogue est comparé (comportement précédent : aucune validation,
    tva_rate par défaut à 19% en silence si absent du YAML)."""

    def test_no_tva_rates_allowed_skips_validation(self, tmp_path, monkeypatch):
        """Paramètre omis (comportement par défaut, inchangé) : aucune
        validation, aucun log, même avec un taux non tunisien."""
        from src.cost_catalog import catalog as catalog_module
        mock_warning = MagicMock()
        monkeypatch.setattr(catalog_module.logger, "warning", mock_warning)

        bad_yaml = _YAML_CONTENT.replace("tva_rate: 19", "tva_rate: 18", 1)
        yaml_file = tmp_path / "bad.yaml"
        yaml_file.write_text(bad_yaml, encoding="utf-8")

        cat = CostCatalog.from_yaml(yaml_file)  # tva_rates_allowed omitted

        assert len(cat) == 5
        mock_warning.assert_not_called()

    def test_valid_rates_no_warning(self, tmp_path, monkeypatch):
        from src.cost_catalog import catalog as catalog_module
        mock_warning = MagicMock()
        monkeypatch.setattr(catalog_module.logger, "warning", mock_warning)

        yaml_file = tmp_path / "valid.yaml"
        yaml_file.write_text(_YAML_CONTENT, encoding="utf-8")  # all entries at tva_rate: 19
        CostCatalog.from_yaml(yaml_file, tva_rates_allowed=[0, 7, 13, 19])

        mock_warning.assert_not_called()

    def test_invalid_rate_logs_warning_but_does_not_raise(self, tmp_path, monkeypatch):
        from src.cost_catalog import catalog as catalog_module
        mock_warning = MagicMock()
        monkeypatch.setattr(catalog_module.logger, "warning", mock_warning)

        bad_yaml = _YAML_CONTENT.replace("tva_rate: 19", "tva_rate: 18", 1)
        yaml_file = tmp_path / "bad.yaml"
        yaml_file.write_text(bad_yaml, encoding="utf-8")

        cat = CostCatalog.from_yaml(yaml_file, tva_rates_allowed=[0, 7, 13, 19])

        mock_warning.assert_called_once()
        assert mock_warning.call_args.kwargs["tva_rate"] == 18.0
        # The suspect rate is kept as-is (not silently coerced to a valid one)
        # — the entry is still usable, only flagged for a human to review.
        assert any(e.tva_rate == 18.0 for e in cat.all_entries())


# ── Correspondance (match) ────────────────────────────────────────────────────

class TestCatalogMatch:
    def test_exact_keyword_match(self, catalog):
        entry = catalog.match("Facture maintenance informatique serveurs")
        assert entry is not None
        assert entry.id == "maintenance_informatique"

    def test_match_with_accents(self, catalog):
        # "électricité" avec accent doit matcher l'entrée electricite_steg
        entry = catalog.match("Facture électricité mois de mars 2024 STEG")
        assert entry is not None
        assert entry.id == "electricite_steg"

    def test_match_keyword_case_insensitive(self, catalog):
        entry = catalog.match("LICENCE Microsoft Office 365 annuelle")
        assert entry is not None
        assert entry.id == "licences_saas"

    def test_flux_filter_fournisseur(self, catalog):
        # "prestation informatique" existe dans client + fournisseur → flux filter isole client
        entry = catalog.match(
            "Prestation informatique forfait mensuel",
            flux=ChargeFlux.CLIENT,
        )
        assert entry is not None
        assert entry.flux == ChargeFlux.CLIENT

    def test_flux_filter_excludes_wrong_flux(self, catalog):
        # "prestation informatique" ne doit PAS matcher fournisseur si flux=CLIENT
        entry = catalog.match(
            "maintenance informatique serveur",
            flux=ChargeFlux.CLIENT,
        )
        # maintenance_informatique est flux=fournisseur → doit être exclu
        assert entry is None or entry.flux == ChargeFlux.CLIENT

    def test_empty_text_returns_none(self, catalog):
        assert catalog.match("") is None
        assert catalog.match("   ") is None

    def test_unrelated_text_returns_none(self, catalog):
        entry = catalog.match("xyzzy foobar qux", min_score=70)
        assert entry is None

    def test_min_score_threshold(self, catalog):
        # Score max possible (keywords exactement présents) — doit matcher même à 99
        entry = catalog.match("maintenance informatique serveur", min_score=99)
        assert entry is not None

        # Score trop élevé pour un texte vague — doit pas matcher
        entry_strict = catalog.match("travaux divers", min_score=99)
        assert entry_strict is None

    def test_capex_keyword_match(self, catalog):
        entry = catalog.match("Acquisition serveur Dell PowerEdge R740")
        assert entry is not None
        assert entry.id == "materiel_informatique"
        assert entry.type_charge == ChargeType.CAPEX


# ── Correspondance avec score (match_with_score) ───────────────────────────────

class TestCatalogMatchWithScore:
    """match_with_score() est le nouveau chemin utilisé par AccountingCoder pour
    obtenir la vraie confiance au lieu d'une valeur fixe — voir
    classification_agent.py et accounting_coder.py."""

    def test_exact_match_returns_max_score(self, catalog):
        entry, score = catalog.match_with_score("Facture maintenance informatique serveurs")
        assert entry is not None
        assert entry.id == "maintenance_informatique"
        assert score == 100

    def test_empty_text_returns_none_and_zero(self, catalog):
        entry, score = catalog.match_with_score("")
        assert entry is None
        assert score == 0

    def test_no_match_returns_none_and_zero(self, catalog):
        entry, score = catalog.match_with_score("xyzzy foobar qux", min_score=70)
        assert entry is None
        assert score == 0

    def test_match_consistent_with_plain_match(self, catalog):
        """match() est maintenant un simple wrapper autour de match_with_score() —
        les deux doivent toujours retourner la même entrée."""
        text = "LICENCE Microsoft Office 365 annuelle"
        entry_plain = catalog.match(text)
        entry_scored, score = catalog.match_with_score(text)
        assert entry_plain is entry_scored
        assert score >= 70


# ── Accesseurs ────────────────────────────────────────────────────────────────

class TestCatalogAccessors:
    def test_get_by_id(self, catalog):
        entry = catalog.get("licences_saas")
        assert entry is not None
        assert entry.label == "Licences logiciels et abonnements SaaS"

    def test_get_unknown_id_returns_none(self, catalog):
        assert catalog.get("nonexistent_id") is None

    def test_all_entries_returns_copy(self, catalog):
        entries = catalog.all_entries()
        assert len(entries) == 5
        # Modifications de la liste retournée ne doivent pas affecter le catalog
        entries.clear()
        assert len(catalog.all_entries()) == 5

    def test_entries_by_flux_fournisseur(self, catalog):
        fournisseur = catalog.entries_by_flux(ChargeFlux.FOURNISSEUR)
        assert all(e.flux == ChargeFlux.FOURNISSEUR for e in fournisseur)
        assert len(fournisseur) == 4  # maintenance, licences, electricite, materiel

    def test_entries_by_flux_client(self, catalog):
        clients = catalog.entries_by_flux(ChargeFlux.CLIENT)
        assert len(clients) == 1
        assert clients[0].id == "prestations_si"
