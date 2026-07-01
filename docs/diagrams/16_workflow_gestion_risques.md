# Diagram 16 — Workflow : Gestion des Risques (avec risques de retard)
# Paste into Eraser → New Diagram → Flowchart

```mermaid
flowchart TB

  subgraph MANUAL["Voie A — Création manuelle (Chef de Projet)"]
    M1["Chef de Projet saisit :\n• titre\n• type_risque\n• probabilité / impact"]
    M2["Clique 'Suggérer plan'\n→ IA (Ollama local) génère\n   3 actions de mitigation"]
    M3["Enregistre le risque\n→ statut : IDENTIFIE\n   source : MANUAL"]
    M1 --> M2 --> M3
  end

  subgraph AUTO["Voie B — Détection IA nightly (RiskAgent)"]
    A1["APScheduler — chaque nuit\nou bouton 🤖 dans l'UI"]
    A2["Condition :\ndate_fin < aujourd'hui\nET statut ∉ TERMINE, ANNULE"]
    A3["Calcul du retard :\ndays_overdue = today − date_fin"]
    A4["Probabilité calculée :\n1–7j → FAIBLE\n8–30j → MOYENNE\n> 30j → ELEVEE"]
    A5["Impact calculé depuis la priorité :\nBASSE → MOYEN\nMOYENNE → ELEVE\nHAUTE → CRITIQUE"]
    A6["niveau_criticite = f(prob, impact)\nRisk créé avec source : AI_SUGGESTED\nstatut : IDENTIFIE"]
    A7{"Risque IA\ndéjà existant ?"}
    A8["→ IGNORÉ (anti-doublon)"]
    A9["Badge 🤖 Suggéré par IA\nDans la page Risques"]
    A10{"Chef de Projet décide"}
    A11["Confirmer → statut : IDENTIFIE\n(reste visible et traçable)"]
    A12["Ignorer → statut : CLOTURE\n(archivé)"]

    A1 --> A2 --> A7
    A7 -->|"Oui"| A8
    A7 -->|"Non"| A3 --> A4 --> A5 --> A6 --> A9 --> A10
    A10 --> A11
    A10 --> A12
  end

  subgraph LIFECYCLE["Cycle de vie d'un risque"]
    S1["IDENTIFIE"]
    S2["EN_SURVEILLANCE"]
    S3["EN_TRAITEMENT"]
    S4["MAITRISE"]
    S5["SURVENU"]
    S6["CLOTURE"]

    S1 --> S2 --> S3
    S3 --> S4
    S3 --> S5
    S4 --> S6
    S5 --> S6
  end

  subgraph MATRIX["Matrice Probabilité × Impact"]
    direction LR
    MH["ELEVEE × CRITIQUE\n= CRITIQUE 🔴"]
    MM["MOYENNE × ELEVE\n= ELEVEE 🟠"]
    ML["FAIBLE × MOYEN\n= MOYENNE 🟡"]
    LL["FAIBLE × FAIBLE\n= FAIBLE 🔵"]
  end

  M3 --> S1
  A11 --> S1

  style M1 fill:#EFF4FA,color:#1A3A5C
  style M2 fill:#F0A500,color:#FFFFFF
  style M3 fill:#1D9E76,color:#FFFFFF
  style A1 fill:#1A3A5C,color:#FFFFFF
  style A6 fill:#F0A500,color:#FFFFFF
  style A9 fill:#FFF8E8,color:#B07800
  style A11 fill:#1D9E76,color:#FFFFFF
  style A12 fill:#95A5A6,color:#FFFFFF
  style A8 fill:#95A5A6,color:#FFFFFF
  style S1 fill:#2E86C1,color:#FFFFFF
  style S2 fill:#F0A500,color:#FFFFFF
  style S3 fill:#E67E22,color:#FFFFFF
  style S4 fill:#1D9E76,color:#FFFFFF
  style S5 fill:#E74C3C,color:#FFFFFF
  style S6 fill:#95A5A6,color:#FFFFFF
  style MH fill:#E74C3C,color:#FFFFFF
  style MM fill:#E67E22,color:#FFFFFF
  style ML fill:#F0A500,color:#1A3A5C
  style LL fill:#2E86C1,color:#FFFFFF
```

## Logique de calcul automatique (voie B — RiskAgent)

| Jours de retard | Probabilité assignée | Impact (HAUTE) | Criticité résultante |
|----------------|---------------------|----------------|---------------------|
| 1–7 jours | FAIBLE | CRITIQUE | MOYENNE |
| 8–30 jours | MOYENNE | CRITIQUE | ELEVEE |
| > 30 jours | ELEVEE | CRITIQUE | CRITIQUE |
| 1–7 jours | FAIBLE | MOYEN (BASSE) | FAIBLE |
| 8–30 jours | MOYENNE | ELEVE (MOYENNE) | ELEVEE |

> L'impact est déduit de la **priorité du jalon** : BASSE → MOYEN, MOYENNE → ELEVE, HAUTE → CRITIQUE.
> Anti-doublon : si un risque `source=AI_SUGGESTED` et `statut=IDENTIFIE` existe déjà pour ce jalon, l'IA ne crée pas de doublon.
