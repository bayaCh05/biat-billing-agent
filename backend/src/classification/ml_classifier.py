"""Classificateur ML de secours (Level B) pour le codage comptable.

Utilisé quand le catalogue de règles (Level A) ne trouve pas de correspondance
au-dessus du seuil de confiance.

Pipeline : TF-IDF unigrammes+bigrammes → Régression Logistique.
Avantages : entièrement local, déterministe, réentraînable à partir des
corrections humaines, interprétable (coefficients logistiques).

Cycle d'apprentissage :
  1. Au démarrage, charger le modèle sérialisé si présent.
  2. Lors d'une correction humaine, appeler retrain_from_repo(repository).
  3. Le modèle est sauvegardé dans data/ml_model.joblib après chaque reentraînement.

Exigences : scikit-learn (inclus dans pyproject.toml).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from src.classification.matcher import normalise
from src.models.enums import InvoiceStatus
from src.utils.logging import get_logger

logger = get_logger(__name__)

_MIN_CLASSES = 2          # besoin d'au moins 2 labels distincts pour entraîner
_MIN_EXAMPLES = 5         # besoin d'au moins 5 exemples au total


class MLClassifier:
    """Classificateur TF-IDF + Logistic Regression pour la classification comptable.

    Prédit un cost_catalog_id à partir du texte d'une facture.
    Retourne (None, 0.0) si le modèle n'est pas encore entraîné.
    """

    def __init__(self, model_path: str | Path = "data/ml_model.joblib") -> None:
        self._path = Path(model_path)
        self._pipeline = None   # sklearn Pipeline
        self._classes: list[str] = []
        self._load_if_exists()

    # ── API publique ──────────────────────────────────────────────────────────

    def is_trained(self) -> bool:
        return self._pipeline is not None and len(self._classes) >= _MIN_CLASSES

    def predict(self, text: str) -> tuple[Optional[str], float]:
        """Prédire le cost_catalog_id le plus probable avec sa probabilité.

        Returns:
            (catalog_id, confidence) ou (None, 0.0) si modèle non entraîné.
        """
        if not self.is_trained():
            return None, 0.0
        norm = normalise(text)
        if not norm.strip():
            return None, 0.0
        proba = self._pipeline.predict_proba([norm])[0]
        idx = int(proba.argmax())
        return self._classes[idx], float(proba[idx])

    def fit(self, texts: list[str], labels: list[str]) -> None:
        """Entraîner (ou ré-entraîner) sur un corpus de (texte, label).

        Args:
            texts:  textes bruts des factures (seront normalisés).
            labels: cost_catalog_id correspondant.

        Raises:
            ValueError: if texts and labels have different lengths, or fewer than
                        _MIN_EXAMPLES training examples are provided.
        """
        if len(texts) != len(labels):
            raise ValueError(
                f"texts and labels must have the same length "
                f"(got {len(texts)} texts and {len(labels)} labels)"
            )
        if len(texts) < _MIN_EXAMPLES:
            raise ValueError(
                f"Need at least {_MIN_EXAMPLES} training examples, got {len(texts)}"
            )

        unique_labels = set(labels)
        if len(unique_labels) < _MIN_CLASSES:
            logger.warning(
                "ml_training_skipped",
                reason="need at least 2 distinct labels",
                found=len(unique_labels),
            )
            return

        try:
            from sklearn.linear_model import LogisticRegression
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.pipeline import Pipeline

            norm_texts = [normalise(t) for t in texts]
            pipeline = Pipeline([
                ("tfidf", TfidfVectorizer(
                    analyzer="word",
                    ngram_range=(1, 2),
                    max_features=5000,
                    sublinear_tf=True,
                    min_df=1,
                )),
                ("clf", LogisticRegression(
                    max_iter=1000,
                    C=1.0,
                    class_weight="balanced",
                    solver="lbfgs",
                )),
            ])
            pipeline.fit(norm_texts, labels)
            self._pipeline = pipeline
            self._classes = list(pipeline.classes_)
            self._save()
            logger.info(
                "ml_model_trained",
                n_examples=len(texts),
                n_classes=len(self._classes),
                model_path=str(self._path),
            )
        except ImportError:
            logger.error("ml_training_failed", reason="scikit-learn not installed")

    _TRAIN_STATUSES = frozenset({
        InvoiceStatus.VALIDATED, InvoiceStatus.EXPORTED,
        InvoiceStatus.JOURNALED, InvoiceStatus.PAID,
    })

    def retrain_from_repo(self, repository) -> None:
        """Ré-entraîner à partir des factures labellisées dans la base de données.

        N'utilise que les factures VALIDATED / EXPORTED / PAID avec un
        cost_catalog_id, pour éviter d'entraîner sur des labels FLAGGED
        potentiellement incorrects.
        """
        texts: list[str] = []
        labels: list[str] = []

        for status in self._TRAIN_STATUSES:
            for inv in repository.get_by_status(status):
                if not inv.cost_catalog_id:
                    continue
                corpus = self._invoice_to_corpus(inv)
                if corpus.strip():
                    texts.append(corpus)
                    labels.append(inv.cost_catalog_id)

        if len(texts) >= _MIN_EXAMPLES:
            self.fit(texts, labels)

    # ── Persistence ───────────────────────────────────────────────────────────

    def _save(self) -> None:
        try:
            import joblib
            self._path.parent.mkdir(parents=True, exist_ok=True)
            joblib.dump({"pipeline": self._pipeline, "classes": self._classes}, self._path)
        except Exception as exc:
            logger.warning("ml_model_save_failed", error=str(exc))

    def _load_if_exists(self) -> None:
        if not self._path.exists():
            return
        try:
            import joblib
            data = joblib.load(self._path)
            self._pipeline = data["pipeline"]
            self._classes = data["classes"]
            logger.info("ml_model_loaded", n_classes=len(self._classes), path=str(self._path))
        except Exception as exc:
            logger.warning("ml_model_load_failed", error=str(exc))

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _invoice_to_corpus(invoice) -> str:
        parts: list[str] = []
        for field_name in ("issuer_name", "recipient_name"):
            attr = getattr(invoice, field_name, None)
            val = getattr(attr, "value", None) if attr else None
            if val:
                parts.append(str(val))
        for item in invoice.line_items:
            if item.description:
                parts.append(item.description)
        if invoice.raw_extracted_text:
            parts.append(invoice.raw_extracted_text[:300])
        return " ".join(parts)
