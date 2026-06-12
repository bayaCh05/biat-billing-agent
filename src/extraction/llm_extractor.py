from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from datetime import date

from src.models.invoice import ConfidenceField, InvoiceRecord, LineItem

# Fields that get a ConfidenceField with value + confidence score
EXTRACTABLE_FIELDS = [
    "issuer_name", "issuer_tax_id",
    "recipient_name", "recipient_tax_id",
    "invoice_number", "invoice_date", "due_date",
    "amount_ht", "tva_rate", "tva_amount", "amount_ttc",
]
DATE_FIELDS = {"invoice_date", "due_date"}
NUMERIC_FIELDS = {"amount_ht", "tva_rate", "tva_amount", "amount_ttc"}

_SYSTEM_PROMPT = """\
You are an expert accounting document processor specialising in Tunisian business \
invoices (factures). Invoices may be written in French, Arabic, or both.

Your task: extract structured fields from the invoice text. \
Return ONLY a valid JSON object matching the schema below. \
No markdown, no code fences, no explanations — pure JSON only.

For every field return:
  "value"      — the extracted value (null if absent or unreadable)
  "confidence" — your certainty from 0.0 (not found) to 1.0 (certain)
  "source"     — the exact substring from the invoice text you relied on (null if none)

Tunisian invoice specifics:
- Matricule Fiscal (MF) format: 1234567/A/M/000 or similar alphanumeric pattern
- Accepted TVA rates: 0 %, 7 %, 13 %, 19 %
- Default currency is TND unless the invoice explicitly states otherwise
- Dates appear as DD/MM/YYYY, DD-MM-YYYY, or French/Arabic month names → convert to YYYY-MM-DD
- "Montant HT" = amount before tax | "TVA" or "Taxe" = tax amount | "Montant TTC" = total with tax
- Arabic labels for amounts: مبلغ خارج الأداء (HT) | الأداء على القيمة المضافة (TVA) | المجموع (TTC)
- DECIMAL SEPARATOR: Tunisian invoices use period (.) as decimal separator and NO thousands
  separator. Never interpret a period as a thousands separator.
  Example: 973.420 means nine hundred seventy-three point four two zero TND,
  NOT nine hundred seventy-three thousand. Return 973.42, not 973420.0.
"""

_FIELD_DESCRIPTIONS = """\
Field descriptions:
  issuer_name     — full legal name of the company that issued this invoice
  issuer_tax_id   — Tunisian MF of the issuer
  recipient_name  — full legal name of the invoice recipient
  recipient_tax_id— Tunisian MF of the recipient
  invoice_number  — invoice reference / number. Common French labels: "Numéro", "Numero",
                    "N°", "No", "Réf", "Ref", "Facture N°", "FAC-", "INV-"
  invoice_date    — date of issue → YYYY-MM-DD
  due_date        — payment due date → YYYY-MM-DD (null if not stated)
  amount_ht       — total amount before tax (numeric, in invoice currency)
  tva_rate        — VAT rate as a PERCENTAGE INTEGER/FLOAT, not a decimal fraction.
                    ALWAYS return 19.0 not 0.19, return 7.0 not 0.07.
                    Tunisian rates are: 0, 7, 13, or 19.
  tva_amount      — total VAT amount (numeric)
  amount_ttc      — total amount including tax (numeric)
  currency        — ISO currency code (TND by default)
  line_items      — array of individual line items from the invoice table.
                    Look for a table with columns such as:
                      Désignation / Description / Libellé (→ description)
                      Qté / Quantité / Nombre       (→ quantity, float)
                      Prix Unitaire / PU / P.U.     (→ unit_price, float, BEFORE tax)
                      Montant HT / Total HT          (→ line_total, float, BEFORE tax)
                      Taux TVA / TVA%                (→ tva_rate, PERCENTAGE like 19.0)
                    Rules:
                      - line_total = quantity × unit_price (pre-tax, do NOT add TVA)
                      - tva_rate is a PERCENTAGE (19.0, not 0.19)
                      - If a column is absent, return null for that field
                      - Do NOT invent values — only extract what is written
                    Arabic labels: الوصف (description) | الكمية (qty) | سعر الوحدة (unit_price)
                                   المجموع قبل الضريبة (line_total) | نسبة الضريبة (tva_rate)
"""

_JSON_SCHEMA = """\
{
  "issuer_name":      {"value": string|null, "confidence": float, "source": string|null},
  "issuer_tax_id":    {"value": string|null, "confidence": float, "source": string|null},
  "recipient_name":   {"value": string|null, "confidence": float, "source": string|null},
  "recipient_tax_id": {"value": string|null, "confidence": float, "source": string|null},
  "invoice_number":   {"value": string|null, "confidence": float, "source": string|null},
  "invoice_date":     {"value": "YYYY-MM-DD"|null, "confidence": float, "source": string|null},
  "due_date":         {"value": "YYYY-MM-DD"|null, "confidence": float, "source": string|null},
  "amount_ht":        {"value": float|null,  "confidence": float, "source": string|null},
  "tva_rate":         {"value": float|null,  "confidence": float, "source": string|null},
  "tva_amount":       {"value": float|null,  "confidence": float, "source": string|null},
  "amount_ttc":       {"value": float|null,  "confidence": float, "source": string|null},
  "currency":         {"value": string,      "confidence": float, "source": string|null},
  "line_items": [
    {"description": string|null, "quantity": float|null, "unit_price": float|null,
     "line_total": float|null, "tva_rate": float|null}
  ]
}
"""


