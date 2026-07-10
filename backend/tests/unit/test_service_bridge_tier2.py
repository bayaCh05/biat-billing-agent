"""Unit tests — service_bridge.py Tier 2 (budget/CAPEX/risks/roadmap writes).

Second scoping tier — business-logic writes: wrong data here is a real
business problem but not the security/financial-integrity risk Tier 1
covered. create_budget_plan_entry_native already had tests (from the
unique-index-collision fix); the other 16 live functions in this domain
did not.
"""
from __future__ import annotations

import asyncio
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.storage.documents.service_bridge import (
    close_risk_native,
    create_asset_native,
    create_budget_line_native,
    create_livrable_native,
    create_risk_native,
    create_roadmap_item_native,
    delete_budget_line_native,
    delete_budget_plan_entry_native,
    delete_roadmap_item_native,
    seed_budget_plan_from_yaml_native,
    update_budget_line_native,
    update_budget_plan_entry_native,
    update_livrable_native,
    update_risk_native,
    update_roadmap_item_native,
    valider_phase_native,
    PhaseValidationError,
)


def _run(coro):
    return asyncio.run(coro)


def _find_chain(return_value):
    chain = MagicMock()
    chain.to_list = AsyncMock(return_value=return_value)
    return chain


_FIXED_UUID = "12345678-1234-1234-1234-123456789012"


class TestCreateRoadmapItemNative:
    def test_inserts_and_returns_created_item(self):
        body = SimpleNamespace(
            titre="Migration Mongo", description="", date_debut=date(2026, 1, 1),
            date_fin=date(2026, 6, 30), projet_id="proj-1", responsable_id=None,
            statut="PLANIFIE", priorite="HAUTE", annee=2026,
        )
        created = SimpleNamespace(id="item-1", titre="Migration Mongo")
        coll = MagicMock()
        coll.insert_one = AsyncMock()
        with (
            patch(
                "src.storage.documents.feuille_de_route.FeuilleDeRouteDocument.get_pymongo_collection",
                return_value=coll,
            ),
            patch(
                "src.storage.documents.service_bridge._get_by_str_id",
                new=AsyncMock(return_value=created),
            ),
        ):
            result = _run(create_roadmap_item_native(body))

        assert result is created
        doc = coll.insert_one.call_args[0][0]
        assert doc["titre"] == "Migration Mongo"
        assert doc["annee"] == 2026


class TestUpdateRoadmapItemNative:
    def test_returns_none_when_not_found(self):
        with patch(
            "src.storage.documents.service_bridge._get_by_str_id",
            new=AsyncMock(return_value=None),
        ):
            body = SimpleNamespace(titre="X", description=None, date_debut=None, date_fin=None,
                                    statut=None, priorite=None, projet_id=None)
            result = _run(update_roadmap_item_native(_FIXED_UUID, body))
        assert result is None

    def test_updates_only_provided_fields(self):
        item = SimpleNamespace(id=_FIXED_UUID)
        coll = MagicMock()
        coll.update_one = AsyncMock()
        body = SimpleNamespace(titre=None, description=None, date_debut=None, date_fin=None,
                                statut="EN_COURS", priorite=None, projet_id=None)
        with (
            patch(
                "src.storage.documents.service_bridge._get_by_str_id",
                new=AsyncMock(return_value=item),
            ),
            patch(
                "src.storage.documents.feuille_de_route.FeuilleDeRouteDocument.get_pymongo_collection",
                return_value=coll,
            ),
        ):
            _run(update_roadmap_item_native(_FIXED_UUID, body))
        update = coll.update_one.call_args[0][1]["$set"]
        assert update == {"statut": "EN_COURS"}


