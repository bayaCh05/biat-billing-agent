"""Unit tests — service_bridge.py Tier 3, batch B: projects/roadmap/livrables/
risks read-only *_mongo functions.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.storage.documents.service_bridge import (
    get_project_mongo,
    list_livrables_mongo,
    list_phases_mongo,
    list_projects_mongo,
    list_risks_mongo,
    list_roadmap_mongo,
    list_roadmap_with_risks_mongo,
    risk_summary_mongo,
    risks_for_project_mongo,
    risks_for_roadmap_mongo,
    risks_par_projet_mongo,
)


def _run(coro):
    return asyncio.run(coro)


def _find_chain(return_value):
    chain = MagicMock()
    chain.sort.return_value = chain
    chain.to_list = AsyncMock(return_value=return_value)
    return chain


def _agg_result(rows):
    agg = MagicMock()
    agg.to_list = AsyncMock(return_value=rows)
    return agg


_FIXED_UUID = "12345678-1234-1234-1234-123456789012"


class TestListProjectsMongo:
    def test_computes_budget_and_spent_amounts(self):
        charte = SimpleNamespace(
            project_id="proj-1", project_name="Migration Mongo", client="BIAT",
            budget_jh=100.0, taux_jh=500.0, is_active=True,
            valid_from=date(2026, 1, 1), valid_until=None,
        )
        coll = MagicMock()
        coll.aggregate.return_value = _agg_result([{"_id": "proj-1", "total": 40.0}])
        with (
            patch(
                "src.storage.documents.charte_projet.CharteProjetDocument.find",
                return_value=_find_chain([charte]),
            ),
            patch(
                "src.storage.documents.phase.PhaseDocument.get_pymongo_collection",
                return_value=coll,
            ),
        ):
            result = _run(list_projects_mongo())

        assert len(result) == 1
        row = result[0]
        assert row["status"] == "ACTIVE"
        assert row["consumed_jh"] == 40.0
        assert row["budget_tnd"] == 50000.0
        assert row["spent_tnd"] == 20000.0

    def test_returns_none_when_mongo_down(self):
        with patch(
            "src.storage.documents.charte_projet.CharteProjetDocument.find",
            side_effect=Exception("mongo down"),
        ):
            result = _run(list_projects_mongo())
        assert result is None


class TestGetProjectMongo:
    def test_returns_empty_dict_when_not_found(self):
        with patch(
            "src.storage.documents.charte_projet.CharteProjetDocument.find_one",
            new=AsyncMock(return_value=None),
        ):
            result = _run(get_project_mongo("proj-missing"))
        assert result == {}

    def test_returns_project_details_with_consumed_jh(self):
        charte = SimpleNamespace(
            project_id="proj-1", project_name="Migration Mongo", client="BIAT",
            budget_jh=100.0, taux_jh=500.0, is_active=False,
            valid_from=date(2026, 1, 1), valid_until=date(2026, 12, 31),
        )
        coll = MagicMock()
        coll.aggregate.return_value = _agg_result([{"total": 25.0}])
        with (
            patch(
                "src.storage.documents.charte_projet.CharteProjetDocument.find_one",
                new=AsyncMock(return_value=charte),
            ),
            patch(
                "src.storage.documents.phase.PhaseDocument.get_pymongo_collection",
                return_value=coll,
            ),
        ):
            result = _run(get_project_mongo("proj-1"))

        assert result["status"] == "COMPLETED"
        assert result["consumed_jh"] == 25.0
        assert result["spent_tnd"] == 12500.0

    def test_returns_none_when_mongo_down(self):
        with patch(
            "src.storage.documents.charte_projet.CharteProjetDocument.find_one",
            side_effect=Exception("mongo down"),
        ):
            result = _run(get_project_mongo("proj-1"))
        assert result is None


class TestListPhasesMongo:
    def test_returns_phases_for_project(self):
        phases = [SimpleNamespace(id="PHASE-1")]
        with patch(
            "src.storage.documents.phase.PhaseDocument.find",
            return_value=_find_chain(phases),
        ) as mock_find:
            result = _run(list_phases_mongo("proj-1"))
        assert result == phases
        mock_find.assert_called_once_with({"project_id": "proj-1"})

    def test_returns_none_when_mongo_down(self):
        with patch(
            "src.storage.documents.phase.PhaseDocument.find",
            side_effect=Exception("mongo down"),
        ):
            result = _run(list_phases_mongo("proj-1"))
        assert result is None


class TestListRoadmapMongo:
    def test_filters_by_year(self):
        items = [SimpleNamespace(id="item-1")]
        with patch(
            "src.storage.documents.feuille_de_route.FeuilleDeRouteDocument.find",
            return_value=_find_chain(items),
        ) as mock_find:
            result = _run(list_roadmap_mongo(2026))
        assert result == items
        mock_find.assert_called_once_with({"annee": 2026})

    def test_returns_none_when_mongo_down(self):
        with patch(
            "src.storage.documents.feuille_de_route.FeuilleDeRouteDocument.find",
            side_effect=Exception("mongo down"),
        ):
            result = _run(list_roadmap_mongo(2026))
        assert result is None


class TestListRoadmapWithRisksMongo:
    def test_merges_items_with_risk_summary(self):
        items = [SimpleNamespace(id="item-1")]
        risk_rows = [{"_id": "item-1", "risk_count": 2, "max_criticite_num": 4}]
        coll = MagicMock()
        coll.aggregate.return_value = _agg_result(risk_rows)
        with (
            patch(
                "src.storage.documents.feuille_de_route.FeuilleDeRouteDocument.find",
                return_value=_find_chain(items),
            ),
            patch(
                "src.storage.documents.risque.RisqueDocument.get_pymongo_collection",
                return_value=coll,
            ),
        ):
            result = _run(list_roadmap_with_risks_mongo(2026))

        assert result["items"] == items
        assert result["risk_by_item"]["item-1"] == {"count": 2, "highest_criticite": "CRITIQUE"}

    def test_returns_none_when_mongo_down(self):
        with patch(
            "src.storage.documents.feuille_de_route.FeuilleDeRouteDocument.find",
            side_effect=Exception("mongo down"),
        ):
            result = _run(list_roadmap_with_risks_mongo(2026))
        assert result is None


class TestListLivrablesMongo:
    def test_returns_livrables_for_phase(self):
        docs = [SimpleNamespace(id="lv-1")]
        with patch(
            "src.storage.documents.livrable.LivrableDocument.find",
            return_value=_find_chain(docs),
        ) as mock_find:
            result = _run(list_livrables_mongo("PHASE-1"))
        assert result == docs
        mock_find.assert_called_once_with({"phase_id": "PHASE-1"})

    def test_returns_none_when_mongo_down(self):
        with patch(
            "src.storage.documents.livrable.LivrableDocument.find",
            side_effect=Exception("mongo down"),
        ):
            result = _run(list_livrables_mongo("PHASE-1"))
        assert result is None


class TestListRisksMongo:
    def test_builds_query_from_all_filters(self):
        with patch(
            "src.storage.documents.risque.RisqueDocument.find",
            return_value=_find_chain([]),
        ) as mock_find:
            _run(list_risks_mongo(
                projet_id="proj-1", feuille_route_id=_FIXED_UUID,
                statut="IDENTIFIE", niveau_criticite="CRITIQUE",
            ))
        query = mock_find.call_args[0][0]
        assert query == {
            "projet_id": "proj-1", "feuille_route_id": _FIXED_UUID,
            "statut": "IDENTIFIE", "niveau_criticite": "CRITIQUE",
        }

    def test_no_filters_queries_everything(self):
        with patch(
            "src.storage.documents.risque.RisqueDocument.find",
            return_value=_find_chain([]),
        ) as mock_find:
            _run(list_risks_mongo())
        assert mock_find.call_args[0][0] == {}

    def test_returns_none_when_mongo_down(self):
        with patch(
            "src.storage.documents.risque.RisqueDocument.find",
            side_effect=Exception("mongo down"),
        ):
            result = _run(list_risks_mongo())
        assert result is None


class TestRiskSummaryMongo:
    def test_aggregates_by_criticite_and_statut(self):
        risks = [
            SimpleNamespace(statut="IDENTIFIE", niveau_criticite="CRITIQUE",
                             date_echeance_mitigation=None, id="r1", titre="R1", projet_id="p1",
                             created_at=datetime(2026, 1, 1, tzinfo=timezone.utc)),
            SimpleNamespace(statut="CLOTURE", niveau_criticite="FAIBLE",
                             date_echeance_mitigation=None, id="r2", titre="R2", projet_id="p1",
                             created_at=datetime(2026, 1, 2, tzinfo=timezone.utc)),
        ]
        with patch(
            "src.storage.documents.risque.RisqueDocument.find",
            return_value=_find_chain(risks),
        ):
            result = _run(risk_summary_mongo())

        assert result["by_criticite"]["CRITIQUE"] == 1
        assert result["by_criticite"]["FAIBLE"] == 0  # CLOTURE risks excluded
        assert result["by_statut"] == {"IDENTIFIE": 1, "CLOTURE": 1}
        assert result["total_active"] == 1
        assert len(result["top_critical"]) == 1

    def test_flags_overdue_mitigation(self):
        past_due = date(2020, 1, 1)
        risks = [
            SimpleNamespace(statut="IDENTIFIE", niveau_criticite="MOYENNE",
                             date_echeance_mitigation=past_due, id="r1", titre="R1", projet_id="p1",
                             created_at=datetime(2026, 1, 1, tzinfo=timezone.utc)),
        ]
        with patch(
            "src.storage.documents.risque.RisqueDocument.find",
            return_value=_find_chain(risks),
        ):
            result = _run(risk_summary_mongo())
        assert len(result["overdue"]) == 1
        assert result["overdue"][0]["id"] == "r1"

    def test_returns_none_when_mongo_down(self):
        with patch(
            "src.storage.documents.risque.RisqueDocument.find",
            side_effect=Exception("mongo down"),
        ):
            result = _run(risk_summary_mongo())
        assert result is None


class TestRisksParProjetMongo:
    def test_groups_by_project_sorted_by_criticite(self):
        risks = [
            SimpleNamespace(projet_id="p1", niveau_criticite="FAIBLE"),
            SimpleNamespace(projet_id="p2", niveau_criticite="CRITIQUE"),
        ]
        chartes = [SimpleNamespace(project_id="p1", project_name="Projet 1"),
                   SimpleNamespace(project_id="p2", project_name="Projet 2")]
        with (
            patch(
                "src.storage.documents.risque.RisqueDocument.find",
                return_value=_find_chain(risks),
            ),
            patch(
                "src.storage.documents.charte_projet.CharteProjetDocument.find",
                return_value=_find_chain(chartes),
            ),
        ):
            result = _run(risks_par_projet_mongo())

        assert len(result) == 2
        assert result[0]["projet_id"] == "p2"  # CRITIQUE sorts first
        assert result[0]["project_name"] == "Projet 2"

    def test_returns_none_when_mongo_down(self):
        with patch(
            "src.storage.documents.risque.RisqueDocument.find",
            side_effect=Exception("mongo down"),
        ):
            result = _run(risks_par_projet_mongo())
        assert result is None


class TestRisksForRoadmapMongo:
    def test_excludes_closed_risks(self):
        with patch(
            "src.storage.documents.risque.RisqueDocument.find",
            return_value=_find_chain([]),
        ) as mock_find:
            _run(risks_for_roadmap_mongo(_FIXED_UUID))
        query = mock_find.call_args[0][0]
        assert query["feuille_route_id"] == _FIXED_UUID
        assert query["statut"] == {"$ne": "CLOTURE"}

    def test_returns_none_when_mongo_down(self):
        with patch(
            "src.storage.documents.risque.RisqueDocument.find",
            side_effect=Exception("mongo down"),
        ):
            result = _run(risks_for_roadmap_mongo(_FIXED_UUID))
        assert result is None


class TestRisksForProjectMongo:
    def test_excludes_closed_risks(self):
        with patch(
            "src.storage.documents.risque.RisqueDocument.find",
            return_value=_find_chain([]),
        ) as mock_find:
            _run(risks_for_project_mongo("proj-1"))
        query = mock_find.call_args[0][0]
        assert query == {"projet_id": "proj-1", "statut": {"$ne": "CLOTURE"}}

    def test_returns_none_when_mongo_down(self):
        with patch(
            "src.storage.documents.risque.RisqueDocument.find",
            side_effect=Exception("mongo down"),
        ):
            result = _run(risks_for_project_mongo("proj-1"))
        assert result is None