class ExtractionError(RuntimeError):
    pass


def normalise_tnd_amount(raw) -> float | None:
    """Normalise an LLM-returned monetary value to a plain float.

    Handles the two common Ollama misformats for Tunisian invoices:
      "973,420.000"  — comma as thousands separator → 973.42
      "1,234,567.89" — US format                    → 1234567.89
      "973.420"      — period as decimal, 3 dp       → 973.42  (already correct)
      "1 234.56"     — space as thousands separator  → 1234.56
    """
    if raw is None:
        return None
    s = str(raw).strip()
    s = re.sub(r"[^\d,.\s]", "", s).strip()
    if not s:
        return None
    # Remove space-as-thousands (e.g. "1 234.56")
    s = re.sub(r"(\d)\s+(\d)", r"\1\2", s)
    # Both comma and period present → comma is thousands, period is decimal
    if "," in s and "." in s:
        s = s.replace(",", "")
        return float(s)
    # Only comma → French decimal separator
    if "," in s:
        return float(s.replace(",", "."))
    return float(s)


# ── LLM Backends ──────────────────────────────────────────────────────────────

class LLMBackendBase(ABC):
    @abstractmethod
    def complete(self, system: str, user: str) -> str:
        """Send a system+user prompt. Returns the raw text response."""


class OllamaBackend(LLMBackendBase):
    def __init__(self, model: str, base_url: str) -> None:
        self.model = model
        self.base_url = base_url

    def complete(self, system: str, user: str) -> str:
        import ollama
        client = ollama.Client(host=self.base_url)
        response = client.chat(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.message.content


# Fields extracted in amounts_only mode
_AMOUNTS_FIELDS = ["amount_ht", "tva_rate", "tva_amount", "amount_ttc"]

_AMOUNTS_ONLY_SYSTEM = (
    "You are an expert at reading Tunisian business invoices (factures)."
)

_AMOUNTS_ONLY_USER = """\
Extract ONLY the monetary totals from this Tunisian invoice.
Return JSON with exactly these fields:
{{
  "amount_ht":   {{"value": float|null, "confidence": float}},
  "tva_rate":    {{"value": float|null, "confidence": float}},
  "tva_amount":  {{"value": float|null, "confidence": float}},
  "amount_ttc":  {{"value": float|null, "confidence": float}}
}}

Rules:
- Period (.) is the decimal separator. No thousands separator.
- 973.420 means nine hundred seventy-three point four two zero TND, NOT nine hundred seventy-three thousand. Return 973.42, not 973420.0.
- Return confidence 1.0 when the value is clearly printed; 0.5 if you are guessing.
- Return null for any field not found in the invoice.
- Accepted TVA rates: 0, 7, 13, 19 (return as percentage, e.g. 19.0 not 0.19)

Invoice text:
---
{text}
---"""


# ── LLM Extractor ─────────────────────────────────────────────────────────────

class LLMExtractor:
    """Sends invoice text to an LLM, parses its JSON reply into InvoiceRecord fields.

    mode="amounts_only"  — default; asks the LLM for only the 4 monetary totals.
                           Reduces response to ~200 tokens, eliminating truncation
                           with small models like qwen2.5:3b.
    mode="full_schema"   — legacy full extraction; LLM populates all fields.
                           Use in tests that need text-field extraction from a mock.
    """

    def __init__(self, backend: LLMBackendBase, languages: list[str],
                 mode: str = "amounts_only") -> None:
        self.backend = backend
        self.languages = languages
        self.mode = mode

    def extract(self, text: str, invoice: InvoiceRecord) -> InvoiceRecord:
        if self.mode == "amounts_only":
            system = _AMOUNTS_ONLY_SYSTEM
            user = _AMOUNTS_ONLY_USER.format(text=text)
            raw_response = self.backend.complete(system, user)
            invoice = self._parse_response(raw_response, invoice, fields=_AMOUNTS_FIELDS)
        else:
            system, user = self._build_prompt(text)
            raw_response = self.backend.complete(system, user)
            invoice = self._parse_response(raw_response, invoice)
            invoice = self._validate_sources(invoice, text)
        invoice = self._cross_validate_amounts(invoice)
        return invoice

    # ── Prompt ────────────────────────────────────────────────────────────────

    def _build_prompt(self, text: str) -> tuple[str, str]:
        lang_hint = (
            "The invoice is written in French and/or Arabic."
            if "ar" in self.languages
            else "The invoice is written in French."
        )
        user = (
            f"{lang_hint}\n\n"
            f"Invoice text:\n---\n{text}\n---\n\n"
            f"Return JSON matching this schema exactly:\n{_JSON_SCHEMA}\n\n"
            f"{_FIELD_DESCRIPTIONS}"
        )
        return _SYSTEM_PROMPT, user

    # ── Parsing ───────────────────────────────────────────────────────────────

    def _parse_response(self, response_text: str, invoice: InvoiceRecord,
                        fields: list[str] | None = None) -> InvoiceRecord:
        json_str = self._extract_json(response_text)
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as exc:
            raise ExtractionError(f"LLM returned unparseable JSON: {exc}\n\nRaw: {response_text[:500]}")

        active_fields = fields if fields is not None else EXTRACTABLE_FIELDS
        for field_name in active_fields:
            if field_name not in data or not isinstance(data[field_name], dict):
                continue
            field_data = data[field_name]
            value = field_data.get("value")
            confidence = float(field_data.get("confidence") or 0.0)
            source = field_data.get("source") or None

            if field_name in DATE_FIELDS:
                value, confidence = self._coerce_date(value, confidence)
            elif field_name in NUMERIC_FIELDS:
                value, confidence = self._coerce_numeric(value, confidence)
                if field_name == "tva_rate" and value is not None and 0 < value < 1:
                    value = round(value * 100, 4)  # 0.19 → 19.0

            # Confidence merge: only overwrite a rules-based value if the LLM
            # is more confident AND actually extracted something.
            existing: ConfidenceField | None = getattr(invoice, field_name, None)
            if (
                value is None
                or (
                    existing is not None
                    and isinstance(existing, ConfidenceField)
                    and existing.value is not None
                    and confidence <= existing.confidence
                )
            ):
                continue  # keep the higher-confidence (rules) value

            setattr(invoice, field_name, ConfidenceField(
                value=value, confidence=confidence, source=source,
            ))

        # Currency is a plain str field, not a ConfidenceField
        if "currency" in data and isinstance(data["currency"], dict):
            cur_value = data["currency"].get("value")
            invoice.currency = cur_value if cur_value else "TND"

        # Line items
        if "line_items" in data and isinstance(data["line_items"], list):
            invoice.line_items = [
                LineItem(
                    line_number=i + 1,
                    description=li.get("description"),
                    quantity=self._to_float(li.get("quantity")),
                    unit_price=self._to_float(li.get("unit_price")),
                    line_total=self._to_float(li.get("line_total")),
                    tva_rate=self._coerce_line_tva_rate(li.get("tva_rate")),
                )
                for i, li in enumerate(data["line_items"])
                if isinstance(li, dict)
            ]

        invoice.raw_extracted_json = data
        return invoice

    def _validate_sources(self, invoice: InvoiceRecord, original_text: str) -> InvoiceRecord:
        """Zero out confidence on any field whose source snippet isn't in the text."""
        for field_name in EXTRACTABLE_FIELDS:
            cf: ConfidenceField = getattr(invoice, field_name)
            if cf.source and cf.source not in original_text:
                setattr(invoice, field_name, ConfidenceField(
                    value=cf.value, confidence=0.0, source=cf.source,
                ))
        return invoice

    def _cross_validate_amounts(self, invoice: InvoiceRecord) -> InvoiceRecord:
        """Penalise confidence on all three amount fields if HT + TVA ≠ TTC."""
        ht = invoice.amount_ht.value
        tva = invoice.tva_amount.value
        ttc = invoice.amount_ttc.value
        if ht is not None and tva is not None and ttc is not None:
            tolerance = max(0.02, ttc * 0.001)
            if abs(ht + tva - ttc) > tolerance:
                for fn in ("amount_ht", "tva_amount", "amount_ttc"):
                    cf = getattr(invoice, fn)
                    setattr(invoice, fn, ConfidenceField(
                        value=cf.value,
                        confidence=round(cf.confidence * 0.5, 4),
                        source=cf.source,
                    ))
        return invoice

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_json(text: str) -> str:
        """Strip markdown fences and return the innermost JSON object."""
        text = text.strip()
        # Strip ```json ... ``` or ``` ... ```
        fenced = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if fenced:
            return fenced.group(1)
        # Fall back to first { ... last }
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            return text[start:end]
        return text

    @staticmethod
    def _coerce_date(value, confidence: float) -> tuple:
        from src.utils.date_parser import parse_date
        if value is None:
            return None, 0.0
        parsed = parse_date(str(value))
        if parsed is None:
            return None, 0.0
        return parsed, confidence

    @staticmethod
    def _coerce_numeric(value, confidence: float) -> tuple:
        if value is None:
            return None, 0.0
        try:
            return normalise_tnd_amount(value), confidence
        except (TypeError, ValueError):
            return None, 0.0

    @staticmethod
    def _to_float(value) -> float | None:
        if value is None:
            return None
        try:
            return normalise_tnd_amount(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _coerce_line_tva_rate(value) -> float | None:
        if value is None:
            return None
        try:
            rate = float(value)
            if 0 < rate < 1:
                rate = round(rate * 100, 4)  # 0.19 → 19.0
            return rate
        except (TypeError, ValueError):
            return None
