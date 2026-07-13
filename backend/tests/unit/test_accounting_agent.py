"""Unit tests for src/ai_agents/accounting_agent.py — all Ollama/Mongo calls mocked."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from src.models.enums import ChargeFlux, ChargeNature, ChargeType, Recurrence
from src.models.invoice import InvoiceRecord
from src.models.journal import JournalEntry, JournalLine
from src.cost_catalog.catalog import CostCatalogEntry


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_ollama(available: bool = True, response: str | None = None):
    mock = MagicMock()
    mock.is_available.return_value = available
    mock.complete.return_value = response
    return mock


def _reset_ollama_singleton():
    import src.ai_agents.ollama_client as mod
    mod.OllamaClient._instance = None


def _make_invoice(**overrides) -> InvoiceRecord:
    inv = InvoiceRecord(file_hash="a" * 64, raw_file_path="/tmp/test.pdf")
    inv.amount_ht.value = overrides.pop("amount_ht", 1000.0)
    inv.amount_ttc.value = overrides.pop("amount_ttc", 1190.0)
    inv.invoice_date.value = overrides.pop("invoice_date", date(2026, 6, 1))
    inv.issuer_name.value = overrides.pop("issuer_name", "ACME Tunisie")
    for key, value in overrides.items():
        setattr(inv, key, value)
    return inv


def _make_catalog_entry(**overrides) -> CostCatalogEntry:
    defaults = dict(
        id="hebergement",
        label="Hébergement cloud",
        compte="6135",
        nature=ChargeNature.FIXE,
        type_charge=ChargeType.OPEX,
        tva_rate=19.0,
        recurrence=Recurrence.MENSUELLE,
        flux=ChargeFlux.FOURNISSEUR,
    )
    defaults.update(overrides)
    return CostCatalogEntry(**defaults)


def _make_balanced_entry(compte: str = "6135") -> JournalEntry:
    return JournalEntry(
        reference="FACT-001",
        date_ecriture=date(2026, 6, 1),
        description="Facture ACME",
        lines=[
            JournalLine(compte=compte, libelle="Charge", debit=1000.0),
            JournalLine(compte="4366", libelle="TVA déductible", debit=190.0),
            JournalLine(compte="401", libelle="Fournisseurs", credit=1190.0),
        ],
    )


@pytest.fixture
def agent_parts():
    """(agent, entry_gen, journal_repo, catalog) with Ollama unavailable by default."""
    _reset_ollama_singleton()
    entry_gen = MagicMock()
    journal_repo = MagicMock()
    catalog = MagicMock()
    with patch("src.ai_agents.base_agent.OllamaClient.get", return_value=_mock_ollama(available=False)):
        from src.ai_agents.accounting_agent import AccountingAgent
        agent = AccountingAgent(entry_gen, journal_repo, catalog)
    return agent, entry_gen, journal_repo, catalog


# ── run() — end-to-end orchestration of the 3 sub-steps ────────────────────────

class TestRun:
    def test_opex_invoice_posts_journal_only(self, agent_parts):
        agent, entry_gen, journal_repo, catalog = agent_parts
        entry = _make_balanced_entry()
        entry_gen.generate.return_value = entry
        catalog_entry = _make_catalog_entry()
        catalog.get.return_value = catalog_entry
        invoice = _make_invoice(cost_catalog_id="hebergement", charge_type=ChargeType.OPEX)

        with patch("src.ai_agents.accounting_agent.OllamaClient.get",
                   return_value=_mock_ollama(available=False)):
            result = agent.run({"invoice": invoice})

        assert result.success is True
        assert result.output["journal_entry_id"] == str(entry.id)
        assert result.output["is_balanced"] is True
        assert result.output["asset_created"] is False
        assert result.output["installments_created"] == 0
        journal_repo.save.assert_called_once_with(entry)

    def test_no_catalog_id_skips_journal(self, agent_parts):
        agent, entry_gen, journal_repo, catalog = agent_parts
        invoice = _make_invoice(cost_catalog_id=None)

        result = agent.run({"invoice": invoice})

        assert result.success is True
        assert result.output["journal_entry_id"] is None
        assert result.output["is_balanced"] is False
        entry_gen.generate.assert_not_called()
        journal_repo.save.assert_not_called()

    def test_capex_invoice_creates_asset(self, agent_parts):
        agent, entry_gen, journal_repo, catalog = agent_parts
        entry_gen.generate.return_value = _make_balanced_entry(compte="2183")
        catalog_entry = _make_catalog_entry(
            id="materiel-info", compte="2183", type_charge=ChargeType.CAPEX,
        )
        catalog.get.return_value = catalog_entry
        invoice = _make_invoice(cost_catalog_id="materiel-info", charge_type=ChargeType.CAPEX)

        mock_repo = MagicMock()
        with (
            patch("src.ai_agents.accounting_agent.OllamaClient.get",
                  return_value=_mock_ollama(available=False)),
            patch("src.storage.sync_mongo_repository.SyncMongoAssetRepository",
                  return_value=mock_repo),
        ):
            result = agent.run({"invoice": invoice})

        assert result.success is True
        assert result.output["asset_created"] is True
        assert result.output["asset_id"] is not None
        assert result.output["amortization_years"] == 5
        assert result.output["amortization_source"] == "DEFAULT"
        mock_repo.save.assert_called_once()
        saved_asset = mock_repo.save.call_args[0][0]
        assert saved_asset.compte_immobilisation == "2183"
        assert saved_asset.compte_amortissement == "28183"

    def test_opex_invoice_does_not_create_asset(self, agent_parts):
        agent, entry_gen, journal_repo, catalog = agent_parts
        entry_gen.generate.return_value = _make_balanced_entry()
        catalog.get.return_value = _make_catalog_entry()
        invoice = _make_invoice(cost_catalog_id="hebergement", charge_type=ChargeType.OPEX)

        result = agent.run({"invoice": invoice})

        assert result.output["asset_created"] is False
        assert result.output["asset_id"] is None

    def test_payment_term_creates_installments(self, agent_parts):
        agent, entry_gen, journal_repo, catalog = agent_parts
        entry_gen.generate.return_value = _make_balanced_entry()
        catalog.get.return_value = _make_catalog_entry()
        invoice = _make_invoice(
            cost_catalog_id="hebergement", charge_type=ChargeType.OPEX,
            payment_term_days=45,
        )

        with patch(
            "src.storage.sync_mongo_repository.save_payment_installments_sync",
            return_value=["inst-1", "inst-2"],
        ) as mock_save:
            result = agent.run({"invoice": invoice})

        assert result.success is True
        assert result.output["installments_created"] == 2
        assert result.output["installment_ids"] == ["inst-1", "inst-2"]
        mock_save.assert_called_once()

    def test_no_payment_term_skips_installments(self, agent_parts):
        agent, entry_gen, journal_repo, catalog = agent_parts
        entry_gen.generate.return_value = _make_balanced_entry()
        catalog.get.return_value = _make_catalog_entry()
        invoice = _make_invoice(
            cost_catalog_id="hebergement", charge_type=ChargeType.OPEX,
            payment_term_days=None,
        )

        result = agent.run({"invoice": invoice})

        assert result.output["installments_created"] == 0
        assert result.output["installment_ids"] == []

    def test_unexpected_exception_returns_failure(self, agent_parts):
        agent, entry_gen, journal_repo, catalog = agent_parts
        catalog.get.side_effect = RuntimeError("catalog crashed")
        invoice = _make_invoice(cost_catalog_id="hebergement")

        result = agent.run({"invoice": invoice})

        assert result.success is False
        assert "catalog crashed" in result.error


# ── _post_journal ────────────────────────────────────────────────────────────

class TestPostJournal:
    def test_no_catalog_entry_returns_none(self, agent_parts):
        agent, entry_gen, journal_repo, catalog = agent_parts
        invoice = _make_invoice()

        journal_id, is_balanced, explanation = agent._post_journal(invoice, None)

        assert journal_id is None
        assert is_balanced is False
        assert explanation == ""
        entry_gen.generate.assert_not_called()

    def test_generator_exception_is_caught(self, agent_parts):
        agent, entry_gen, journal_repo, catalog = agent_parts
        entry_gen.generate.side_effect = RuntimeError("generation failed")
        invoice = _make_invoice()
        catalog_entry = _make_catalog_entry()

        journal_id, is_balanced, explanation = agent._post_journal(invoice, catalog_entry)

        assert journal_id is None
        assert is_balanced is False
        assert explanation == ""
        journal_repo.save.assert_not_called()

    def test_balanced_entry_is_saved(self, agent_parts):
        agent, entry_gen, journal_repo, catalog = agent_parts
        entry = _make_balanced_entry()
        entry_gen.generate.return_value = entry
        invoice = _make_invoice()
        catalog_entry = _make_catalog_entry()

        with patch("src.ai_agents.accounting_agent.OllamaClient.get",
                   return_value=_mock_ollama(available=False)):
            journal_id, is_balanced, explanation = agent._post_journal(invoice, catalog_entry)

        assert journal_id == str(entry.id)
        assert is_balanced is True
        journal_repo.save.assert_called_once_with(entry)
        assert entry.accounting_explanation == explanation


# ── _generate_accounting_explanation ────────────────────────────────────────

class TestGenerateAccountingExplanation:
    def test_ollama_unavailable_returns_empty_string(self, agent_parts):
        agent, *_ = agent_parts
        entry = _make_balanced_entry()
        invoice = _make_invoice()

        with patch("src.ai_agents.accounting_agent.OllamaClient.get",
                   return_value=_mock_ollama(available=False)):
            explanation = agent._generate_accounting_explanation(invoice, entry)

        assert explanation == ""

    def test_ollama_available_returns_trimmed_response(self, agent_parts):
        agent, *_ = agent_parts
        entry = _make_balanced_entry()
        invoice = _make_invoice()
        long_response = "x" * 300

        with patch("src.ai_agents.accounting_agent.OllamaClient.get",
                   return_value=_mock_ollama(available=True, response=f"  {long_response}  ")):
            explanation = agent._generate_accounting_explanation(invoice, entry)

        assert explanation == long_response[:250]

    def test_ollama_exception_returns_empty_string(self, agent_parts):
        agent, *_ = agent_parts
        entry = _make_balanced_entry()
        invoice = _make_invoice()
        broken_ollama = MagicMock()
        broken_ollama.is_available.return_value = True
        broken_ollama.complete.side_effect = RuntimeError("ollama down")

        with patch("src.ai_agents.accounting_agent.OllamaClient.get", return_value=broken_ollama):
            explanation = agent._generate_accounting_explanation(invoice, entry)

        assert explanation == ""


# ── _create_capex_asset ──────────────────────────────────────────────────────

class TestCreateCapexAsset:
    def test_no_catalog_entry_returns_all_none(self, agent_parts):
        agent, *_ = agent_parts
        invoice = _make_invoice()

        asset_id, years, source = agent._create_capex_asset(invoice, None)

        assert (asset_id, years, source) == (None, None, None)

    def test_repository_exception_is_caught(self, agent_parts):
        agent, *_ = agent_parts
        invoice = _make_invoice(line_items=[])
        catalog_entry = _make_catalog_entry(compte="2183", type_charge=ChargeType.CAPEX)

        with (
            patch("src.ai_agents.accounting_agent.OllamaClient.get",
                  return_value=_mock_ollama(available=False)),
            patch("src.storage.sync_mongo_repository.SyncMongoAssetRepository",
                  side_effect=RuntimeError("mongo down")),
        ):
            asset_id, years, source = agent._create_capex_asset(invoice, catalog_entry)

        assert asset_id is None
        assert years == 5
        assert source == "DEFAULT"

    def test_short_compte_falls_back_to_default_amortissement(self, agent_parts):
        agent, *_ = agent_parts
        invoice = _make_invoice(line_items=[])
        catalog_entry = _make_catalog_entry(compte="21", type_charge=ChargeType.CAPEX)
        mock_repo = MagicMock()

        with (
            patch("src.ai_agents.accounting_agent.OllamaClient.get",
                  return_value=_mock_ollama(available=False)),
            patch("src.storage.sync_mongo_repository.SyncMongoAssetRepository",
                  return_value=mock_repo),
        ):
            agent._create_capex_asset(invoice, catalog_entry)

        saved_asset = mock_repo.save.call_args[0][0]
        assert saved_asset.compte_amortissement == "28184"

    def test_description_uses_first_line_item_when_present(self, agent_parts):
        agent, *_ = agent_parts
        from src.models.invoice import LineItem
        invoice = _make_invoice(
            line_items=[LineItem(line_number=1, description="Serveur Dell R740")],
        )
        catalog_entry = _make_catalog_entry(
            label="Matériel informatique", compte="2183", type_charge=ChargeType.CAPEX,
        )
        mock_repo = MagicMock()

        with (
            patch("src.ai_agents.accounting_agent.OllamaClient.get",
                  return_value=_mock_ollama(available=False)),
            patch("src.storage.sync_mongo_repository.SyncMongoAssetRepository",
                  return_value=mock_repo),
        ):
            agent._create_capex_asset(invoice, catalog_entry)

        saved_asset = mock_repo.save.call_args[0][0]
        assert saved_asset.designation == "Serveur Dell R740"

    def test_description_falls_back_to_catalog_label(self, agent_parts):
        agent, *_ = agent_parts
        invoice = _make_invoice(line_items=[])
        catalog_entry = _make_catalog_entry(
            label="Serveur physique", compte="2183", type_charge=ChargeType.CAPEX,
        )
        mock_repo = MagicMock()

        with (
            patch("src.ai_agents.accounting_agent.OllamaClient.get",
                  return_value=_mock_ollama(available=False)),
            patch("src.storage.sync_mongo_repository.SyncMongoAssetRepository",
                  return_value=mock_repo),
        ):
            agent._create_capex_asset(invoice, catalog_entry)

        saved_asset = mock_repo.save.call_args[0][0]
        assert saved_asset.designation == "Serveur physique"


# ── _get_amortization_duration ──────────────────────────────────────────────

class TestGetAmortizationDuration:
    def test_ollama_unavailable_returns_default_5_years(self, agent_parts):
        agent, *_ = agent_parts
        catalog_entry = _make_catalog_entry()

        with patch("src.ai_agents.accounting_agent.OllamaClient.get",
                   return_value=_mock_ollama(available=False)):
            years, source = agent._get_amortization_duration("Serveur", catalog_entry)

        assert (years, source) == (5, "DEFAULT")

    def test_ollama_returns_bare_integer(self, agent_parts):
        agent, *_ = agent_parts
        catalog_entry = _make_catalog_entry()

        with patch("src.ai_agents.accounting_agent.OllamaClient.get",
                   return_value=_mock_ollama(available=True, response="3")):
            years, source = agent._get_amortization_duration("Logiciel", catalog_entry)

        assert (years, source) == (3, "AI")

    def test_ollama_returns_number_embedded_in_text(self, agent_parts):
        agent, *_ = agent_parts
        catalog_entry = _make_catalog_entry()

        with patch("src.ai_agents.accounting_agent.OllamaClient.get",
                   return_value=_mock_ollama(available=True, response="Réponse: 7 ans")):
            years, source = agent._get_amortization_duration("Véhicule", catalog_entry)

        assert (years, source) == (7, "AI")

    def test_ollama_returns_out_of_range_falls_back(self, agent_parts):
        agent, *_ = agent_parts
        catalog_entry = _make_catalog_entry()

        with patch("src.ai_agents.accounting_agent.OllamaClient.get",
                   return_value=_mock_ollama(available=True, response="99")):
            years, source = agent._get_amortization_duration("Bâtiment", catalog_entry)

        assert (years, source) == (5, "DEFAULT")

    def test_ollama_returns_unparseable_text_falls_back(self, agent_parts):
        agent, *_ = agent_parts
        catalog_entry = _make_catalog_entry()

        with patch("src.ai_agents.accounting_agent.OllamaClient.get",
                   return_value=_mock_ollama(available=True, response="je ne sais pas")):
            years, source = agent._get_amortization_duration("Mobilier", catalog_entry)

        assert (years, source) == (5, "DEFAULT")


# ── _create_payment_schedule ─────────────────────────────────────────────────

class TestCreatePaymentSchedule:
    def test_no_payment_term_returns_empty_list(self, agent_parts):
        agent, *_ = agent_parts
        invoice = _make_invoice(payment_term_days=None)

        assert agent._create_payment_schedule(invoice) == []

    def test_no_amount_ttc_returns_empty_list(self, agent_parts):
        agent, *_ = agent_parts
        invoice = _make_invoice(payment_term_days=30, amount_ttc=None)

        assert agent._create_payment_schedule(invoice) == []

    def test_single_installment_within_one_period(self, agent_parts):
        agent, *_ = agent_parts
        invoice = _make_invoice(payment_term_days=20, amount_ttc=1000.0)

        with patch(
            "src.storage.sync_mongo_repository.save_payment_installments_sync",
            return_value=["inst-1"],
        ) as mock_save:
            ids = agent._create_payment_schedule(invoice)

        assert ids == ["inst-1"]
        rows = mock_save.call_args[0][0]
        assert len(rows) == 1
        assert rows[0]["total_installments"] == 1
        assert rows[0]["base_amount"] == 1000.0

    def test_two_installments_with_remainder(self, agent_parts):
        agent, *_ = agent_parts
        invoice = _make_invoice(payment_term_days=45, amount_ttc=900.0)

        with patch(
            "src.storage.sync_mongo_repository.save_payment_installments_sync",
            return_value=["inst-1", "inst-2"],
        ) as mock_save:
            agent._create_payment_schedule(invoice)

        rows = mock_save.call_args[0][0]
        assert len(rows) == 2
        assert rows[0]["installment_number"] == 1
        assert rows[1]["installment_number"] == 2
        assert rows[0]["total_installments"] == 2
        assert round(rows[0]["base_amount"] + rows[1]["base_amount"] - 900.0, 3) == 0 or \
            abs(rows[0]["base_amount"] * 2 - 900.0) < 0.01

    def test_save_exception_returns_empty_list(self, agent_parts):
        agent, *_ = agent_parts
        invoice = _make_invoice(payment_term_days=30, amount_ttc=500.0)

        with patch(
            "src.storage.sync_mongo_repository.save_payment_installments_sync",
            side_effect=RuntimeError("mongo down"),
        ):
            ids = agent._create_payment_schedule(invoice)

        assert ids == []


# ── check_consistency ────────────────────────────────────────────────────────

class TestCheckConsistency:
    def test_delegates_to_sync_mongo_repository(self, agent_parts):
        agent, *_ = agent_parts
        expected = {"balanced": 10, "unbalanced": 0}

        with patch(
            "src.storage.sync_mongo_repository.journal_consistency_check_sync",
            return_value=expected,
        ):
            result = agent.check_consistency()

        assert result == expected

    def test_works_without_journal_repo(self):
        """journal_repo is only needed by run(), not check_consistency() — see __init__ docstring."""
        _reset_ollama_singleton()
        from src.ai_agents.accounting_agent import AccountingAgent
        agent = AccountingAgent(MagicMock(), journal_repo=None, cost_catalog=MagicMock())
        expected = {"balanced": 1, "unbalanced": 1}

        with patch(
            "src.storage.sync_mongo_repository.journal_consistency_check_sync",
            return_value=expected,
        ):
            result = agent.check_consistency()

        assert result == expected
