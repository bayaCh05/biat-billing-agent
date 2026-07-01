# Diagram 14 — Workflow : Statuts d'une Facture (avec indicateurs de risque)
# Paste into Eraser → New Diagram → Flowchart

```mermaid
flowchart TD

  RECEIVED["📥 RECEIVED"]
  EXTRACTING["⚙️ EXTRACTING"]
  EXTRACTED["📄 EXTRACTED"]
  CLASSIFYING["🔍 CLASSIFYING"]
  CLASSIFIED["🗂️ CLASSIFIED"]
  VALIDATING["✅ VALIDATING"]
  VALIDATED["✔️ VALIDATED"]
  FLAGGED["🚩 FLAGGED\nRévision humaine requise"]
  JOURNALING["📒 JOURNALING"]
  JOURNALED["📗 JOURNALED"]
  EXPORTED["📤 EXPORTED"]
  PAID["💳 PAID"]
  REJECTED["❌ REJECTED"]
  ERROR["💥 ERROR"]
  EXTRACTION_FAILED["💥 EXTRACTION_FAILED"]

  RISK_EXTRACT["⚠️ Risque extraction\nPDF illisible / champs manquants\nFallback : OCR Tesseract\nSi échec total → EXTRACTION_FAILED"]
  RISK_CLASS["⚠️ Risque classification\nCompte PCE potentiellement erroné\nSi confiance < 85% → FLAGGED"]
  RISK_VALID["⚠️ Risques validation\n• HT + TVA ≠ TTC\n• Doublon détecté\n• Montant suspect\nAnomalyAgent → FLAGGED"]
  RISK_JOURNAL["⚠️ Risque écriture\nDébit ≠ Crédit\nBloquage auto avant sauvegarde"]
  RISK_PAYMENT["⚠️ Risque paiement\nRetard → +10% par tranche 30j\nSuivi nightly automatique"]

  RECEIVED --> EXTRACTING
  EXTRACTING --- RISK_EXTRACT
  RISK_EXTRACT -->|"PDF ok"| EXTRACTED
  RISK_EXTRACT -->|"Échec total"| EXTRACTION_FAILED
  EXTRACTING -->|"Erreur système"| ERROR

  EXTRACTED --> CLASSIFYING
  CLASSIFYING --> CLASSIFIED
  CLASSIFIED --- RISK_CLASS
  RISK_CLASS -->|"Confiance ≥ 85%"| VALIDATING
  RISK_CLASS -->|"Confiance < 85%"| FLAGGED

  VALIDATING --- RISK_VALID
  RISK_VALID -->|"Aucun flag ERROR"| VALIDATED
  RISK_VALID -->|"Flag ERROR"| FLAGGED

  VALIDATED --> JOURNALING
  JOURNALING --- RISK_JOURNAL
  RISK_JOURNAL -->|"Équilibré"| JOURNALED
  RISK_JOURNAL -->|"Déséquilibre"| ERROR

  FLAGGED -->|"Comptable : Corriger"| VALIDATED
  FLAGGED -->|"Comptable : Rejeter"| REJECTED

  JOURNALED --> EXPORTED
  EXPORTED --> PAID
  EXPORTED --- RISK_PAYMENT

  style RECEIVED fill:#1A3A5C,color:#FFFFFF
  style JOURNALED fill:#1D9E76,color:#FFFFFF
  style PAID fill:#1D9E76,color:#FFFFFF
  style FLAGGED fill:#F0A500,color:#FFFFFF
  style ERROR fill:#E74C3C,color:#FFFFFF
  style EXTRACTION_FAILED fill:#E74C3C,color:#FFFFFF
  style REJECTED fill:#E74C3C,color:#FFFFFF
  style RISK_EXTRACT fill:#FFF8E8,color:#7D4E00,stroke:#F0A500,stroke-width:2px
  style RISK_CLASS fill:#FFF8E8,color:#7D4E00,stroke:#F0A500,stroke-width:2px
  style RISK_VALID fill:#FFF8E8,color:#7D4E00,stroke:#F0A500,stroke-width:2px
  style RISK_JOURNAL fill:#FEE2E2,color:#7F1D1D,stroke:#E74C3C,stroke-width:2px
  style RISK_PAYMENT fill:#FFF8E8,color:#7D4E00,stroke:#F0A500,stroke-width:2px
```

## Transitions et risques

| Transition | Déclencheur | Risque | Mitigation |
|-----------|-------------|--------|------------|
| RECEIVED → EXTRACTING | Pipeline IA automatique | PDF illisible | Fallback OCR Tesseract |
| EXTRACTING → EXTRACTION_FAILED | OCR + LLM échouent | Critique — blocage | Rejet avec notification |
| CLASSIFIED → FLAGGED | Confiance < 85% | Compte PCE erroné | Révision humaine obligatoire |
| VALIDATING → FLAGGED | AnomalyAgent flag ERROR | Math / Doublon / Anomalie | File de révision comptable |
| JOURNALING → ERROR | Débit ≠ Crédit | Non-conformité PCE | Bloquage automatique avant DB |
| EXPORTED → PAID | Comptable marque payé | Retard de paiement | Pénalité +10%/30j, alertes nightly |
