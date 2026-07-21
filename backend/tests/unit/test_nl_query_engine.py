"""Unit tests for NLQueryEngine — LLM and MongoDB calls mocked."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch


from src.query.nl_query_engine import NLQueryEngine, _build_system_prompt


# ── System prompt content ─────────────────────────────────────────────────────

class TestBuildSystemPrompt:
    def test_includes_year_filter_example_for_assets(self):
        """Regression test — without a worked example for filtering by
        acquisition year, qwen2.5:3b fell back to `new Date(...)` (invalid
        JSON) for questions like "Actifs CAPEX acquis en 2026" (2026-07)."""
        prompt = _build_system_prompt()
        assert "acquisition_date" in prompt
        assert "new Date(...)" in prompt  # named explicitly as forbidden
        assert '"$gte": "2026-01-01"' in prompt


# ── Static / pure methods (no mocking needed) ─────────────────────────────────

class TestIsSafe:
    def test_allowed_collection_and_simple_pipeline_is_safe(self):
        safe, reason = NLQueryEngine._is_safe("invoices", [{"$match": {"status": "PAID"}}])
        assert safe is True
        assert reason == ""

    def test_disallowed_collection_is_unsafe(self):
        safe, reason = NLQueryEngine._is_safe("users", [{"$match": {}}])
        assert safe is False
        assert "non autorisée" in reason

    def test_empty_pipeline_is_unsafe(self):
        safe, _ = NLQueryEngine._is_safe("invoices", [])
        assert safe is False

    def test_non_list_pipeline_is_unsafe(self):
        safe, _ = NLQueryEngine._is_safe("invoices", {"$match": {}})
        assert safe is False

    def test_out_stage_is_unsafe(self):
        safe, reason = NLQueryEngine._is_safe("invoices", [{"$out": "evil"}])
        assert safe is False
        assert "$out" in reason

    def test_merge_stage_is_unsafe(self):
        safe, _ = NLQueryEngine._is_safe("invoices", [{"$merge": "evil"}])
        assert safe is False

    def test_lookup_stage_is_unsafe(self):
        safe, _ = NLQueryEngine._is_safe("invoices", [{"$lookup": {}}])
        assert safe is False

    def test_where_stage_is_unsafe(self):
        safe, _ = NLQueryEngine._is_safe("invoices", [{"$where": "1==1"}])
        assert safe is False

    def test_multi_key_stage_is_unsafe(self):
        safe, _ = NLQueryEngine._is_safe("invoices", [{"$match": {}, "$sort": {}}])
        assert safe is False

    def test_non_dollar_stage_is_unsafe(self):
        safe, _ = NLQueryEngine._is_safe("invoices", [{"match": {}}])
        assert safe is False


class TestCoerceDates:
    def test_converts_iso_date_string(self):
        result = NLQueryEngine._coerce_dates({"invoice_date": "2026-06-01"})
        assert result["invoice_date"].year == 2026
        assert result["invoice_date"].month == 6
        assert result["invoice_date"].day == 1

    def test_converts_iso_datetime_string(self):
        result = NLQueryEngine._coerce_dates({"paid_at": "2026-06-01T12:30:00Z"})
        assert result["paid_at"].year == 2026
        assert result["paid_at"].hour == 12

    def test_leaves_non_date_strings_untouched(self):
        result = NLQueryEngine._coerce_dates({"status": "PAID"})
        assert result["status"] == "PAID"

    def test_recurses_into_nested_pipeline(self):
        pipeline = [{"$match": {"invoice_date": {"$gte": "2026-01-01"}}}]
        result = NLQueryEngine._coerce_dates(pipeline)
        assert result[0]["$match"]["invoice_date"]["$gte"].year == 2026

    def test_leaves_non_string_values_untouched(self):
        result = NLQueryEngine._coerce_dates({"n": 5, "flag": True, "x": None})
        assert result == {"n": 5, "flag": True, "x": None}


class TestStripDateFromString:
    """Regression test — qwen2.5:3b occasionally wraps an already-native date
    field (e.g. due_date) in $dateFromString, which MongoDB rejects with a
    ConversionFailure ("requires that 'dateString' be a string, found: date").
    Seen live for "Factures en retard" (2026-07-16)."""

    def test_unwraps_known_date_field(self):
        node = {"$dateFromString": {"dateString": "$due_date"}}
        result = NLQueryEngine._strip_date_from_string(node, {"due_date"})
        assert result == "$due_date"

    def test_leaves_unknown_field_untouched(self):
        node = {"$dateFromString": {"dateString": "$some_string_field"}}
        result = NLQueryEngine._strip_date_from_string(node, {"due_date"})
        assert result == node

    def test_recurses_into_expr_and_unwraps_in_place(self):
        pipeline = [{"$match": {"$expr": {
            "$lt": [{"$dateFromString": {"dateString": "$due_date"}}, "$$NOW"]
        }}}]
        result = NLQueryEngine._strip_date_from_string(pipeline, {"due_date"})
        assert result[0]["$match"]["$expr"]["$lt"][0] == "$due_date"

    def test_leaves_pipeline_without_date_from_string_untouched(self):
        pipeline = [{"$match": {"status": "FLAGGED"}}]
        result = NLQueryEngine._strip_date_from_string(pipeline, {"due_date"})
        assert result == pipeline


class TestFormatAnswer:
    def test_single_float_formats_as_tnd(self):
        rows = [{"total": 12345.678}]
        result = NLQueryEngine._format_answer("Total TTC", rows)
        assert "12,345.678 TND" in result
        assert "Total TTC" in result

    def test_single_int_formats_with_commas(self):
        rows = [{"nb": 1000}]
        result = NLQueryEngine._format_answer("Nombre", rows)
        assert "1,000" in result

    def test_single_string_value(self):
        rows = [{"name": "Ooredoo"}]
        result = NLQueryEngine._format_answer("Fournisseur", rows)
        assert "Ooredoo" in result

    def test_single_none_value(self):
        rows = [{"val": None}]
        result = NLQueryEngine._format_answer("Montant", rows)
        assert "Aucune donnée" in result

    def test_empty_rows_returns_no_result_message(self):
        result = NLQueryEngine._format_answer("Test", [])
        assert "Aucun résultat" in result

    def test_multiple_rows_bullet_list(self):
        rows = [{"name": "A", "val": 1.0}, {"name": "B", "val": 2.0}]
        result = NLQueryEngine._format_answer("Liste", rows)
        assert "•" in result
        assert "A" in result
        assert "B" in result

    def test_large_result_shows_count(self):
        rows = [{"i": i} for i in range(20)]
        result = NLQueryEngine._format_answer("Grand résultat", rows)
        assert "20" in result

    def test_empty_explanation_still_works(self):
        rows = [{"n": 5}]
        result = NLQueryEngine._format_answer("", rows)
        assert "5" in result


# ── query() with mocked LLM and MongoDB ───────────────────────────────────────

class _FakeCursor(list):
    """aggregate() returns a cursor; iterating it yields the docs."""


def _mock_collection(return_value=None, side_effect=None):
    coll = MagicMock()
    if side_effect is not None:
        coll.aggregate.side_effect = side_effect
    else:
        coll.aggregate.return_value = _FakeCursor(return_value or [])
    return coll


class TestNLQueryEngineQuery:
    def test_successful_query_returns_all_fields(self):
        nl = NLQueryEngine()
        coll = _mock_collection([{"nb": 42}])
        llm_json = json.dumps({
            "collection": "invoices",
            "pipeline": [{"$count": "nb"}],
            "explanation": "Comptage factures",
        })
        with patch.object(nl, "_ask_llm", return_value=llm_json), \
             patch("src.storage.sync_mongo_repository._get_db", return_value={"invoices": coll}):
            result = nl.query("Combien de factures?")

        assert result["explanation"] == "Comptage factures"
        assert result["result"] == [{"nb": 42}]
        assert "42" in result["answer"]
        assert "invoices" in result["sql"]

    def test_null_pipeline_from_llm_returns_explanation(self):
        nl = NLQueryEngine()
        llm_json = json.dumps({
            "collection": None, "pipeline": None,
            "explanation": "Je ne peux pas répondre.",
        })
        with patch.object(nl, "_ask_llm", return_value=llm_json):
            result = nl.query("Quelle est la météo?")

        assert result["sql"] is None
        assert result["result"] is None
        assert "Je ne peux pas répondre." in result["answer"]

    def test_disallowed_collection_rejected(self):
        nl = NLQueryEngine()
        llm_json = json.dumps({
            "collection": "users", "pipeline": [{"$match": {}}],
            "explanation": "Liste utilisateurs",
        })
        with patch.object(nl, "_ask_llm", return_value=llm_json):
            result = nl.query("Liste les utilisateurs")

        assert result["sql"] is None
        assert "non autorisée" in result["answer"]

    def test_out_stage_rejected(self):
        nl = NLQueryEngine()
        llm_json = json.dumps({
            "collection": "invoices", "pipeline": [{"$out": "evil"}],
            "explanation": "Suppression déguisée",
        })
        with patch.object(nl, "_ask_llm", return_value=llm_json):
            result = nl.query("Supprime tout")

        assert result["sql"] is None
        assert "$out" in result["answer"]

    def test_pipeline_error_triggers_retry(self):
        nl = NLQueryEngine()
        first_llm = json.dumps({
            "collection": "invoices", "pipeline": [{"$badStage": {}}],
            "explanation": "Mauvaise requête",
        })
        second_llm = json.dumps({
            "collection": "invoices", "pipeline": [{"$count": "nb"}],
            "explanation": "Requête corrigée",
        })
        coll = _mock_collection(
            side_effect=[Exception("unknown stage $badStage"), _FakeCursor([{"nb": 3}])]
        )
        with patch.object(nl, "_ask_llm", side_effect=[first_llm, second_llm]), \
             patch("src.storage.sync_mongo_repository._get_db", return_value={"invoices": coll}):
            result = nl.query("Test avec erreur")

        assert result["result"] == [{"nb": 3}]

    def test_unparsable_llm_response_returns_error(self):
        nl = NLQueryEngine()
        with patch.object(nl, "_ask_llm", return_value="not json at all") as mock_ask:
            result = nl.query("Question sans réponse")

        assert result["sql"] is None
        assert result["result"] is None
        assert "non parsable" in result["answer"]
        # Retry attempted once (still invalid) before giving up — see
        # test_parse_failure_retries_and_succeeds_below for the success case.
        assert mock_ask.call_count == 2

    def test_parse_failure_retries_and_succeeds_on_second_attempt(self):
        """Invalid JSON on the first attempt (e.g. `new Date(...)` instead of
        an ISO string) must trigger one retry, same safety net as exec_error —
        regression test for the CAPEX assets query bug (2026-07)."""
        nl = NLQueryEngine()
        invalid_first = '{"collection": "assets", "pipeline": [{"$match": {"acquisition_date": new Date("2026-01-01")}}]}'
        valid_second = json.dumps({
            "collection": "assets",
            "pipeline": [{"$count": "nb"}],
            "explanation": "Actifs CAPEX acquis en 2026",
        })
        coll = _mock_collection([{"nb": 2}])
        with patch.object(nl, "_ask_llm", side_effect=[invalid_first, valid_second]) as mock_ask, \
             patch("src.storage.sync_mongo_repository._get_db", return_value={"assets": coll}):
            result = nl.query("Actifs CAPEX acquis en 2026")

        assert mock_ask.call_count == 2
        assert result["result"] == [{"nb": 2}]
        assert "non parsable" not in result["answer"]

    def test_ollama_connection_error_returns_graceful_response(self):
        nl = NLQueryEngine(ollama_url="http://localhost:99999")
        # _ask_llm catches ConnectionError and returns JSON fallback internally
        result = nl.query("Test connexion")
        # Should not raise — just return None collection/pipeline
        assert "question" in result

    def test_empty_result_set(self):
        nl = NLQueryEngine()
        coll = _mock_collection([])
        llm_json = json.dumps({
            "collection": "invoices",
            "pipeline": [{"$match": {"issuer_name": "Inconnu"}}],
            "explanation": "Recherche",
        })
        with patch.object(nl, "_ask_llm", return_value=llm_json), \
             patch("src.storage.sync_mongo_repository._get_db", return_value={"invoices": coll}):
            result = nl.query("Factures de Inconnu")

        assert result["result"] == []
        assert "Aucun résultat" in result["answer"]

    def test_date_literal_coerced_before_execution(self):
        nl = NLQueryEngine()
        coll = _mock_collection([{"total": 1000.0}])
        llm_json = json.dumps({
            "collection": "invoices",
            "pipeline": [
                {"$match": {"invoice_date": {"$gte": "2026-06-01"}}},
                {"$group": {"_id": None, "total": {"$sum": "$amount_ttc"}}},
            ],
            "explanation": "Total juin",
        })
        with patch.object(nl, "_ask_llm", return_value=llm_json), \
             patch("src.storage.sync_mongo_repository._get_db", return_value={"invoices": coll}):
            nl.query("Total de juin")

        executed_pipeline = coll.aggregate.call_args[0][0]
        gte_value = executed_pipeline[0]["$match"]["invoice_date"]["$gte"]
        assert hasattr(gte_value, "year")  # coerced to a real datetime, not a string