class TestDeleteRoadmapItemNative:
    def test_returns_false_when_not_found(self):
        with patch(
            "src.storage.documents.service_bridge._get_by_str_id",
            new=AsyncMock(return_value=None),
        ):
            result = _run(delete_roadmap_item_native(_FIXED_UUID))
        assert result is False

    def test_cascades_to_linked_risks(self):
        item = SimpleNamespace(id=_FIXED_UUID)
        coll_fr = MagicMock()
        coll_fr.delete_one = AsyncMock()
        coll_risk = MagicMock()
        coll_risk.delete_many = AsyncMock()
        with (
            patch(
                "src.storage.documents.service_bridge._get_by_str_id",
                new=AsyncMock(return_value=item),
            ),
            patch(
                "src.storage.documents.feuille_de_route.FeuilleDeRouteDocument.get_pymongo_collection",
                return_value=coll_fr,
            ),
            patch(
                "src.storage.documents.risque.RisqueDocument.get_pymongo_collection",
                return_value=coll_risk,
            ),
        ):
            result = _run(delete_roadmap_item_native(_FIXED_UUID))
        assert result is True
        coll_fr.delete_one.assert_awaited_once_with({"_id": _FIXED_UUID})
        coll_risk.delete_many.assert_awaited_once_with({"feuille_route_id": _FIXED_UUID})


class TestCreateLivrableNative:
    def test_returns_none_when_phase_not_found(self):
        with patch(
            "src.storage.documents.phase.PhaseDocument.get",
            new=AsyncMock(return_value=None),
        ):
            body = SimpleNamespace(titre="X", description="", date_livraison_prevue=date(2026, 1, 1), statut="EN_ATTENTE")
            result = _run(create_livrable_native("PHASE-1", body, "chef@biat-it.tn"))
        assert result is None

    def test_creates_livrable_when_phase_exists(self):
        phase = SimpleNamespace(id="PHASE-1")
        created = SimpleNamespace(id="lv-1")
        coll = MagicMock()
        coll.insert_one = AsyncMock()
        body = SimpleNamespace(titre="Cahier des charges", description="", date_livraison_prevue=date(2026, 1, 1), statut="EN_ATTENTE")
        with (
            patch(
                "src.storage.documents.phase.PhaseDocument.get",
                new=AsyncMock(return_value=phase),
            ),
            patch(
                "src.storage.documents.livrable.LivrableDocument.get_pymongo_collection",
                return_value=coll,
            ),
            patch(
                "src.storage.documents.service_bridge._get_by_str_id",
                new=AsyncMock(return_value=created),
            ),
        ):
            result = _run(create_livrable_native("PHASE-1", body, "chef@biat-it.tn"))

        assert result is created
        doc = coll.insert_one.call_args[0][0]
        assert doc["phase_id"] == "PHASE-1"
        assert doc["created_by"] == "chef@biat-it.tn"


class TestUpdateLivrableNative:
    def test_returns_none_when_not_found(self):
        with patch(
            "src.storage.documents.service_bridge._get_by_str_id",
            new=AsyncMock(return_value=None),
        ):
            body = SimpleNamespace(titre=None, description=None, statut="LIVRE", date_livraison_reelle=None)
            result = _run(update_livrable_native(_FIXED_UUID, body))
        assert result is None

    def test_updates_statut(self):
        lv = SimpleNamespace(id=_FIXED_UUID)
        coll = MagicMock()
        coll.update_one = AsyncMock()
        body = SimpleNamespace(titre=None, description=None, statut="LIVRE", date_livraison_reelle=None)
        with (
            patch(
                "src.storage.documents.service_bridge._get_by_str_id",
                new=AsyncMock(return_value=lv),
            ),
            patch(
                "src.storage.documents.livrable.LivrableDocument.get_pymongo_collection",
                return_value=coll,
            ),
        ):
            _run(update_livrable_native(_FIXED_UUID, body))
        assert coll.update_one.call_args[0][1]["$set"] == {"statut": "LIVRE"}


