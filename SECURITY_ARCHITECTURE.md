# Documentation Projet — BIAT IT Billing Agent

**Filiale** : BIAT Innovations & Technology  
**Système** : Automatisation intelligente des factures fournisseurs / clients  
**Stagiaire** : Baya Chaabene  
**Classification** : Confidentiel — Usage interne

---

## Table des matières

1. [Présentation du projet](#1-présentation-du-projet)
2. [Architecture technique](#2-architecture-technique)
3. [Fonctionnalités implémentées](#3-fonctionnalités-implémentées)
4. [Pipeline IA de traitement des factures](#4-pipeline-ia-de-traitement-des-factures)
5. [Architecture de sécurité](#5-architecture-de-sécurité)
6. [Module LDAP mock](#6-module-ldap-mock)
7. [Base de données](#7-base-de-données)
8. [API REST](#8-api-rest)
9. [Interface utilisateur](#9-interface-utilisateur)
10. [Tests](#10-tests)
11. [Déploiement](#11-déploiement)
12. [Recommandations](#12-recommandations)

---

## 1. Présentation du projet

### Objectif

Système intelligent d'automatisation de la facturation pour BIAT IT. Il traite les factures fournisseurs et clients de A à Z :

```
PDF / Image
    │
    ▼
OCR + LLM (local)          ← Tesseract + Ollama qwen2.5:3b
    │
    ▼
Extraction des champs      ← fournisseur, montant, TVA, date, N° facture
    │
    ▼
Classification PCE         ← code comptable (6xxx OPEX / 2xxx CAPEX)
    │
    ▼
Validation & anomalies     ← contrôle TVA, doublons, montants suspects
    │
    ▼
Écriture comptable         ← journal double entrée (PCE tunisien)
    │
    ▼
Suivi budgétaire           ← budget vs réel, alertes dépassement
```

### Contrainte bancaire principale

> **DATA RESIDENCY : LOCAL ONLY**
> Aucune donnée de facturation ne peut être envoyée vers des API cloud (OpenAI, Anthropic, Google, AWS hors Tunisie). Ollama est le seul backend LLM autorisé. Exigence BCT (Banque Centrale de Tunisie).

---

## 2. Architecture technique

### Stack

| Couche | Technologie | Version |
|---|---|---|
| Backend | FastAPI + SQLAlchemy | Python 3.14 |
| Frontend | React + TypeScript + Tailwind | Vite |
| Base de données | SQLite (WAL mode) | — |
| LLM | Ollama `qwen2.5:3b` | local :11434 |
| OCR | Tesseract | local |
| Auth | JWT HS256 + LDAP hybrid | — |
| Tests | pytest | 9.0.3 |

### Vue d'ensemble

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         PÉRIMÈTRE LOCAL BIAT IT                         │
│                                                                         │
│  ┌──────────────┐   HTTP/HTTPS    ┌──────────────────────────────────┐  │
│  │  React/TS    │ ◄────────────► │      FastAPI :8000                │  │
│  │  :5173       │                │  ┌──────────────────────────────┐ │  │
│  │              │                │  │  Auth · RBAC · RateLimit     │ │  │
│  │  Pages :     │                │  │  CORS · JWT · Audit HMAC     │ │  │
│  │  Factures    │                │  └──────────────────────────────┘ │  │
│  │  Budget      │                │           │          │             │  │
│  │  Projets     │                │    ┌──────▼───┐ ┌────▼──────┐    │  │
│  │  Risques     │                │    │  SQLite  │ │  Ollama   │    │  │
│  │  Journal     │                │    │  WAL     │ │  :11434   │    │  │
│  │  Admin       │                │    └──────────┘ └───────────┘    │  │
│  └──────────────┘                └──────────────────────────────────┘  │
│                                                                         │
│  ══════════════  Aucune donnée ne quitte ce périmètre  ══════════════   │
└─────────────────────────────────────────────────────────────────────────┘
```

### Structure du projet

```
internship_biat/
├── backend/
│   ├── api/
│   │   ├── routers/          ← endpoints REST (invoices, auth, budget, risks…)
│   │   ├── security/         ← jwt_handler, file_validator, account_lockout, audit_integrity
│   │   └── main.py           ← middlewares (CORS, RateLimit, CSP)
│   ├── src/
│   │   ├── agent/            ← config_loader.py (wire AIComponents) — l'ancien daemon
│   │   │                       (pipeline.py + agent.py) a été supprimé en 2026-07
│   │   ├── ai_agents/        ← InvoiceProcessingOrchestrator + 6 agents IA spécialisés
│   │   ├── models/           ← InvoiceRecord, enums, journal, asset
│   │   ├── storage/          ← ORM SQLAlchemy + repositories
│   │   ├── extraction/       ← HybridExtractor (PDF natif → OCR → LLM)
│   │   ├── classification/   ← AccountingCoder (règles + ML)
│   │   ├── validation/       ← champs, cohérence, doublons, anomalies
│   │   ├── accounting/       ← génération écritures double entrée
│   │   ├── budget/           ← BudgetTracker, plan vs réel
│   │   ├── capex/            ← amortissements linéaires/dégressifs
│   │   └── services/         ← email, audit, LDAP, ldif_parser, mock_ldap_auth
│   ├── mock_ldap_data/       ← annuaire LDIF de test (5 utilisateurs)
│   └── tests/
│       ├── unit/             ← 42 fichiers
│       └── integration/      ← API E2E avec vraie base Mongo de test
├── frontend/
│   └── src/pages/
│       ├── factures/         ← upload, liste, détail facture
│       ├── comptabilite/     ← journal, grand livre, échéancier
│       ├── projets/          ← projets, budget projet, livrables
│       ├── transversal/      ← risques (par projet), feuille de route
│       ├── pilotage/         ← KPI dashboard, budget, immobilisations
│       └── admin/            ← gestion utilisateurs, audit, sécurité
├── scripts/
│   ├── seed_budget_actuals.py   ← 77 factures JOURNALED Jan–Jun 2026
│   ├── seed_risks_par_projet.py ← 9 risques (3/projet) liés à PRJ-CBK/IC/PCD
│   └── seed_roadmap.py          ← 16 jalons sur 4 trimestres 2026
└── config/
    ├── settings.yaml
    ├── cost_catalog.yaml        ← 33 catégories PCE
    └── budget_plan.yaml         ← plan annuel 12 mois par catégorie
```

---

## 3. Fonctionnalités implémentées

### 3.1 Traitement des factures

| Fonctionnalité | Description |
|---|---|
| Upload PDF/image | Validation magic bytes + taille + extension |
| Extraction OCR | Tesseract pour les images scannées |
| Extraction LLM | Ollama qwen2.5:3b pour les PDF natifs |
| Classification PCE | Règles + ML (TF-IDF + LogisticRegression) |
| Validation automatique | TVA, montants, doublons, anomalies |
| Écriture comptable | Journal double entrée conforme PCE tunisien |
| File de révision | Interface humaine pour les factures signalées |
| Voir PDF | Téléchargement du PDF original depuis le détail |
| Voir écriture | Affichage inline des lignes débit/crédit |

### 3.2 Budget & Finance

| Fonctionnalité | Description |
|---|---|
| Plan budgétaire | Plan mensuel par catégorie de charge (12 mois) |
| Suivi des réels | Agrégation automatique depuis les factures JOURNALED |
| Alertes dépassement | Seuils configurables, indicateurs rouge/orange |
| Données de test | 77 factures seeded couvrant 13 catégories (Jan–Jun 2026) |
| Immobilisations (CAPEX) | Amortissement linéaire et dégressif, registre d'actifs |
| Échéancier | Suivi des paiements et pénalités de retard |

### 3.3 Gestion de projets

| Fonctionnalité | Description |
|---|---|
| Projets | PRJ-CBK (Core Banking), PRJ-IC (Cloud), PRJ-PCD (Portail Digital) |
| Feuille de route | Gantt par trimestre, jalons LATE/AT RISK/ON TIME |
| Risques par projet | Matrice probabilité × impact, criticité calculée |
| Livrables | Suivi par phase avec statut de livraison |
| Budget projet | Plan vs réel par projet |

### 3.4 Administration & Sécurité

| Fonctionnalité | Description |
|---|---|
| Gestion utilisateurs | CRUD complet, création avec envoi d'email automatique |
| Tableau de bord sécurité | Tentatives échouées, fichiers rejetés, tokens révoqués |
| Audit trail | Toutes les actions tracées avec HMAC-SHA256 |
| Vérification intégrité | Détection de falsification des logs d'audit |

### 3.5 Authentification

| Fonctionnalité | Description |
|---|---|
| Login local | Comptes démo + comptes créés par l'Admin |
| LDAP hybride | `@biat.local` via OpenLDAP, autres en local |
| OTP email | Vérification 6 chiffres (TTL 10 min) avant accès |
| Photo de profil | Upload base64, max 2 MB, stockée en base |
| Mot de passe | Changement avec vérification de l'ancien + OTP |

---

## 4. Pipeline IA de traitement des factures

### 4.1 Agents IA

```
ExtractionAgent
    └── HybridExtractor.extract()
        ├── Route 1 : PDF natif → extraction texte → LLM (qwen2.5:3b)
        ├── Route 2 : Image → Tesseract OCR → LLM
        └── Champs extraits : issuer, N° facture, date, montants, TVA
                             + score de confiance 0.0–1.0 par champ

ClassificationAgent
    └── AccountingCoder
        ├── Niveau A : règles YAML (mots-clés → compte PCE)
        └── Niveau B : ML TF-IDF + LogisticRegression (fallback)

AnomalyAgent
    ├── Vérification TVA (taux autorisés : 0%, 7%, 13%, 19%)
    ├── Cohérence HT + TVA = TTC (tolérance 0.005 TND)
    ├── Détection doublons (hash fichier + similarité)
    └── Montants suspects (HIGH_VALUE, SUSPICIOUS_AMOUNT)

AccountingAgent
    └── EntryGenerator → écriture double entrée
        ├── Débit  : 6xxx (charges) ou 2xxx (CAPEX)
        ├── Crédit : 401 (fournisseurs)
        └── TVA    : 4366 (déductible) / 4367 (collectée)
```

### 4.2 Statuts du pipeline

```
RECEIVED → EXTRACTED → CLASSIFIED → VALIDATED / FLAGGED → JOURNALED → PAID
```
(Les statuts intermédiaires `-ING` et `EXPORTING`/`EXPORTED` existent encore dans
l'enum mais ne sont plus jamais posés par `InvoiceProcessingOrchestrator` — c'était le
comportement de l'ancien daemon `agent/pipeline.py`, supprimé en 2026-07.)

Statuts terminaux (arrêt pipeline) : `FLAGGED, ESCALATED, ERROR, EXTRACTION_FAILED`

### 4.3 Correction du verrou SQLite (correctif de session, historique)

**Problème identifié à l'époque** : le pipeline utilisait deux sessions SQLAlchemy différentes simultanément (session FastAPI + session PipelineComponents), provoquant un verrou SQLite (`database is locked`) qui bloquait toutes les mises à jour de statut.

**Correction à l'époque** : l'orchestrateur utilisait un `InvoiceRepository(self._db)` construit sur la session FastAPI transmise en paramètre — une seule session active par requête.

**Note (2026-07)** : ce correctif décrivait l'état SQLAlchemy d'alors. Depuis,
la facture elle-même est lue/écrite via `SyncMongoInvoiceRepository()` (Mongo,
pas SQLAlchemy) dans `InvoiceProcessingOrchestrator.__init__` — le verrou SQLite décrit
ci-dessus ne peut plus se produire sur ce chemin. `self._db` (SQLAlchemy)
reste un paramètre réel du constructeur, transmis à certains agents, mais
n'est plus utilisé pour le repository des factures.

---

## 5. Architecture de sécurité

### 5.1 Vue d'ensemble

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          PÉRIMÈTRE DE SÉCURITÉ                              │
│                                                                             │
│   ┌──────────────┐    HTTPS/TLS     ┌─────────────────────────────────┐    │
│   │   Navigateur │ ──────────────► │        Reverse Proxy (prod)      │    │
│   │  React/TS    │ ◄────────────── │        (nginx / Caddy)           │    │
│   └──────────────┘                 └───────────────┬─────────────────┘    │
│                                                    ▼                       │
│                                    ┌───────────────────────────┐           │
│                                    │    FastAPI :8000           │           │
│                                    │  ┌─────────────────────┐  │           │
│                                    │  │  SlowAPI RateLimiter │  │           │
│                                    │  │  CORS Middleware      │  │           │
│                                    │  │  JWT Auth Guard       │  │           │
│                                    │  │  RBAC require_role()  │  │           │
│                                    │  └─────────────────────┘  │           │
│                                    └──────┬──────────┬──────────┘           │
│                              ┌────────────▼──┐  ┌────▼────────────┐        │
│                              │  SQLite WAL   │  │  Ollama :11434  │        │
│                              │  (local only) │  │  qwen2.5:3b     │        │
│                              └───────────────┘  └─────────────────┘        │
│                                                                             │
│   ══════  Aucune donnée de facturation ne quitte ce périmètre  ══════       │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 5.2 Authentification

#### Modes (AUTH_MODE)

```
AUTH_MODE=hybrid
       │
       ├── @biat.local  ──► LDAP (OpenLDAP docker / mock LDIF)
       │                        └── bind DN + vérification mot de passe
       │                            attributs : uid, cn, mail, departmentNumber
       └── autres       ──► Base locale SQLite (UserORM + bcrypt)
```

#### Flux de connexion avec OTP

```
Utilisateur → POST /auth/login → vérification identifiants
                               → check account_lockout
                               → génération OTP 6 chiffres (TTL 10 min)
                               → send_otp_email() via SMTP Gmail
                               ← {require_otp: true}
Utilisateur → POST /auth/verify-otp → vérification code
                                    ← access_token (8h) + refresh_token (7j)
```

#### Protection brute-force

| Paramètre | Valeur | Variable |
|---|---|---|
| Tentatives max | 5 | `MAX_FAILED_LOGIN_ATTEMPTS` |
| Durée verrou | 15 min | `ACCOUNT_LOCKOUT_MINUTES` |
| Déverrouillage | Automatique | — |

### 5.3 Tokens JWT

```
Payload : {
  "sub"   : "user_id",
  "role"  : "Comptable",
  "email" : "user@biat.local",
  "type"  : "access",
  "exp"   : now + 8h,
  "jti"   : "uuid-v4"          ← révocation individuelle
}
Signature : HMAC-SHA256(secret ≥ 32 chars)
```

- Révocation par liste noire `jti` (table `revoked_tokens`)
- Refresh token : cookie HttpOnly, `Secure=true` en production

### 5.4 Contrôle d'accès (RBAC)

#### Matrice des rôles

| Module | Comptable | Chef de Projet | Direction | Admin |
|---|:---:|:---:|:---:|:---:|
| Upload / validation factures | ✓ | — | — | ✓ |
| Journal comptable | ✓ | — | ✓ | ✓ |
| Budget | ✓ | — | ✓ | ✓ |
| Roadmap / Risques | — | ✓ | ✓ | ✓ |
| Audit log | — | — | ✓ | ✓ |
| Gestion utilisateurs | — | — | — | ✓ |
| Tableau de bord sécurité | — | — | — | ✓ |

#### Implémentation

```python
@router.post("/upload")
async def upload_invoice(
    _: dict = Depends(require_role("Comptable", "Admin"))
): ...
```

### 5.5 Intégrité des logs d'audit (HMAC)

```python
# Chaque ligne signée à l'écriture
payload = f"{id}|{created_at}|{user_id}|{action}|{resource}|{status}|{ip}"
row_hash = HMAC-SHA256(payload, AUDIT_HMAC_SECRET)

# Vérification : détecte toute modification manuelle
verify_row_hash(log) → True | False
```

### 5.6 Validation des fichiers uploadés

```
Fichier reçu
    ├─ 1. Taille       → max 20 MB
    ├─ 2. Extension    → whitelist : pdf, jpg, jpeg, png, tiff
    ├─ 3. Magic bytes  → %PDF / \xFF\xD8\xFF / \x89PNG / II* MM*
    ├─ 4. Cohérence    → extension = magic bytes
    └─ 5. Stockage     → data/uploads/{sha256}{ext}
```

### 5.7 Sécurité API

| Mécanisme | Détail |
|---|---|
| Rate limiting | SlowAPI : 10 req/min sur login et upload |
| CORS | Origines whitelist (:5173, :5174) |
| Validation entrées | Pydantic v2 — types stricts, longueurs max |
| Pas de SQL brut | SQLAlchemy ORM uniquement |
| CSP | Content-Security-Policy header (prod) |
| HSTS | HTTP Strict Transport Security (prod) |

### 5.8 Tableau des menaces

| Menace | Contre-mesure |
|---|---|
| Brute-force | Account lockout 5 tentatives / 15 min |
| Vol de token | Révocation JTI + expiration 8h |
| Fuite cloud | Architecture 100% locale (Ollama, SQLite) |
| Upload malveillant | Magic bytes + whitelist + taille max |
| Injection SQL | SQLAlchemy ORM uniquement |
| CSRF | JWT stateless + CORS strict |
| Falsification logs | HMAC-SHA256 par ligne |
| XSS | React (échappement auto) + CSP |
| Élévation privilèges | `require_role()` sur chaque route |
| Écoute réseau | TLS + cookies Secure + HttpOnly |

---

## 6. Module LDAP mock

### 6.1 Objectif

Simuler un annuaire d'entreprise LDAP sans dépendance externe (pas de docker, pas de python-ldap) pour les environnements de développement et de test.

### 6.2 Architecture

```
backend/
├── mock_ldap_data/
│   └── users.ldif              ← annuaire simulé
└── src/services/
    ├── ldif_parser.py          ← parse LDIF + décode base64
    └── mock_ldap_auth.py       ← MockLDAPAuth singleton
```

### 6.3 ldif_parser.py

```python
parse_ldif(filepath: str) -> list[dict]
```

- Découpe le fichier en blocs séparés par lignes vides
- Décode automatiquement les valeurs base64 (`attr:: valeur`)
- Accumule `objectClass` en liste
- Ignore les entrées sans `uid` (OU racine, etc.)

### 6.4 mock_ldap_auth.py

```python
auth = MockLDAPAuth.get()                        # singleton thread-safe
user = auth.authenticate("mtrabelsi", "biat2026")
# → {"uid": "mtrabelsi", "cn": "Mohamed Trabelsi",
#    "mail": "mtrabelsi@biat.local", "role": "Chef_Projet"}
# → None si échec
```

#### Mapping département → rôle

| `departmentNumber` | Rôle applicatif |
|---|---|
| `100` | `Direction` |
| `200` | `Chef_Projet` |
| `300` | `Comptable` |
| `900` | `Admin` |
| autre | `Comptable` (défaut) |

### 6.5 Utilisateurs de test

| uid | Nom | Rôle | Mot de passe |
|---|---|---|---|
| `admin` | Administrateur Système | Admin | `admin2026` |
| `mtrabelsi` | Mohamed Trabelsi | Chef_Projet | `biat2026` |
| `abenali` | Amira Ben Ali | Comptable | `biat2026` |
| `kbouaziz` | Karim Bouaziz *(base64)* | Direction | `biat2026` |
| `smansour` | Sonia Mansour | Comptable | `biat2026` |

---

## 7. Base de données

### Modèle de données principal

```
invoices                   ← factures (cœur du système)
  ├── journal_entries      ← écritures comptables
  ├── journal_lines        ← lignes débit/crédit
  └── invoice_flags        ← anomalies détectées

users                      ← comptes locaux
  └── revoked_tokens       ← liste noire JWT

assets                     ← immobilisations CAPEX
budget_plans               ← plan mensuel par catégorie
projects                   ← projets IT
  ├── feuilles_de_route    ← jalons
  ├── risques              ← matrice des risques
  └── livrables            ← livrables par phase

audit_logs                 ← traçabilité (HMAC par ligne)
```

### Plan Comptable (PCE Tunisien)

| Compte | Usage |
|---|---|
| `401` | Fournisseurs |
| `411` | Clients |
| `4366` | TVA déductible |
| `4367` | TVA collectée |
| `6xxx` | Charges (OPEX) |
| `2xxx` | Immobilisations (CAPEX) |
| `6811` | Dotations amortissements |
| `28xx` | Amortissements cumulés |

---

## 8. API REST

### Principaux endpoints

| Méthode | Route | Rôle requis | Description |
|---|---|---|---|
| `POST` | `/auth/login` | — | Connexion |
| `POST` | `/auth/verify-otp` | — | Validation OTP |
| `POST` | `/invoices/upload` | Comptable, Admin | Upload + pipeline complet |
| `GET` | `/invoices/{id}/pdf` | Tous | Télécharger le PDF original |
| `GET` | `/invoices/{id}/pipeline-status` | Tous | Statut temps réel des étapes |
| `GET` | `/budget/summary` | Comptable, Direction, Admin | Synthèse budget vs réel |
| `GET` | `/journal` | Comptable, Direction, Admin | Écritures comptables |
| `GET` | `/assets` | Tous | Registre des immobilisations |
| `GET` | `/audit/logs` | Direction, Admin | Journal d'audit |
| `POST` | `/audit/verify-integrity` | Admin | Vérification HMAC |
| `GET` | `/admin/users` | Admin | Liste des utilisateurs |
| `POST` | `/admin/users` | Admin | Créer un utilisateur + email |

---

## 9. Interface utilisateur

### Pages principales

| Page | Route | Description |
|---|---|---|
| Accueil / Upload | `/upload` | Upload facture + suivi pipeline IA |
| KPI Dashboard | `/dashboard` | Indicateurs clés temps réel |
| Toutes les factures | `/factures` | Liste + détail + PDF + écriture |
| File de révision | `/review` | Factures signalées à valider |
| Suivi | `/suivi` | Cycle de vie + réconciliation |
| Journal | `/journal` | Écritures comptables |
| Budget | `/budget` | Plan vs réel (graphiques) |
| Immobilisations | `/immobilisations` | Registre CAPEX + amortissements |
| Projets | `/projets` | Fiche projet + phases |
| Feuille de route | `/roadmap` | Gantt trimestriel |
| Risques | `/risques` | Matrice par projet |
| Audit | `/audit` | Logs + vérification intégrité |
| Admin | `/admin` | Gestion utilisateurs + sécurité |

---

## 10. Tests

### Couverture

| Suite | Fichiers | Tests |
|---|---|---|
| Unit | 15 fichiers | ~629 tests |
| LDAP mock (nouveau) | 1 fichier | 18 tests |
| Integration E2E | 1 fichier | pipeline complet |

### Lancer les tests

```bash
source .venv/bin/activate

# Tous les tests
.venv/bin/pytest

# Seulement les tests LDAP mock
.venv/bin/pytest backend/tests/unit/test_ldif_mock.py -v

# Tests unitaires uniquement
.venv/bin/pytest backend/tests/unit/ --tb=short -q
```

---

## 11. Déploiement

### Développement

```bash
# Backend
source .venv/bin/activate
python scripts/run_api.py        # FastAPI sur :8000

# Frontend
cd frontend && npm run dev       # React sur :5173

# LLM local (requis)
ollama run qwen2.5:3b
```

### Variables d'environnement requises

```env
JWT_SECRET=<min 32 chars>
SMTP_PASSWORD=<app password Gmail>
EMAIL_ENABLED=true
AUTH_MODE=hybrid                 # local | ldap | hybrid
OLLAMA_BASE_URL=http://localhost:11434
DATABASE_URL=sqlite:///./data/invoices.db
PCE_VECTORSTORE_AUTO_INDEX=false # évite le chargement du modèle HuggingFace
```

---

## 12. Recommandations

| Priorité | Recommandation |
|---|---|
| 🔴 Haute | Migrer vers **argon2id** pour le hachage des mots de passe |
| 🔴 Haute | Activer `COOKIE_SECURE=true` dès passage en HTTPS |
| 🟡 Moyenne | Chiffrement au repos de `data/invoices.db` (SQLCipher) |
| 🟡 Moyenne | Rotation automatique des secrets JWT |
| 🟡 Moyenne | Injection des secrets via HashiCorp Vault (production) |
| 🟢 Basse | Centraliser les logs dans un SIEM (ex: Wazuh) |
| 🟢 Basse | Activer MFA hardware (TOTP) pour les comptes Admin |
| 🟢 Basse | Remplacer SQLite par PostgreSQL pour une utilisation multi-utilisateurs |
