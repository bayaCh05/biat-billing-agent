"""Unit tests for NLQueryEngine — LLM and DB calls mocked."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.query.nl_query_engine import NLQueryEngine


# ── Static / pure methods (no mocking needed) ─────────────────────────────────

class TestIsSafe:
    def test_select_is_safe(self):
        assert NLQueryEngine._is_safe("SELECT * FROM invoices") is True

    def test_select_with_subquery(self):
        assert NLQueryEngine._is_safe("SELECT id FROM (SELECT * FROM invoices)") is True

    def test_insert_is_unsafe(self):
        assert NLQueryEngine._is_safe("INSERT INTO invoices VALUES (1)") is False

    def test_update_is_unsafe(self):
        assert NLQueryEngine._is_safe("UPDATE invoices SET status = 'PAID'") is False

    def test_delete_is_unsafe(self):
        assert NLQueryEngine._is_safe("DELETE FROM invoices") is False

    def test_drop_is_unsafe(self):
        assert NLQueryEngine._is_safe("DROP TABLE invoices") is False

    def test_alter_is_unsafe(self):
        assert NLQueryEngine._is_safe("ALTER TABLE invoices ADD COLUMN x TEXT") is False

    def test_create_is_unsafe(self):
        assert NLQueryEngine._is_safe("CREATE TABLE foo (id INT)") is False

    def test_truncate_is_unsafe(self):
        assert NLQueryEngine._is_safe("TRUNCATE TABLE invoices") is False

    def test_embedded_delete_is_unsafe(self):
        assert NLQueryEngine._is_safe("SELECT 1; DELETE FROM invoices") is False

    def test_empty_string_is_unsafe(self):
        assert NLQueryEngine._is_safe("") is False


class TestSanitizeSql:
    def test_removes_and_direction_condition(self):
        sql = (
            "SELECT SUM(jl.debit) FROM journal_lines jl "
            "JOIN journal_entries je ON jl.entry_id = je.id "
            "AND je.direction = 'SUPPLIER'"
        )
        result = NLQueryEngine._sanitize_sql(sql)
        assert "je.direction" not in result

    def test_removes_and_status_condition(self):
        sql = "SELECT * FROM journal_entries je AND je.status = 'PAID'"
        result = NLQueryEngine._sanitize_sql(sql)
        assert "je.status" not in result

    def test_removes_and_issuer_name_condition(self):
        sql = "SELECT * FROM journal_entries je AND je.issuer_name = 'Acme'"
        result = NLQueryEngine._sanitize_sql(sql)
        assert "je.issuer_name" not in result

    def test_keeps_valid_sql_unchanged(self):
        sql = "SELECT COALESCE(SUM(amount_ttc), 0) AS total FROM invoices WHERE status = 'PAID'"
        assert NLQueryEngine._sanitize_sql(sql) == sql

    def test_keeps_valid_where_direction_on_invoices(self):
        sql = "SELECT * FROM invoices WHERE direction = 'SUPPLIER'"
        assert NLQueryEngine._sanitize_sql(sql) == sql


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


# ── query() with mocked LLM and DB ────────────────────────────────────────────

@pytest.fixture
def engine_mock():
    """SQLAlchemy engine mock that returns a configurable result set."""
    engine = MagicMock()
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    engine.connect.return_value = conn
    return engine, conn


def _make_rows(*dicts):
    """Build mock SQLAlchemy Row objects from dicts."""
    rows = []
    for d in dicts:
        row = MagicMock()
        row._mapping = d
        rows.append(row)
    return rows


class TestNLQueryEngineQuery:
    def test_successful_query_returns_all_fields(self, engine_mock):
        engine, conn = engine_mock
        conn.execute.return_value = _make_rows({"nb": 42})
        nl = NLQueryEngine(engine=engine)

        llm_json = '{"sql": "SELECT COUNT(*) AS nb FROM invoices", "explanation": "Comptage factures"}'
        with patch.object(nl, "_ask_llm", return_value=llm_json):
            result = nl.query("Combien de factures?")

        assert result["sql"] == "SELECT COUNT(*) AS nb FROM invoices"
        assert result["explanation"] == "Comptage factures"
        assert result["result"] == [{"nb": 42}]
        assert "42" in result["answer"]

    def test_null_sql_from_llm_returns_explanation(self, engine_mock):
        engine, _ = engine_mock
        nl = NLQueryEngine(engine=engine)
        llm_json = '{"sql": null, "explanation": "Je ne peux pas répondre."}'
        with patch.object(nl, "_ask_llm", return_value=llm_json):
            result = nl.query("Quelle est la météo?")

        assert result["sql"] is None
        assert result["result"] is None
        assert "Je ne peux pas répondre." in result["answer"]

    def test_unsafe_sql_rejected(self, engine_mock):
        engine, _ = engine_mock
        nl = NLQueryEngine(engine=engine)
        llm_json = '{"sql": "DELETE FROM invoices", "explanation": "Suppression"}'
        with patch.object(nl, "_ask_llm", return_value=llm_json):
            result = nl.query("Supprime tout")

        assert result["sql"] is None
        assert "SELECT" in result["answer"]  # error message mentions SELECT

    def test_sql_error_triggers_retry(self, engine_mock):
        engine, conn = engine_mock
        nl = NLQueryEngine(engine=engine)

        first_llm = '{"sql": "SELECT bad_col FROM invoices", "explanation": "Mauvaise requête"}'
        second_llm = '{"sql": "SELECT COUNT(*) AS nb FROM invoices", "explanation": "Requête corrigée"}'
        conn.execute.side_effect = [
            Exception("no such column: bad_col"),  # first attempt fails
            _make_rows({"nb": 3}),                  # retry succeeds
        ]

        with patch.object(nl, "_ask_llm", side_effect=[first_llm, second_llm]):
            result = nl.query("Test avec erreur")

        assert result["result"] == [{"nb": 3}]

    def test_unparsable_llm_response_returns_error(self, engine_mock):
        engine, _ = engine_mock
        nl = NLQueryEngine(engine=engine)
        with patch.object(nl, "_ask_llm", return_value="not json at all"):
            result = nl.query("Question sans réponse")

        assert result["sql"] is None
        assert result["result"] is None
        assert "non parsable" in result["answer"]

    def test_ollama_connection_error_returns_graceful_response(self, engine_mock):
        engine, _ = engine_mock
        nl = NLQueryEngine(engine=engine, ollama_url="http://localhost:99999")
        # _ask_llm catches ConnectionError and returns JSON fallback internally
        result = nl.query("Test connexion")
        # Should not raise — just return None SQL
        assert "question" in result

    def test_empty_result_set(self, engine_mock):
        engine, conn = engine_mock
        conn.execute.return_value = []
        nl = NLQueryEngine(engine=engine)

        llm_json = '{"sql": "SELECT * FROM invoices WHERE issuer_name = \'Inconnu\'", "explanation": "Recherche"}'
        with patch.object(nl, "_ask_llm", return_value=llm_json):
            result = nl.query("Factures de Inconnu")

        assert result["result"] == []
        assert "Aucun résultat" in result["answer"]

    def test_sanitize_applied_to_llm_sql(self, engine_mock):
        engine, conn = engine_mock
        conn.execute.return_value = _make_rows({"total": 1000.0})
        nl = NLQueryEngine(engine=engine)

        dirty_sql = (
            "SELECT SUM(jl.debit) FROM journal_lines jl "
            "JOIN journal_entries je ON jl.entry_id = je.id "
            "AND je.direction = 'SUPPLIER'"
        )
        llm_json = f'{{"sql": "{dirty_sql}", "explanation": "Test"}}'
        with patch.object(nl, "_ask_llm", return_value=llm_json):
            result = nl.query("Total débit fournisseurs")

        # sanitize should strip the invalid je.direction condition before execution
        executed_sql = conn.execute.call_args[0][0].text
        assert "je.direction" not in executed_sql