class TestValiderPhaseNative:
    def test_returns_none_when_phase_not_found(self):
        with patch(
            "src.storage.documents.phase.PhaseDocument.get",
            new=AsyncMock(return_value=None),
        ):
            result = _run(valider_phase_native("PHASE-1"))
        assert result is None

    def test_raises_when_livrables_not_all_done(self):
        phase = SimpleNamespace(id="PHASE-1", name="Cadrage")
        livrables = [SimpleNamespace(statut="EN_COURS"), SimpleNamespace(statut="LIVRE")]
        with (
            patch("src.storage.documents.phase.PhaseDocument.get", new=AsyncMock(return_value=phase)),
            patch(
                "src.storage.documents.livrable.LivrableDocument.find",
                return_value=_find_chain(livrables),
            ),
        ):
            with pytest.raises(PhaseValidationError) as exc_info:
                _run(valider_phase_native("PHASE-1"))
        assert exc_info.value.count == 1

    def test_validates_when_all_livrables_done(self):
        phase = SimpleNamespace(id="PHASE-1", name="Cadrage")
        validated_phase = SimpleNamespace(id="PHASE-1", status="VALIDEE")
        livrables = [SimpleNamespace(statut="LIVRE"), SimpleNamespace(statut="VALIDE")]
        coll = MagicMock()
        coll.update_one = AsyncMock()
        with (
            patch(
                "src.storage.documents.phase.PhaseDocument.get",
                new=AsyncMock(side_effect=[phase, validated_phase]),
            ),
            patch(
                "src.storage.documents.livrable.LivrableDocument.find",
                return_value=_find_chain(livrables),
            ),
            patch(
                "src.storage.documents.phase.PhaseDocument.get_pymongo_collection",
                return_value=coll,
            ),
        ):
            result = _run(valider_phase_native("PHASE-1"))
        assert result is validated_phase
        update = coll.update_one.call_args[0][1]["$set"]
        assert update["status"] == "VALIDEE"


class TestCreateRiskNative:
    def test_creates_risk_with_computed_criticite_and_logs_audit(self):
        body = SimpleNamespace(
            titre="Retard fournisseur", description="", type_risque="FOURNISSEUR",
            probabilite="ELEVEE", impact="CRITIQUE", statut="IDENTIFIE", plan_mitigation="",
            responsable_id=None, date_identification=date(2026, 1, 1),
            date_echeance_mitigation=None, feuille_route_id=None, projet_id="proj-1",
        )
        user = {"email": "chef@biat-it.tn"}
        created = SimpleNamespace(id="risk-1", titre="Retard fournisseur")
        coll = MagicMock()
        coll.insert_one = AsyncMock()
        with (
            patch(
                "src.storage.documents.risque.RisqueDocument.get_pymongo_collection",
                return_value=coll,
            ),
            patch(
                "src.storage.documents.service_bridge._get_by_str_id",
                new=AsyncMock(return_value=created),
            ),
            patch(
                "src.storage.documents.service_bridge._create_audit_log_native",
                new=AsyncMock(),
            ) as mock_audit,
        ):
            result = _run(create_risk_native(body, user))

        assert result is created
        doc = coll.insert_one.call_args[0][0]
        assert doc["niveau_criticite"] == "CRITIQUE"  # ELEVEE x CRITIQUE -> CRITIQUE
        assert doc["created_by"] == "chef@biat-it.tn"
        mock_audit.assert_awaited_once()


