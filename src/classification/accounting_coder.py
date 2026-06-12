"""Assignation du coding comptable via le CostCatalog.

Remplace l'ancienne approche basée sur un dictionnaire de règles YAML figé.
La classification utilise maintenant le CostCatalog chargé depuis
config/cost_catalog.yaml, qui porte toute la sémantique financière :
nature, type_charge, compte, TVA, récurrence.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from src.cost_catalog.catalog import CostCatalog, CostCatalogEntry
from src.models.enums import ChargeFlux, FlagSeverity, FlagType, InvoiceDirection
from src.models.invoice import InvoiceRecord, ValidationFlag
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.classification.ml_classifier import MLClassifier

logger = get_logger(__name__)


class AccountingCoder:
    """Assigne un coding comptable à une facture en deux passes.

    Passe A — règles (CostCatalog) : correspondance par mots-clés + fuzzy.
    Passe B — ML (MLClassifier)    : TF-IDF + LR si la passe A échoue.

    Si aucune correspondance n'est trouvée, un flag WARNING est ajouté.
    """

    def __init__(
        self,
        catalog: CostCatalog,
        min_score: int = 70,
        ml_classifier: "MLClassifier | None" = None,
        ml_confidence_threshold: float = 0.60,
    ) -> None:
        self.catalog = catalog
        self.min_score = min_score
        self.ml_classifier = ml_classifier
        self.ml_confidence_threshold = ml_confidence_threshold

    def assign(self, invoice: InvoiceRecord) -> InvoiceRecord:
        flux = self._direction_to_flux(invoice.direction)
        if flux is None:
            return invoice  # UNKNOWN direction — classifier aura déjà flaggé

        corpus = self._build_corpus(invoice)

        # Passe A : règles par mots-clés
        entry: CostCatalogEntry | None = self.catalog.match(
            corpus, flux=flux, min_score=self.min_score
        )

        # Passe B : classificateur ML si la passe A échoue
        if entry is None and self.ml_classifier and self.ml_classifier.is_trained():
            catalog_id, confidence = self.ml_classifier.predict(corpus)
            if catalog_id and confidence >= self.ml_confidence_threshold:
                entry = self.catalog.get(catalog_id)
                if entry:
                    logger.info(
                        "ml_fallback_used",
                        invoice_id=str(invoice.id),
                        catalog_id=catalog_id,
                        confidence=round(confidence, 3),
                    )

        if entry:
            invoice.cost_catalog_id = entry.id
            invoice.accounting_compte = entry.compte
            invoice.accounting_label = entry.label
            invoice.charge_nature = entry.nature
            invoice.charge_type = entry.type_charge
            logger.info(
                "accounting_code_assigned",
                invoice_id=str(invoice.id),
                catalog_id=entry.id,
                compte=entry.compte,
                label=entry.label,
                nature=entry.nature.value,
                type_charge=entry.type_charge.value,
            )
        else:
            invoice.add_flag(ValidationFlag(
                flag_type=FlagType.CATALOG_NO_MATCH,
                severity=FlagSeverity.WARNING,
                field_name="cost_catalog_id",
                message=(
                    "Aucune entrée du catalogue de coûts ne correspond au contenu "
                    "de cette facture. Classification manuelle requise."
                ),
            ))
            logger.warning(
                "accounting_code_not_found",
                invoice_id=str(invoice.id),
                flux=flux.value,
            )

        return invoice

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _direction_to_flux(direction: InvoiceDirection) -> ChargeFlux | None:
        if direction == InvoiceDirection.SUPPLIER:
            return ChargeFlux.FOURNISSEUR
        if direction == InvoiceDirection.CLIENT:
            return ChargeFlux.CLIENT
        return None

    @staticmethod
    def _build_corpus(invoice: InvoiceRecord) -> str:
        """Concatène tout le contenu textuel de la facture pour la recherche."""
        parts: list[str] = []

        for field_name in ("issuer_name", "recipient_name", "invoice_number"):
            attr = getattr(invoice, field_name, None)
            value = getattr(attr, "value", None) if attr else None
            if value:
                parts.append(str(value))

        for item in invoice.line_items:
            if item.description:
                parts.append(item.description)

        raw = invoice.raw_extracted_json or {}
        for key in ("notes", "description", "objet", "designation", "nature"):
            if val := raw.get(key):
                parts.append(str(val))

        if invoice.raw_extracted_text:
            # Limite à 500 caractères pour éviter de noyer les keywords pertinents
            parts.append(invoice.raw_extracted_text[:500])

        return " ".join(parts)
