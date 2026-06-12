# BIAT IT — Système de Gestion de la Facturation v3

Automatisation intelligente des factures fournisseurs et émission des factures clients
pour BIAT IT (filiale SI de la BIAT, Tunisie).

## Démarrage rapide

```bash
# 1. Activer l'environnement virtuel
source .venv/bin/activate

# 2. Lancer l'interface Streamlit
streamlit run app/Home.py          # démarre sur :8502

# 3. Démarrer le daemon de traitement automatique (optionnel)
python scripts/run_agent.py        # surveille ./inbox/

# 4. Générer des factures de démonstration
python scripts/make_demo_projects.py   # données projets
python scripts/make_mock_invoices.py   # 10 factures fournisseurs
```

Mot de passe par défaut : `biat2024` (configurable dans `.streamlit/secrets.toml`)

## Fonctionnalités

### Traitement des factures fournisseurs
- **Extraction** : PDF natif → OCR (Tesseract) → LLM local (Ollama `qwen2.5:3b`)
- **Classification** : règles métier + catalogue PCE (33 catégories) + ML (TF-IDF)
- **Validation** : contrôle mathématique, doublons, champs obligatoires, anomalies
- **Export** : écritures comptables double-entrée (PCE tunisien)

### Facturation client (BIAT IT → BIAT)
- Chartes de projet, phases, fiches mensuelles
- Calcul automatique HT × taux JH
- Avances sur projets programmés
- PDF A4 en français (fpdf2)

### Allocation OPEX/CAPEX par projet
- Répartition au prorata des JH consommés
- Amortissement CAPEX exprimé en valeur mensuelle par actif
- Dashboard coût réel vs montant facturé

### Tableaux de bord
| Page | Contenu |
|------|---------|
| Dashboard | KPIs temps réel, ageing, taux d'approbation |
| Review Queue | Validation humaine des factures en erreur |
| Journal | Écritures comptables double-entrée |
| Budget | Budget prévu vs réalisé par catégorie |
| Immobilisations | Registre CAPEX, plans d'amortissement |
| Facturation | Émission factures mensuelles projets |
| Direction | Vue consolidée (trésorerie, CAPEX, facturation) |
| KPI Dashboard | 10 indicateurs clés de performance |

## Stack technique

| Composant | Technologie |
|-----------|-------------|
| Backend | Python 3.14, Pydantic v2, SQLAlchemy 2.0 |
| Base de données | SQLite (WAL mode) → PostgreSQL (prod, même code) |
| Migrations | Alembic |
| LLM | Ollama `qwen2.5:3b` — **local uniquement** |
| OCR | Tesseract |
| UI | Streamlit 1.58 |
| Graphiques | Plotly Express / Graph Objects |
| PDF | fpdf2 |
| ML classifieur | scikit-learn (TF-IDF + Régression Logistique) |
| Tests | pytest 9.0, 526 tests |

## Contrainte de sécurité

> **Toute l'inférence IA est locale (Ollama).** Aucune donnée de facturation
> n'est transmise à un service cloud (OpenAI, Anthropic, Groq, etc.).
> BIAT IT est une filiale bancaire soumise à des règles de résidence des données.

## Structure du projet

```
src/
  agent/          pipeline.py (fonctions pures) + agent.py (daemon)
  billing/        project_repository, monthly_invoice_builder, cost_allocator
  models/         invoice, client_invoice, project, cost_allocation, asset
  storage/        ORM (SQLAlchemy), repository, migrations (Alembic)
  extraction/     HybridExtractor (PDF → OCR → LLM)
  classification/ AccountingCoder (règles + ML), CostCatalog
  validation/     FieldValidator, CoherenceChecker, DuplicateDetector
  accounting/     EntryGenerator (PCE tunisien)
  budget/         BudgetTracker, CostAnalyzer
  capex/          DepreciationCalculator (linéaire / dégressif)

app/
  Home.py         Upload + pipeline
  pages/          11 pages Streamlit

config/
  settings.yaml   Configuration principale
  cost_catalog.yaml  33 catégories PCE
  budget_plan.yaml   Budget annuel mensuel

tests/
  unit/           15 fichiers, ~460 tests
  integration/    test_pipeline_e2e, test_project_billing_e2e
```

## Commandes utiles

```bash
# Tests
pytest --tb=short -q

# Migrations
alembic upgrade head
alembic current
alembic history

# Lint
ruff check src/ app/ tests/

# Réentraîner le classificateur ML
python -c "
from src.agent.config_loader import build_pipeline_components, load_config
from src.classification.ml_classifier import MLClassifier
cfg = load_config()
clf = MLClassifier(cfg['classification']['ml_model_path'])
components, _ = build_pipeline_components()
clf.retrain_from_repo(components.repository)
components.close()
"
```