class TestUpdateRiskNative:
    def test_returns_none_when_not_found(self):
        with patch(
            "src.storage.documents.service_bridge._get_by_str_id",
            new=AsyncMock(return_value=None),
        ):
            body = SimpleNamespace(titre=None, description=None, type_risque=None, plan_mitigation=None,
                                    responsable_id=None, date_echeance_mitigation=None,
                                    probabilite=None, impact=None, statut=None)
            result = _run(update_risk_native(_FIXED_UUID, body, {"email": "a@biat-it.tn"}))
        assert result is None

    def test_recomputes_criticite_when_probability_changes(self):
        risk = SimpleNamespace(
            id=_FIXED_UUID, statut="IDENTIFIE", probabilite="FAIBLE", impact="FAIBLE",
            date_cloture=None, titre="Risque X",
        )
        updated = SimpleNamespace(id=_FIXED_UUID)
        coll = MagicMock()
        coll.update_one = AsyncMock()
        body = SimpleNamespace(titre=None, description=None, type_risque=None, plan_mitigation=None,
                                responsable_id=None, date_echeance_mitigation=None,
                                probabilite="ELEVEE", impact="CRITIQUE", statut=None)
        with (
            patch(
                "src.storage.documents.service_bridge._get_by_str_id",
                new=AsyncMock(side_effect=[risk, updated]),
            ),
            patch(
                "src.storage.documents.risque.RisqueDocument.get_pymongo_collection",
                return_value=coll,
            ),
        ):
            result = _run(update_risk_native(_FIXED_UUID, body, {"email": "a@biat-it.tn"}))

        assert result is updated
        update = coll.update_one.call_args[0][1]["$set"]
        assert update["niveau_criticite"] == "CRITIQUE"

    def test_closing_sets_date_cloture_and_logs_audit(self):
        risk = SimpleNamespace(
            id=_FIXED_UUID, statut="EN_TRAITEMENT", probabilite="FAIBLE", impact="FAIBLE",
            date_cloture=None, titre="Risque X",
        )
        updated = SimpleNamespace(id=_FIXED_UUID)
        coll = MagicMock()
        coll.update_one = AsyncMock()
        body = SimpleNamespace(titre=None, description=None, type_risque=None, plan_mitigation=None,
                                responsable_id=None, date_echeance_mitigation=None,
                                probabilite=None, impact=None, statut="CLOTURE")
        with (
            patch(
                "src.storage.documents.service_bridge._get_by_str_id",
                new=AsyncMock(side_effect=[risk, updated]),
            ),
            patch(
                "src.storage.documents.risque.RisqueDocument.get_pymongo_collection",
                return_value=coll,
            ),
            patch(
                "src.storage.documents.service_bridge._create_audit_log_native",
                new=AsyncMock(),
            ) as mock_audit,
        ):
            _run(update_risk_native(_FIXED_UUID, body, {"email": "a@biat-it.tn"}))

        update = coll.update_one.call_args[0][1]["$set"]
        assert update["statut"] == "CLOTURE"
        assert update["date_cloture"] is not None
        assert mock_audit.await_count == 2  # RISK_STATUS_CHANGED + RISK_CLOSED


class TestCloseRiskNative:
    def test_returns_none_when_not_found(self):
        with patch(
            "src.storage.documents.service_bridge._get_by_str_id",
            new=AsyncMock(return_value=None),
        ):
            result = _run(close_risk_native(_FIXED_UUID, {"email": "a@biat-it.tn"}))
        assert result is None

    def test_closes_and_logs_audit(self):
        risk = SimpleNamespace(id=_FIXED_UUID, titre="Risque X")
        coll = MagicMock()
        coll.update_one = AsyncMock()
        with (
            patch(
                "src.storage.documents.service_bridge._get_by_str_id",
                new=AsyncMock(return_value=risk),
            ),
            patch(
                "src.storage.documents.risque.RisqueDocument.get_pymongo_collection",
                return_value=coll,
            ),
            patch(
                "src.storage.documents.service_bridge._create_audit_log_native",
                new=AsyncMock(),
            ) as mock_audit,
        ):
            result = _run(close_risk_native(_FIXED_UUID, {"email": "a@biat-it.tn"}))

        assert result is risk
        update = coll.update_one.call_args[0][1]["$set"]
        assert update["statut"] == "CLOTURE"
        mock_audit.assert_awaited_once()


