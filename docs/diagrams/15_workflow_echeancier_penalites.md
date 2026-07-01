# Diagram 15 — Workflow : Échéancier et Pénalités de Retard (avec colonne risque)
# Paste into Eraser → New Diagram → Flowchart

```mermaid
flowchart TB

  INV["📥 Facture reçue — Jour 0\nMontant TTC : 14 280 TND\nDélai : 90 jours (3 × 30j)"]

  subgraph GEN["Génération de l'échéancier (IA)"]
    E1["Échéance 1 — Jour 30\n4 760 TND\n🟢 PENDING — À l'heure"]
    E2["Échéance 2 — Jour 60\n4 760 TND\n🟢 PENDING — À l'heure"]
    E3["Échéance 3 — Jour 90\n4 760 TND\n🟢 PENDING — À l'heure"]
  end

  INV --> E1
  INV --> E2
  INV --> E3

  subgraph LATE1["Scénario : Échéance 1 non payée"]
    D31["Jour 31 — Retard détecté\n🔴 LATE\n⚠️ Risque : Pénalité imminente"]
    D31 -->|"+10% après 30j de retard"| P1["Jour 60 : 4 760 × 1,10\n= 5 236 TND\n🔴 Pénalité +10%"]
    P1 -->|"+10% après 60j de retard"| P2["Jour 90 : 4 760 × 1,21\n= 5 760 TND\n🔴 Pénalité +21%"]
  end

  subgraph PAID1["Paiement tardif de l'échéance 1"]
    PAY["Jour 65 : Paiement 5 760 TND\n✅ PAID"]
    JE["Écriture comptable :\nDébit 401 (Fournisseur) 4 760\nDébit 668 (Pénalités) 1 000\nCrédit 532 (Banque) 5 760"]
  end

  E1 -->|"Non payée"| D31
  P1 --> PAY
  PAY --> JE

  subgraph FORMULA["Formule de pénalité"]
    F["montant × (1 + taux)^périodes_retard\nTaux = 10% par période de 30j\n\nEx : 4 760 × (1,10)² = 5 759,6 TND"]
  end

  subgraph RISK_COL["Niveaux de risque par échéance"]
    R1["🟢 PENDING — Risque : Nul"]
    R2["🟡 Échéance dans 7j — Risque : Faible\nPulse jaune dans l'UI"]
    R3["🔴 1–30j de retard — Risque : ELEVEE\n+10% appliqué"]
    R4["🔴🔴 > 30j de retard — Risque : CRITIQUE\n+21% ou plus appliqué"]
  end

  style INV fill:#1A3A5C,color:#FFFFFF
  style D31 fill:#E74C3C,color:#FFFFFF
  style P1 fill:#E67E22,color:#FFFFFF
  style P2 fill:#E74C3C,color:#FFFFFF
  style PAY fill:#1D9E76,color:#FFFFFF
  style JE fill:#2E86C1,color:#FFFFFF
  style F fill:#F5F7FA,color:#1A3A5C,stroke:#2E86C1
  style R1 fill:#E8F5F0,color:#0D6E52
  style R2 fill:#FFF8E8,color:#B07800
  style R3 fill:#FEE8E0,color:#C0391B
  style R4 fill:#FEE2E2,color:#7F1D1D
```

## Tableau récapitulatif des risques par période

| Jour | Échéance | Montant | Statut | Niveau de risque | Action système |
|------|----------|---------|--------|-----------------|----------------|
| J+30 | 1 | 4 760 TND | PENDING | 🟢 Nul | — |
| J+37 | 1 | 4 760 TND | LATE | 🔴 ÉLEVÉ | Alerte comptable |
| J+60 | 1 | 5 236 TND | LATE +10% | 🔴 CRITIQUE | Pénalité appliquée |
| J+90 | 1 | 5 760 TND | LATE +21% | 🔴 CRITIQUE | Pénalité compoundée |
| J+65 | 1 | 5 760 TND | PAID | ✅ Soldée | Écriture 401/668/532 |
| J+60 | 2 | 4 760 TND | PENDING | 🟢 Nul | — |
| J+90 | 3 | 4 760 TND | PENDING | 🟢 Nul | — |

> **Règle** : Chaque période de 30 jours de retard = +10% cumulatif sur l'échéance concernée.
> Recalcul automatique chaque nuit par le scheduler APScheduler.
