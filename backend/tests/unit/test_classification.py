"""Unit tests for the classification module."""
from __future__ import annotations

import pytest



from src.classification.accounting_coder import AccountingCoder
from src.classification.classifier import Classifier
from src.classification.matcher import (
    contains_any,
    fuzzy_match,
    normalise,
)
from src.cost_catalog.catalog import CostCatalog
from src.models.enums import ChargeNature, ChargeType, FlagType, InvoiceDirection
from src.models.invoice import ConfidenceField, InvoiceRecord, LineItem


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _invoice(**kwargs) -> InvoiceRecord:
    base = dict(file_hash="abc123", raw_file_path="/tmp/inv.pdf")
    base.update(kwargs)
    return InvoiceRecord(**base)


def _with_field(invoice: InvoiceRecord, field: str, value: str) -> InvoiceRecord:
    setattr(invoice, field, ConfidenceField(value=value, confidence=0.9))
    return invoice


CLASSIFICATION_RULES = [
    {
        "name": "biat_it_as_recipient",
        "condition": {"field": "recipient_tax_id", "matches": r"^BIAT"},
        "result": "SUPPLIER",
    },
    {
        "name": "biat_it_as_issuer",
        "condition": {"field": "issuer_tax_id", "matches": r"^BIAT"},
        "result": "CLIENT",
    },
    {
        "name": "biat_it_name_recipient",
        "condition": {
            "field": "recipient_name",
            "contains_any": ["BIAT IT", "BIAT INFORMATIQUE"],
        },
        "result": "SUPPLIER",
    },
    {
        "name": "biat_it_name_issuer",
        "condition": {
            "field": "issuer_name",
            "contains_any": ["BIAT IT", "BIAT INFORMATIQUE"],
        },
        "result": "CLIENT",
    },
    {
        "name": "default",
        "result": "UNKNOWN",
    },
]

_MINI_CATALOG_YAML = """
entries:
  - id: maintenance_informatique
    label: Maintenance et support informatique
    compte: "6112"
    nature: fixe
    type_charge: OPEX
    tva_rate: 19
    recurrence: mensuelle
    flux: fournisseur
    keywords: [maintenance informatique, support informatique]

  - id: logiciels_acquis
    label: Logiciels acquis (licences perpétuelles)
    compte: "2284"
    nature: fixe
    type_charge: CAPEX
    tva_rate: 19
    recurrence: ponctuelle
    flux: fournisseur
    keywords: [logiciel, licence, SaaS, SAAS]

  - id: prestations_si
    label: Prestations de services informatiques
    compte: "7061"
    nature: variable
    type_charge: OPEX
    tva_rate: 19
    recurrence: mensuelle
    flux: client
    keywords: [prestation informatique, service informatique, prestation de développement]
"""


@pytest.fixture
def mini_catalog(tmp_path) -> CostCatalog:
    f = tmp_path / "mini.yaml"
    f.write_text(_MINI_CATALOG_YAML, encoding="utf-8")
    return CostCatalog.from_yaml(f)


# ── Normalise & fuzzy helpers ─────────────────────────────────────────────────

class TestNormalise:
    def test_lowercases(self):
        assert normalise("ABC") == "abc"

    def test_strips_accents(self):
        assert normalise("éàü") == "eau"

    def test_removes_punctuation(self):
        assert normalise("hello, world!") == "hello world"

    def test_collapses_whitespace(self):
        assert normalise("a  b   c") == "a b c"

    def test_empty_string(self):
        assert normalise("") == ""


class TestFuzzyMatch:
    def test_identical_strings_match(self):
        assert fuzzy_match("BIAT IT", "BIAT IT") is True

    def test_similar_strings_match(self):
        assert fuzzy_match("BIAT Informatique", "BIAT Informtique") is True  # typo

    def test_very_different_strings_no_match(self):
        assert fuzzy_match("Apple Inc", "Microsoft Corp") is False

    def test_case_insensitive(self):
        assert fuzzy_match("biat it", "BIAT IT") is True


class TestContainsAny:
    def test_exact_keyword_found(self):
        assert contains_any("BIAT IT SARL", ["BIAT IT"]) is True

    def test_keyword_not_found(self):
        assert contains_any("Acme Corp", ["BIAT IT", "BIAT INFORMATIQUE"]) is False

    def test_accented_keyword_found(self):
        assert contains_any("Société de Maintenance", ["maintenance"]) is True

    def test_multiple_keywords_first_matches(self):
        assert contains_any("BIAT INFORMATIQUE", ["OTHER", "BIAT INFORMATIQUE"]) is True


# ── Classifier ────────────────────────────────────────────────────────────────