class TestCreateAssetNative:
    def test_creates_and_returns_asset_model(self):
        body = SimpleNamespace(
            designation="Serveur Dell R740", compte_immobilisation="2183",
            compte_amortissement="28183", acquisition_date=date(2026, 1, 1),
            acquisition_cost_ht=15000.0, useful_life_years=5, depreciation_method="linear",
        )
        coll = MagicMock()
        coll.insert_one = AsyncMock()
        with (
            patch(
                "src.storage.documents.asset.AssetDocument.get_pymongo_collection",
                return_value=coll,
            ),
            patch(
                "src.storage.documents.service_bridge._create_audit_log_native",
                new=AsyncMock(),
            ) as mock_audit,
        ):
            result = _run(create_asset_native(body, {"email": "comptable@biat-it.tn"}))

        assert result.designation == "Serveur Dell R740"
        doc = coll.insert_one.call_args[0][0]
        assert doc["designation"] == "Serveur Dell R740"
        assert doc["fully_depreciated"] is False
        mock_audit.assert_awaited_once()


class TestCreateBudgetLineNative:
    def test_creates_with_zero_consumed(self):
        body = SimpleNamespace(categorie="Licences", montant_prevu=10000.0, devise="TND")
        created = SimpleNamespace(id="lb-1")
        coll = MagicMock()
        coll.insert_one = AsyncMock()
        with (
            patch(
                "src.storage.documents.ligne_budget.LigneBudgetDocument.get_pymongo_collection",
                return_value=coll,
            ),
            patch(
                "src.storage.documents.service_bridge._get_by_str_id",
                new=AsyncMock(return_value=created),
            ),
        ):
            result = _run(create_budget_line_native("proj-1", body))
        assert result is created
        doc = coll.insert_one.call_args[0][0]
        assert doc["montant_consomme"] == 0.0
        assert doc["projet_id"] == "proj-1"


class TestUpdateBudgetLineNative:
    def test_returns_none_when_not_found(self):
        with patch(
            "src.storage.documents.service_bridge._get_by_str_id",
            new=AsyncMock(return_value=None),
        ):
            body = SimpleNamespace(categorie=None, montant_prevu=None)
            result = _run(update_budget_line_native(_FIXED_UUID, body))
        assert result is None

    def test_updates_montant_prevu(self):
        lb = SimpleNamespace(id=_FIXED_UUID)
        coll = MagicMock()
        coll.update_one = AsyncMock()
        body = SimpleNamespace(categorie=None, montant_prevu=5000.0)
        with (
            patch(
                "src.storage.documents.service_bridge._get_by_str_id",
                new=AsyncMock(return_value=lb),
            ),
            patch(
                "src.storage.documents.ligne_budget.LigneBudgetDocument.get_pymongo_collection",
                return_value=coll,
            ),
        ):
            _run(update_budget_line_native(_FIXED_UUID, body))
        assert coll.update_one.call_args[0][1]["$set"] == {"montant_prevu": 5000.0}


class TestDeleteBudgetLineNative:
    def test_returns_false_when_not_found(self):
        with patch(
            "src.storage.documents.service_bridge._get_by_str_id",
            new=AsyncMock(return_value=None),
        ):
            result = _run(delete_budget_line_native(_FIXED_UUID))
        assert result is False

    def test_deletes_when_found(self):
        lb = SimpleNamespace(id=_FIXED_UUID)
        coll = MagicMock()
        coll.delete_one = AsyncMock()
        with (
            patch(
                "src.storage.documents.service_bridge._get_by_str_id",
                new=AsyncMock(return_value=lb),
            ),
            patch(
                "src.storage.documents.ligne_budget.LigneBudgetDocument.get_pymongo_collection",
                return_value=coll,
            ),
        ):
            result = _run(delete_budget_line_native(_FIXED_UUID))
        assert result is True
        coll.delete_one.assert_awaited_once_with({"_id": _FIXED_UUID})


