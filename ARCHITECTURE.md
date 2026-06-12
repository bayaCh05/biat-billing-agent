# Architecture — BIAT IT Billing System v3

## Vue d'ensemble

```
┌─────────────┐    ┌──────────────────────────────────────────────┐
│   Human     │    │                   System                     │
│  (Finance)  │    │                                              │
│             │    │  ┌────────────┐   ┌──────────┐   ┌───────┐  │
│  Upload PDF ├───►│  │ Extraction │──►│ Classify │──►│Validate│  │
│             │    │  │ PDF/OCR/LLM│   │ PCE Code │   │ Math  │  │
│  Review ◄───┼────┤  └────────────┘   └──────────┘   └───┬───┘  │
│  (flagged)  │    │                                       │      │
│             │    │  ┌─────────────────────────┐          │      │
│             │    │  │ Export + Journal Entry  │◄─────────┘      │
│             │    │  │ (PCE tunisien double-   │                  │
│             │    │  │  entry: 401/6xxx/4366)  │                  │
│             │    │  └─────────────────────────┘                  │
└─────────────┘    └──────────────────────────────────────────────┘
```

## Principes de conception

### 1. Pipeline = fonctions pures
`src/agent/pipeline.py` n'est **pas** une classe. Ce sont des fonctions libres
qui prennent `PipelineComponents` (dataclass d'injection de dépendances) et un
`InvoiceRecord` Pydantic :

```python
invoice = extract(invoice, components)    # RECEIVED → EXTRACTED
invoice = classify(invoice, components)   # EXTRACTED → CLASSIFIED
invoice = validate(invoice, components)   # CLASSIFIED → VALIDATED | FLAGGED
invoice = export_file(invoice, components)# VALIDATED → EXPORTED
invoice = post_journal(invoice, components)# EXPORTED → JOURNALED
```

Avantages : testabilité, pas d'état partagé, chaque étape est réexécutable.

### 2. Séparation données / règles métier
| Couche | Stockage | Contenu |
|--------|----------|---------|
| Transactions | SQLite (WAL) | Factures, écritures, actifs, projets |
| Règles métier | YAML versionné | Catalogue PCE, templates, settings |
| IA | Ollama local | Extraction LLM — jamais cloud |

### 3. Résidence des données (contrainte bancaire)
Tout traitement IA est local. `OllamaBackend` est le seul backend autorisé
en production. `LLMBackendBase` permet de brancher un mock pour les tests.

---

## Modèle de données

### Factures fournisseurs

```
InvoiceRecord (Pydantic)
  ├── ConfidenceField[str]  issuer_name, invoice_number, ...
  ├── ConfidenceField[float] amount_ht, tva_rate, amount_ttc
  ├── list[LineItem]
  ├── list[ValidationFlag]  (FlagType + FlagSeverity)
  └── InvoiceStatus         (machine d'états)
```

Machine d'états :
```
RECEIVED → EXTRACTING → EXTRACTED → CLASSIFYING → CLASSIFIED
         → VALIDATING → VALIDATED → EXPORTING → EXPORTED
         → JOURNALING → JOURNALED → PAID/COLLECTED
                     ↘ FLAGGED → (révision humaine) → retour pipeline
```

### Facturation client (BIAT IT → BIAT)

```
CharteProjet          budget_jh + taux_jh (taux unique toutes filières)
  └── Phase[]         planned_jh, consumed_jh, livrables[]

FicheMensuelle        DRAFT → SUBMITTED → BILLED
  ├── phases_cloturees[]   → Type A : JH × taux_jh (compte 7061)
  └── avances[]            → Type B : montant forfaitaire (compte 4191)

ClientInvoice         FAC-IT-YYYY-NNNN, TVA 0% (B2B intra-groupe)
```

### Allocation OPEX/CAPEX

```
ProjectCostAllocation
  ├── jh_allocated / jh_total  → allocation_ratio
  ├── opex_allocated = opex_total × ratio
  ├── capex_amort_monthly = Σ(dotation_mensuelle × allocation_pct)
  └── total_cost = opex_allocated + capex_allocated
```

---

## Couche de persistance

### Tables SQLite (16 tables)
```
invoices              — factures fournisseurs + champs extraits
line_items            — lignes de facture
validation_flags      — erreurs et avertissements
status_history        — audit trail de chaque transition d'état
payments              — règlements

journal_entries       — écritures comptables
journal_lines         — lignes débit/crédit (équilibre vérifié)

client_invoices       — factures émises BIAT IT → BIAT
client_line_items     — lignes (phases + avances)

assets                — immobilisations CAPEX
asset_project_links   — % d'actif alloué par projet

chartes_projet        — autorisations de facturation
phases                — phases avec livrables (JSON)
fiches_mensuelles     — fiches mensuelles (DRAFT/SUBMITTED/BILLED)
fiche_phases          — M2M fiche ↔ phases
avances_programmees   — avances sur projets futurs
```

### Migrations Alembic
```
(base)
  └── 0b6a99bbc611  initial schema (16 tables, 22 index)
        └── 9e32aa144819  BILLED status + sanitisation
              └── ece2bf29445f  invoice_number sur FicheMensuelle
```

---

## Composants clés

### HybridExtractor
```
PDF natif (pdfplumber) ──┐
                          ├──► LLM (Ollama qwen2.5:3b) ──► InvoiceRecord
Image/scan (Tesseract) ──┘
```
Seuil `min_native_pdf_chars = 50` : en-dessous → route OCR.

### AccountingCoder (Level A + Level B)
- **Level A** : correspondance floue catalogue (CostCatalog, seuil 70/100)
- **Level B** : ML local (TF-IDF + LogisticRegression, entraîné sur factures validées)
- Résultat : `cost_catalog_id` + `accounting_compte` (6xxx/2xxx)

### EntryGenerator (PCE tunisien)
```
Facture fournisseur :
  Débit  401 (Fournisseurs)          TTC
  Crédit 6xxx/2xxx (Charges/Immobil) HT
  Crédit 4366 (TVA déductible)       TVA

Facture client :
  Débit  411 (Clients)               TTC
  Crédit 7xxx (Produits)             HT
  Crédit 4367 (TVA collectée)        TVA

Amortissement :
  Débit  6811 (Dotations amortissements)
  Crédit 28xx (Amortissements cumulés)
```
Invariant vérifié : `|Σ débits − Σ crédits| < 0.005 TND`

---

## Tests

| Fichier | Nb tests | Couverture |
|---------|----------|------------|
| test_storage.py | 45 | InvoiceRepository CRUD |
| test_validation.py | 48 | FieldValidator, CoherenceChecker, DuplicateDetector |
| test_pipeline.py | 38 | Stages, machine d'états, AutoCorrector |
| test_project_repository.py | 29 | CharteProjet, Phase, FicheMensuelle |
| test_monthly_invoice_builder.py | 18 | Lignes phases/avances, TVA 0%, ValueError |
| test_cost_allocator.py | 15 | Ratio JH, CAPEX, edge cases |
| test_project_billing_e2e.py | 4 | Flow complet bout-en-bout |
| … (9 autres fichiers) | ~329 | Budget, CAPEX, ML, extraction, … |
| **Total** | **526** | |

---

## Évolutions prévues

| Priorité | Item |
|----------|------|
| P1 | Migration vers PostgreSQL (même code, changer `DATABASE_URL`) |
| P1 | Améliorer l'extraction LLM (prompt engineering ou `qwen2.5:7b`) |
| P2 | API REST pour intégration SI BIAT |
| P2 | Authentification LDAP/AD (remplacer mot de passe statique) |
| P3 | Envoi automatique des factures PDF par email |
| P3 | Tableau de bord mobile (Streamlit Mobile ou React) |