class TestClassifier:
    def setup_method(self):
        self.clf = Classifier(rules=CLASSIFICATION_RULES)

    def test_tax_id_match_supplier(self):
        inv = _invoice(file_hash="h1", raw_file_path="/f")
        inv = _with_field(inv, "recipient_tax_id", "BIAT/1234/A/P/000")
        inv = self.clf.classify(inv)
        assert inv.direction == InvoiceDirection.SUPPLIER

    def test_tax_id_match_client(self):
        inv = _invoice(file_hash="h2", raw_file_path="/f")
        inv = _with_field(inv, "issuer_tax_id", "BIAT/5678/A/P/000")
        inv = self.clf.classify(inv)
        assert inv.direction == InvoiceDirection.CLIENT

    def test_name_fallback_supplier(self):
        inv = _invoice(file_hash="h3", raw_file_path="/f")
        inv = _with_field(inv, "recipient_name", "BIAT IT SARL")
        inv = self.clf.classify(inv)
        assert inv.direction == InvoiceDirection.SUPPLIER

    def test_name_fallback_client(self):
        inv = _invoice(file_hash="h4", raw_file_path="/f")
        inv = _with_field(inv, "issuer_name", "BIAT INFORMATIQUE")
        inv = self.clf.classify(inv)
        assert inv.direction == InvoiceDirection.CLIENT

    def test_default_unknown(self):
        inv = _invoice(file_hash="h5", raw_file_path="/f")
        inv = self.clf.classify(inv)
        assert inv.direction == InvoiceDirection.UNKNOWN

    def test_unknown_adds_flag(self):
        inv = _invoice(file_hash="h6", raw_file_path="/f")
        inv = self.clf.classify(inv)
        flag_types = [f.flag_type for f in inv.flags]
        assert FlagType.UNKNOWN_DIRECTION in flag_types

    def test_known_direction_no_unknown_flag(self):
        inv = _invoice(file_hash="h7", raw_file_path="/f")
        inv = _with_field(inv, "recipient_tax_id", "BIAT/000")
        inv = self.clf.classify(inv)
        flag_types = [f.flag_type for f in inv.flags]
        assert FlagType.UNKNOWN_DIRECTION not in flag_types

    def test_null_field_does_not_match(self):
        # recipient_tax_id has no value → rule skipped → falls to default
        inv = _invoice(file_hash="h8", raw_file_path="/f")
        inv.recipient_tax_id = ConfidenceField(value=None)
        inv = self.clf.classify(inv)
        assert inv.direction == InvoiceDirection.UNKNOWN

    def test_first_matching_rule_wins(self):
        # Both issuer_tax_id and recipient_tax_id start with BIAT — recipient rule comes first
        inv = _invoice(file_hash="h9", raw_file_path="/f")
        inv = _with_field(inv, "recipient_tax_id", "BIAT/R/000")
        inv = _with_field(inv, "issuer_tax_id", "BIAT/I/000")
        inv = self.clf.classify(inv)
        assert inv.direction == InvoiceDirection.SUPPLIER


# ── AccountingCoder ───────────────────────────────────────────────────────────