class TestUpdateBudgetPlanEntryNative:
    def test_returns_none_when_not_found(self):
        with patch(
            "src.storage.documents.budget_plan.BudgetPlanDocument.find_one",
            new=AsyncMock(return_value=None),
        ):
            body = SimpleNamespace(label=None, monthly=None, note=None)
            result = _run(update_budget_plan_entry_native("cat-1", 2026, body, {"email": "a@biat-it.tn"}))
        assert result is None

    def test_updates_monthly_values_and_logs_audit(self):
        row = SimpleNamespace(id="bp-1", catalog_id="cat-1", year=2026)
        updated = SimpleNamespace(id="bp-1", monthly=[100.0] * 12)
        coll = MagicMock()
        coll.update_one = AsyncMock()
        body = SimpleNamespace(label=None, monthly=[100.0] * 12, note=None)
        with (
            patch(
                "src.storage.documents.budget_plan.BudgetPlanDocument.find_one",
                new=AsyncMock(side_effect=[row, updated]),
            ),
            patch(
                "src.storage.documents.budget_plan.BudgetPlanDocument.get_pymongo_collection",
                return_value=coll,
            ),
            patch(
                "src.storage.documents.service_bridge._create_audit_log_native",
                new=AsyncMock(),
            ) as mock_audit,
        ):
            result = _run(update_budget_plan_entry_native("cat-1", 2026, body, {"email": "a@biat-it.tn"}))

        assert result is updated
        update = coll.update_one.call_args[0][1]["$set"]
        assert update["monthly"] == [100.0] * 12
        mock_audit.assert_awaited_once()


class TestDeleteBudgetPlanEntryNative:
    def test_returns_false_when_not_found(self):
        with patch(
            "src.storage.documents.budget_plan.BudgetPlanDocument.find_one",
            new=AsyncMock(return_value=None),
        ):
            result = _run(delete_budget_plan_entry_native("cat-1", 2026, {"email": "a@biat-it.tn"}))
        assert result is False

    def test_deletes_and_logs_audit(self):
        row = SimpleNamespace(id="bp-1")
        coll = MagicMock()
        coll.delete_one = AsyncMock()
        with (
            patch(
                "src.storage.documents.budget_plan.BudgetPlanDocument.find_one",
                new=AsyncMock(return_value=row),
            ),
            patch(
                "src.storage.documents.budget_plan.BudgetPlanDocument.get_pymongo_collection",
                return_value=coll,
            ),
            patch(
                "src.storage.documents.service_bridge._create_audit_log_native",
                new=AsyncMock(),
            ) as mock_audit,
        ):
            result = _run(delete_budget_plan_entry_native("cat-1", 2026, {"email": "a@biat-it.tn"}))

        assert result is True
        coll.delete_one.assert_awaited_once_with({"_id": "bp-1"})
        mock_audit.assert_awaited_once()


class TestSeedBudgetPlanFromYamlNative:
    def test_skips_when_year_already_seeded(self):
        with (
            patch(
                "src.storage.documents.budget_plan.BudgetPlanDocument.find_one",
                new=AsyncMock(return_value=SimpleNamespace(id="bp-1")),
            ) as mock_find,
        ):
            _run(seed_budget_plan_from_yaml_native(2026, MagicMock()))
        mock_find.assert_awaited_once_with({"year": 2026})

    def test_inserts_entries_from_yaml_when_not_yet_seeded(self):
        yaml_path = MagicMock()
        yaml_path.read_text.return_value = """
entries:
  - catalog_id: licences_ms365
    label: Licences Microsoft 365
    monthly: [100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100]
"""
        coll = MagicMock()
        coll.insert_many = AsyncMock()
        with (
            patch(
                "src.storage.documents.budget_plan.BudgetPlanDocument.find_one",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "src.storage.documents.budget_plan.BudgetPlanDocument.get_pymongo_collection",
                return_value=coll,
            ),
        ):
            _run(seed_budget_plan_from_yaml_native(2026, yaml_path))

        coll.insert_many.assert_awaited_once()
        docs = coll.insert_many.call_args[0][0]
        assert len(docs) == 1
        assert docs[0]["catalog_id"] == "licences_ms365"
        assert docs[0]["year"] == 2026
        assert len(docs[0]["monthly"]) == 12
