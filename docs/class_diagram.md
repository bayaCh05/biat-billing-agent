# Diagramme de Classes — BIAT IT Billing Agent

```mermaid
classDiagram

%% ══════════════════════════════════════════════
%%  ÉNUMÉRATIONS
%% ══════════════════════════════════════════════

class InvoiceStatus {
    <<enumeration>>
    RECEIVED
    EXTRACTING
    EXTRACTED
    CLASSIFYING
    CLASSIFIED
    VALIDATING
    VALIDATED
    FLAGGED
    ESCALATED
    EXPORTING
    EXPORTED
    JOURNALED
    PAID
    COLLECTED
    REJECTED
    ERROR
    EXTRACTION_FAILED
}

class InvoiceDirection {
    <<enumeration>>
    SUPPLIER
    CLIENT
    UNKNOWN
}

class ChargeType {
    <<enumeration>>
    OPEX
    CAPEX
}

class FlagSeverity {
    <<enumeration>>
    ERROR
    WARNING
}

class FlagType {
    <<enumeration>>
    TOTAL_MISMATCH
    TVA_MISMATCH
    MISSING_FIELD
    INVALID_TAX_ID
    LOW_CONFIDENCE
    DUPLICATE
    NEAR_DUPLICATE
    HIGH_VALUE
    UNKNOWN_DIRECTION
    CATALOG_NO_MATCH
}

class ClientInvoiceStatus {
    <<enumeration>>
    DRAFT
    SENT
    PAID
    CANCELLED
}

class ExtractionMethod {
    <<enumeration>>
    NATIVE_PDF_LLM
    OCR_LLM
    RULES
}

%% ══════════════════════════════════════════════
%%  MODÈLE FACTURE FOURNISSEUR
%% ══════════════════════════════════════════════

class ConfidenceField~T~ {
    +T value
    +float confidence
    +str source
}

class LineItem {
    +int line_number
    +str description
    +float quantity
    +float unit_price
    +float line_total
    +float tva_rate
}

class ValidationFlag {
    +FlagType flag_type
    +FlagSeverity severity
    +str field_name
    +str message
    +bool resolved
    +datetime resolved_at
    +str resolved_by
}

class InvoiceRecord {
    +UUID id
    +str file_hash
    +str raw_file_path
    +InvoiceDirection direction
    +InvoiceStatus status
    +ExtractionMethod extraction_method
    +ConfidenceField~str~ issuer_name
    +ConfidenceField~str~ issuer_tax_id
    +ConfidenceField~str~ recipient_name
    +ConfidenceField~str~ invoice_number
    +ConfidenceField~date~ invoice_date
    +ConfidenceField~float~ amount_ht
    +ConfidenceField~float~ tva_rate
    +ConfidenceField~float~ tva_amount
    +ConfidenceField~float~ amount_ttc
    +str currency
    +str cost_catalog_id
    +str accounting_compte
    +ChargeType charge_type
    +bool human_review_required
    +datetime received_at
    +datetime paid_at
    +bool has_errors()
    +bool has_warnings()
    +add_flag(flag ValidationFlag)
}

%% ══════════════════════════════════════════════
%%  CATALOGUE COMPTABLE
%% ══════════════════════════════════════════════

class CostCatalogEntry {
    +str id
    +str label
    +str compte
    +float tva_rate
    +ChargeType charge_type
    +list~str~ keywords
}

class CostCatalog {
    +list~CostCatalogEntry~ entries
    +from_yaml(path str)$ CostCatalog
    +match(text str, flux ChargeFlux) CostCatalogEntry
    +get(entry_id str) CostCatalogEntry
    +all_entries() list~CostCatalogEntry~
}

%% ══════════════════════════════════════════════
%%  JOURNAL COMPTABLE
%% ══════════════════════════════════════════════

class JournalLine {
    +str compte
    +str libelle
    +float debit
    +float credit
}

class JournalEntry {
    +UUID id
    +str reference
    +date date_ecriture
    +str description
    +UUID source_invoice_id
    +UUID source_asset_id
    +float total_debit()
    +float total_credit()
    +bool is_balanced()
}

%% ══════════════════════════════════════════════
%%  IMMOBILISATIONS (CAPEX)
%% ══════════════════════════════════════════════

class Asset {
    +UUID id
    +str designation
    +str compte_immobilisation
    +str compte_amortissement
    +date acquisition_date
    +float acquisition_cost_ht
    +int useful_life_years
    +str depreciation_method
    +UUID supplier_invoice_id
    +float annual_depreciation()
    +float monthly_depreciation()
    +float book_value_at(ref_date date)
}

%% ══════════════════════════════════════════════
%%  FACTURATION CLIENT
%% ══════════════════════════════════════════════

class ClientLineItem {
    +str description
    +float quantity
    +float unit_price
    +float line_total
    +float tva_rate
    +float tva_amount
    +str compte_produit
    +str charte_reference
    +str phase_id
}

class ClientInvoice {
    +UUID id
    +str invoice_number
    +date invoice_date
    +date due_date
    +str issuer_name
    +str issuer_tax_id
    +str client_id
    +str client_name
    +str client_tax_id
    +float amount_ht
    +float tva_amount
    +float amount_ttc
    +ClientInvoiceStatus status
    +str source_template_id
    +datetime sent_at
    +datetime paid_at
}

%% ══════════════════════════════════════════════
%%  PROJETS & CHARTES
%% ══════════════════════════════════════════════

class CharteProjet {
    +str id
    +str project_id
    +str project_name
    +str client
    +date valid_from
    +date valid_until
    +float budget_jh
    +float taux_jh
    +bool is_active
}

class Phase {
    +str id
    +str project_id
    +str name
    +str description
    +float planned_jh
    +float consumed_jh
    +str status
    +date closed_date
    +list livrables
}

class AssetProjectLink {
    +str asset_id
    +str project_id
    +float allocation_pct
}

%% ══════════════════════════════════════════════
%%  RELATIONS
%% ══════════════════════════════════════════════

%% InvoiceRecord composition
InvoiceRecord "1" *-- "0..*" LineItem : contient
InvoiceRecord "1" *-- "0..*" ValidationFlag : a
InvoiceRecord "1" *-- "6" ConfidenceField~T~ : champs extraits

%% Enums
InvoiceRecord --> InvoiceStatus : status
InvoiceRecord --> InvoiceDirection : direction
InvoiceRecord --> ChargeType : charge_type
InvoiceRecord --> ExtractionMethod : extraction_method
ValidationFlag --> FlagType : flag_type
ValidationFlag --> FlagSeverity : severity
ClientInvoice --> ClientInvoiceStatus : status

%% Catalogue
CostCatalog "1" o-- "1..*" CostCatalogEntry : regroupe
InvoiceRecord --> CostCatalogEntry : classifiée selon

%% Journal
JournalEntry "1" *-- "2..*" JournalLine : équilibre
JournalEntry --> InvoiceRecord : source_invoice_id
JournalEntry --> Asset : source_asset_id

%% CAPEX
Asset --> InvoiceRecord : supplier_invoice_id
Asset "N" -- "M" CharteProjet : AssetProjectLink

%% Facturation client
ClientInvoice "1" *-- "1..*" ClientLineItem : détail
ClientInvoice --> CharteProjet : référence projet

%% Projets
CharteProjet "1" *-- "1..*" Phase : décomposée en
```

## Légende

| Notation | Signification |
|----------|---------------|
| `*--` | Composition (cycle de vie lié) |
| `o--` | Agrégation (indépendant) |
| `-->` | Association / dépendance |
| `<<enumeration>>` | Énumération |
| `~T~` | Type générique |

## Description des modules

| Module | Classes principales | Rôle |
|--------|---------------------|------|
| **Extraction** | `InvoiceRecord`, `ConfidenceField`, `LineItem` | Stocke les données extraites avec leur score de confiance |
| **Validation** | `ValidationFlag` | Signale les anomalies (math, champs manquants, doublons) |
| **Classification** | `CostCatalogEntry`, `CostCatalog` | Associe chaque facture à un compte PCE et une nature de charge |
| **Comptabilité** | `JournalEntry`, `JournalLine` | Génère les écritures en partie double (PCE Tunisien) |
| **CAPEX** | `Asset`, `AssetProjectLink` | Registre des immobilisations et plan d'amortissement |
| **Facturation** | `ClientInvoice`, `ClientLineItem` | Factures émises aux entités du groupe BIAT |
| **Projets** | `CharteProjet`, `Phase` | Suivi des projets IT par jalons et jours/homme |
