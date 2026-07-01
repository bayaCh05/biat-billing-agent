# Diagram 13 — Sequence: CAPEX Asset Creation
# Paste into Eraser → New Diagram → Sequence Diagram

```
title CAPEX — Création Immobilisation avec Amortissement IA (PCE Tunisien)

Comptable [color: "#1A3A5C", icon: user]
Frontend [color: "#2E86C1", icon: monitor]
FastAPI [color: "#2E86C1", icon: server]
AccountingAgent [color: "#F0A500", icon: book-open]
Ollama [color: "#F0A500", icon: cpu]
Database [color: "#1A3A5C", icon: database]

note over Comptable: "La facture a déjà été classifiée\ncharge_type = CAPEX\ncompte = 2184 Matériel informatique"

FastAPI -> AccountingAgent: "run({invoice, db})\ncharge_type=CAPEX"

note over AccountingAgent: "Étape 1 — Écriture d'acquisition"
AccountingAgent -> AccountingAgent: "Generate PCE journal entry"
AccountingAgent -> Database: "save JournalEntry:\n  Débit 2184: 12 000.000 TND\n  Débit 4366 TVA: 2 280.000 TND\n  Crédit 401 Fournisseur: 14 280.000 TND"

note over AccountingAgent: "Étape 2 — Durée amortissement (IA)"
AccountingAgent -> Ollama: "complete('Durée amortissement PCE\npour: Serveur Dell PowerEdge\ncatégorie: Matériel informatique')"
Ollama --> AccountingAgent: "'5' (entier entre 1-20)"
AccountingAgent -> AccountingAgent: "Parse: 5 ans\nsource = 'AI'"

alt "Ollama indisponible"
  AccountingAgent -> AccountingAgent: "fallback: 5 ans\nsource = 'DEFAULT'"
end

note over AccountingAgent: "Étape 3 — Création immobilisation"
AccountingAgent -> Database: "save Asset:\n  designation='Serveur Dell PowerEdge R740'\n  compte_immob='2184'\n  compte_amort='28184'\n  acquisition_cost_ht=12 000.000\n  useful_life_years=5\n  method='linear'\n  amortization_source='AI'"

note over AccountingAgent: "Étape 4 — Explication comptable (IA)"
AccountingAgent -> Ollama: "complete('Explique écriture:\n2184 Débit 12000\n4366 Débit 2280\n401 Crédit 14280')"
Ollama --> AccountingAgent: "'Acquisition immobilisée selon PCE art.23:\nbien durable > 1 an comptabilisé en 2184...'"
AccountingAgent -> Database: "save accounting_explanation in JournalEntry"

AccountingAgent --> FastAPI: "AgentResult:\n  asset_created=true\n  amortization_years=5\n  amortization_source=AI\n  is_balanced=true"

note over Comptable: "Consultation dans /capex"
Comptable -> Frontend: "Ouvre /capex"
Frontend -> FastAPI: "GET /api/assets"
FastAPI -> Database: "SELECT assets"
Database --> FastAPI: "Asset + book_value_at(today)"
FastAPI --> Frontend: "Asset:\n  VNC au 01/07/2026 = 12 000.000 TND\n  Annuité = 2 400.000 TND\n  Valeur résiduelle 2031 = 0.000 TND"
Frontend --> Comptable: "📊 Immobilisation affichée avec plan d'amortissement"

note over FastAPI: "Chaque fin de mois (APScheduler)\nDotation aux amortissements automatique:\n  Débit 6811: 200.000 TND/mois\n  Crédit 28184: 200.000 TND/mois"
```
