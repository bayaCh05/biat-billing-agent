from enum import Enum


class InvoiceDirection(str, Enum):
    CLIENT = "CLIENT"
    SUPPLIER = "SUPPLIER"
    UNKNOWN = "UNKNOWN"


class InvoiceStatus(str, Enum):
    RECEIVED = "RECEIVED"
    EXTRACTING = "EXTRACTING"
    EXTRACTED = "EXTRACTED"
    CLASSIFYING = "CLASSIFYING"
    CLASSIFIED = "CLASSIFIED"
    VALIDATING = "VALIDATING"
    VALIDATED = "VALIDATED"
    FLAGGED = "FLAGGED"
    ESCALATED = "ESCALATED"
    EXPORTING = "EXPORTING"
    EXPORTED = "EXPORTED"
    JOURNALING = "JOURNALING"
    JOURNALED = "JOURNALED"
    PAID = "PAID"
    COLLECTED = "COLLECTED"
    REJECTED = "REJECTED"
    EXTRACTION_FAILED = "EXTRACTION_FAILED"
    ERROR = "ERROR"


class FlagType(str, Enum):
    # Math / coherence
    TOTAL_MISMATCH = "TOTAL_MISMATCH"
    TVA_MISMATCH = "TVA_MISMATCH"
    LINEITEMS_SUM_MISMATCH = "LINEITEMS_SUM_MISMATCH"
    FUTURE_DATED = "FUTURE_DATED"
    DUE_BEFORE_ISSUE = "DUE_BEFORE_ISSUE"
    INVALID_TVA_RATE = "INVALID_TVA_RATE"

    # Fields
    MISSING_FIELD = "MISSING_FIELD"
    INVALID_TAX_ID = "INVALID_TAX_ID"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"

    # Duplicates & anomalies
    DUPLICATE = "DUPLICATE"
    SUSPECTED_DUPLICATE = "SUSPECTED_DUPLICATE"
    NEAR_DUPLICATE = "NEAR_DUPLICATE"
    SUSPICIOUS_AMOUNT = "SUSPICIOUS_AMOUNT"
    HIGH_VALUE = "HIGH_VALUE"

    # Classification
    UNKNOWN_DIRECTION = "UNKNOWN_DIRECTION"
    CATALOG_NO_MATCH = "CATALOG_NO_MATCH"    # classified direction OK but no catalog entry found

    # Accounting
    JOURNAL_FAILED = "JOURNAL_FAILED"
    AMOUNT_IMPLAUSIBLE = "AMOUNT_IMPLAUSIBLE"

    # Review workflow
    ESCALATED = "ESCALATED"


class FlagSeverity(str, Enum):
    ERROR = "ERROR"       # blocks auto-approval
    WARNING = "WARNING"   # advisory, does not block


class ExtractionMethod(str, Enum):
    NATIVE_PDF_LLM = "native_pdf_llm"
    OCR_LLM = "ocr_llm"
    RULES = "rules"


class ChargeNature(str, Enum):
    FIXE = "fixe"
    VARIABLE = "variable"
    SEMI_VARIABLE = "semi_variable"


class ChargeType(str, Enum):
    OPEX = "OPEX"
    CAPEX = "CAPEX"


class ChargeFlux(str, Enum):
    FOURNISSEUR = "fournisseur"   # dépense — argent sort
    CLIENT = "client"             # recette — argent entre
    INTERNE = "interne"           # opération interne (salaires, amortissements)


class Recurrence(str, Enum):
    MENSUELLE = "mensuelle"
    ANNUELLE = "annuelle"
    PONCTUELLE = "ponctuelle"
    IRREGULIERE = "irreguliere"
