from __future__ import annotations

import re

from src.classification.matcher import contains_any
from src.models.enums import FlagSeverity, FlagType, InvoiceDirection
from src.models.invoice import InvoiceRecord, ValidationFlag
from src.utils.logging import get_logger

logger = get_logger(__name__)


class Classifier:
    """Determines invoice direction (CLIENT/SUPPLIER) by applying YAML-defined rules.

    Rules are evaluated top-to-bottom; the first matching rule wins.
    Each rule condition may use one of:
      - matches:      regex applied to a single field value
      - contains_any: fuzzy keyword list applied to a single field value
    A rule without a condition is treated as a default (catch-all).
    """

    def __init__(self, rules: list[dict]) -> None:
        self.rules = rules

    def classify(self, invoice: InvoiceRecord) -> InvoiceRecord:
        direction, rule_name = self._apply_rules(invoice)
        invoice.direction = direction

        logger.info(
            "invoice_classified",
            invoice_id=str(invoice.id),
            direction=direction.value,
            matched_rule=rule_name,
        )

        if direction == InvoiceDirection.UNKNOWN:
            invoice.add_flag(ValidationFlag(
                flag_type=FlagType.UNKNOWN_DIRECTION,
                severity=FlagSeverity.WARNING,
                message="Could not determine invoice direction from available fields.",
                field_name="direction",
            ))

        return invoice

    # ── Rule engine ───────────────────────────────────────────────────────────

    def _apply_rules(self, invoice: InvoiceRecord) -> tuple[InvoiceDirection, str]:
        for rule in self.rules:
            condition = rule.get("condition")
            result_str = rule.get("result", "UNKNOWN")
            rule_name = rule.get("name", "unnamed")

            if condition is None:
                return InvoiceDirection(result_str), rule_name

            field_name = condition.get("field", "")
            field_value = self._get_field_value(invoice, field_name)

            if field_value is None:
                continue

            if "matches" in condition:
                pattern = condition["matches"]
                if re.search(pattern, field_value, re.IGNORECASE):
                    return InvoiceDirection(result_str), rule_name

            elif "contains_any" in condition:
                keywords = condition["contains_any"]
                if contains_any(field_value, keywords):
                    return InvoiceDirection(result_str), rule_name

        return InvoiceDirection.UNKNOWN, "no_match"

    @staticmethod
    def _get_field_value(invoice: InvoiceRecord, field_name: str) -> str | None:
        """Extract a string value from a plain or ConfidenceField attribute."""
        attr = getattr(invoice, field_name, None)
        if attr is None:
            return None
        # ConfidenceField has a .value attribute
        value = getattr(attr, "value", attr)
        return str(value) if value is not None else None