class TestAccountingCoder:
    def _supplier_invoice(self, description: str | None = None, hash_: str = "ac1") -> InvoiceRecord:
        inv = _invoice(file_hash=hash_, raw_file_path="/f")
        inv.direction = InvoiceDirection.SUPPLIER
        if description:
            inv.line_items = [LineItem(line_number=1, description=description)]
        return inv

    def _client_invoice(self, description: str | None = None, hash_: str = "ac2") -> InvoiceRecord:
        inv = _invoice(file_hash=hash_, raw_file_path="/f")
        inv.direction = InvoiceDirection.CLIENT
        if description:
            inv.line_items = [LineItem(line_number=1, description=description)]
        return inv

    def test_supplier_keyword_match_sets_catalog_id(self, mini_catalog):
        coder = AccountingCoder(catalog=mini_catalog)
        inv = self._supplier_invoice("Licence logiciel ERP annuelle")
        inv = coder.assign(inv)
        assert inv.cost_catalog_id == "logiciels_acquis"
        assert inv.accounting_compte == "2284"
        assert "Logiciels" in inv.accounting_label

    def test_supplier_maintenance_match(self, mini_catalog):
        coder = AccountingCoder(catalog=mini_catalog)
        inv = self._supplier_invoice("Maintenance informatique serveur et support technique")
        inv = coder.assign(inv)
        assert inv.cost_catalog_id == "maintenance_informatique"
        assert inv.accounting_compte == "6112"

    def test_charge_nature_and_type_populated(self, mini_catalog):
        coder = AccountingCoder(catalog=mini_catalog)
        inv = self._supplier_invoice("Maintenance informatique réseau")
        inv = coder.assign(inv)
        assert inv.charge_nature == ChargeNature.FIXE
        assert inv.charge_type == ChargeType.OPEX

    def test_capex_type_charge(self, mini_catalog):
        coder = AccountingCoder(catalog=mini_catalog)
        inv = self._supplier_invoice("Licence logiciel perpétuelle ERP")
        inv = coder.assign(inv)
        assert inv.charge_type == ChargeType.CAPEX

    def test_client_keyword_match(self, mini_catalog):
        coder = AccountingCoder(catalog=mini_catalog)
        inv = self._client_invoice("Prestation de développement logiciel")
        inv = coder.assign(inv)
        assert inv.cost_catalog_id == "prestations_si"
        assert inv.accounting_compte == "7061"

    def test_unknown_direction_no_assignment(self, mini_catalog):
        coder = AccountingCoder(catalog=mini_catalog)
        inv = _invoice(file_hash="ac3", raw_file_path="/f")
        inv.direction = InvoiceDirection.UNKNOWN
        inv = coder.assign(inv)
        assert inv.cost_catalog_id is None
        assert inv.accounting_compte is None

    def test_no_match_adds_warning_flag(self, mini_catalog):
        coder = AccountingCoder(catalog=mini_catalog)
        inv = self._supplier_invoice("xyzzy foobar qux incompréhensible", hash_="ac5")
        inv = coder.assign(inv)
        assert inv.cost_catalog_id is None
        flag_fields = [f.field_name for f in inv.flags]
        assert "cost_catalog_id" in flag_fields

    def test_keyword_match_from_issuer_name(self, mini_catalog):
        coder = AccountingCoder(catalog=mini_catalog)
        inv = _invoice(file_hash="ac4", raw_file_path="/f")
        inv.direction = InvoiceDirection.SUPPLIER
        inv = _with_field(inv, "issuer_name", "SAAS Solutions Tunisia")
        inv = coder.assign(inv)
        assert inv.accounting_compte == "2284"

    def test_case_insensitive_keyword(self, mini_catalog):
        coder = AccountingCoder(catalog=mini_catalog)
        inv = self._supplier_invoice("LICENCE Microsoft Office 365")
        inv = coder.assign(inv)
        assert inv.accounting_compte == "2284"

    # ── last_match_confidence / last_match_pass ─────────────────────────────

    def test_rules_match_sets_confidence_and_pass(self, mini_catalog):
        """Passe A (règles) — la confiance doit refléter le vrai score du
        catalogue, pas une valeur fixe (voir classification_agent.py)."""
        coder = AccountingCoder(catalog=mini_catalog)
        inv = self._supplier_invoice("Licence logiciel ERP annuelle")
        coder.assign(inv)
        assert coder.last_match_pass == "RULES"
        assert coder.last_match_confidence == pytest.approx(1.0)

    def test_no_match_leaves_confidence_and_pass_none(self, mini_catalog):
        coder = AccountingCoder(catalog=mini_catalog)
        inv = self._supplier_invoice("xyzzy foobar qux incompréhensible", hash_="ac6")
        coder.assign(inv)
        assert coder.last_match_pass is None
        assert coder.last_match_confidence is None

    def test_unknown_direction_leaves_confidence_and_pass_none(self, mini_catalog):
        coder = AccountingCoder(catalog=mini_catalog)
        inv = _invoice(file_hash="ac7", raw_file_path="/f")
        inv.direction = InvoiceDirection.UNKNOWN
        coder.assign(inv)
        assert coder.last_match_pass is None
        assert coder.last_match_confidence is None

    def test_ml_fallback_sets_confidence_and_pass(self, mini_catalog):
        """Passe B (ML) — utilisée seulement si la passe A ne trouve rien."""
        from unittest.mock import MagicMock

        ml = MagicMock()
        ml.is_trained.return_value = True
        ml.predict.return_value = ("logiciels_acquis", 0.73)
        coder = AccountingCoder(catalog=mini_catalog, ml_classifier=ml, ml_confidence_threshold=0.60)

        inv = self._supplier_invoice("xyzzy foobar qux incompréhensible", hash_="ac8")
        inv = coder.assign(inv)

        assert inv.cost_catalog_id == "logiciels_acquis"
        assert coder.last_match_pass == "ML"
        assert coder.last_match_confidence == pytest.approx(0.73)

    def test_ml_below_threshold_is_not_used(self, mini_catalog):
        from unittest.mock import MagicMock

        ml = MagicMock()
        ml.is_trained.return_value = True
        ml.predict.return_value = ("logiciels_acquis", 0.40)
        coder = AccountingCoder(catalog=mini_catalog, ml_classifier=ml, ml_confidence_threshold=0.60)

        inv = self._supplier_invoice("xyzzy foobar qux incompréhensible", hash_="ac9")
        inv = coder.assign(inv)

        assert inv.cost_catalog_id is None
        assert coder.last_match_pass is None
        assert coder.last_match_confidence is None


