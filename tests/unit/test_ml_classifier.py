"""Unit tests for MLClassifier."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from src.classification.ml_classifier import MLClassifier


@pytest.fixture
def tmp_model_path(tmp_path: Path) -> Path:
    return tmp_path / "ml_model.joblib"


# ── Untrained behaviour ───────────────────────────────────────────────────────

class TestUntrainedClassifier:
    def test_is_trained_returns_false_when_no_model_file(self, tmp_model_path):
        clf = MLClassifier(model_path=tmp_model_path)
        assert clf.is_trained() is False

    def test_predict_returns_none_and_zero_when_untrained(self, tmp_model_path):
        clf = MLClassifier(model_path=tmp_model_path)
        result = clf.predict("maintenance informatique serveurs")
        assert result == (None, 0.0)

    def test_predict_empty_string_when_untrained(self, tmp_model_path):
        clf = MLClassifier(model_path=tmp_model_path)
        label, conf = clf.predict("")
        assert label is None
        assert conf == 0.0


# ── Training ──────────────────────────────────────────────────────────────────

class TestFitAndPredict:
    _TEXTS = [
        "maintenance informatique serveurs support technique",
        "maintenance support systèmes informatiques TMA",
        "loyer bureau immeuble mensuel",
        "loyer local commercial mensuel bail",
        "électricité STEG consommation énergie",
        "électricité eau STEG facture énergie",
    ]
    _LABELS = [
        "maintenance_informatique",
        "maintenance_informatique",
        "loyer_bureau",
        "loyer_bureau",
        "electricite_steg",
        "electricite_steg",
    ]

    def test_is_trained_after_fit(self, tmp_model_path):
        clf = MLClassifier(model_path=tmp_model_path)
        clf.fit(self._TEXTS, self._LABELS)
        assert clf.is_trained() is True

    def test_predict_known_class(self, tmp_model_path):
        clf = MLClassifier(model_path=tmp_model_path)
        clf.fit(self._TEXTS, self._LABELS)
        label, conf = clf.predict("maintenance informatique")
        assert label == "maintenance_informatique"
        assert conf > 0.3  # small training set — just verify correct class wins

    def test_predict_returns_float_confidence(self, tmp_model_path):
        clf = MLClassifier(model_path=tmp_model_path)
        clf.fit(self._TEXTS, self._LABELS)
        _, conf = clf.predict("loyer bureau mensuel")
        assert isinstance(conf, float)
        assert 0.0 <= conf <= 1.0

    def test_fit_raises_on_mismatched_lengths(self, tmp_model_path):
        clf = MLClassifier(model_path=tmp_model_path)
        with pytest.raises(ValueError):
            clf.fit(["text a", "text b"], ["label_a"])

    def test_fit_raises_on_too_few_samples(self, tmp_model_path):
        clf = MLClassifier(model_path=tmp_model_path)
        with pytest.raises(ValueError):
            clf.fit([], [])


# ── Persistence ───────────────────────────────────────────────────────────────

class TestPersistence:
    _TEXTS = [
        "facture loyer mensuel bureau",
        "loyer immeuble bail mensuel",
        "loyer local commercial mensuel",
        "maintenance serveurs informatiques support",
        "support technique mensuel TMA serveurs",
    ]
    _LABELS = [
        "loyer_bureau",
        "loyer_bureau",
        "loyer_bureau",
        "maintenance_informatique",
        "maintenance_informatique",
    ]

    def test_model_file_created_after_fit(self, tmp_model_path):
        clf = MLClassifier(model_path=tmp_model_path)
        clf.fit(self._TEXTS, self._LABELS)
        assert tmp_model_path.exists()

    def test_loaded_model_predicts_same_as_fitted(self, tmp_model_path):
        clf1 = MLClassifier(model_path=tmp_model_path)
        clf1.fit(self._TEXTS, self._LABELS)
        label1, conf1 = clf1.predict("maintenance informatique")

        clf2 = MLClassifier(model_path=tmp_model_path)
        assert clf2.is_trained()
        label2, conf2 = clf2.predict("maintenance informatique")

        assert label1 == label2
        assert conf1 == pytest.approx(conf2)

    def test_nonexistent_model_path_is_not_trained(self, tmp_path):
        clf = MLClassifier(model_path=tmp_path / "nonexistent.joblib")
        assert clf.is_trained() is False


# ── Retrain from repository ───────────────────────────────────────────────────

class TestRetrainFromRepo:
    def test_retrain_skips_invoices_without_catalog_id(self, tmp_model_path):
        from unittest.mock import MagicMock
        from src.models.invoice import InvoiceRecord

        inv = MagicMock(spec=InvoiceRecord)
        inv.cost_catalog_id = None

        repo = MagicMock()
        repo.get_by_status.return_value = [inv]

        clf = MLClassifier(model_path=tmp_model_path)
        clf.retrain_from_repo(repo)
        assert clf.is_trained() is False

    def test_retrain_trains_when_enough_labelled_data(self, tmp_model_path):
        from unittest.mock import MagicMock
        from src.models.invoice import InvoiceRecord, ConfidenceField

        def make_inv(catalog_id: str, issuer: str, desc: str):
            inv = MagicMock(spec=InvoiceRecord)
            inv.cost_catalog_id = catalog_id
            inv.issuer_name = ConfidenceField(value=issuer, confidence=0.9)
            inv.recipient_name = ConfidenceField(value="BIAT IT", confidence=0.9)
            inv.invoice_number = ConfidenceField(value="FAC-001", confidence=0.9)
            inv.line_items = [MagicMock(description=desc)]
            inv.raw_extracted_json = {}
            inv.raw_extracted_text = ""
            return inv

        invoices = [
            make_inv("maintenance_informatique", "TechCorp", "maintenance serveurs"),
            make_inv("maintenance_informatique", "SupportSA", "support technique TMA"),
            make_inv("maintenance_informatique", "ITServices", "infogérance TMA mensuel"),
            make_inv("loyer_bureau", "ImmobilierTN", "loyer mensuel bureau"),
            make_inv("loyer_bureau", "GestionBail", "loyer local commercial"),
        ]

        repo = MagicMock()
        # retrain_from_repo iterates over VALIDATED + EXPORTED + PAID statuses
        repo.get_by_status.side_effect = lambda status: invoices if status.value == "VALIDATED" else []

        clf = MLClassifier(model_path=tmp_model_path)
        clf.retrain_from_repo(repo)
        assert clf.is_trained() is True
