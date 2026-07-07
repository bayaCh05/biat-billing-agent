# Architecture de Sécurité — BIAT IT Billing Agent

**Filiale** : BIAT Innovations & Technology  
**Système** : Automatisation des factures fournisseurs / clients  
**Classification** : Confidentiel — Usage interne

---

## 1. Vue d'ensemble

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          PÉRIMÈTRE DE SÉCURITÉ                              │
│                                                                             │
│   ┌──────────────┐    HTTPS/TLS     ┌─────────────────────────────────┐    │
│   │   Navigateur │ ──────────────► │        Reverse Proxy (prod)      │    │
│   │  React/TS    │ ◄────────────── │        (nginx / Caddy)           │    │
│   │  :5173       │                 └───────────────┬─────────────────┘    │
│   └──────────────┘                                 │                       │
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
│                                           │          │                      │
│                              ┌────────────▼──┐  ┌────▼────────────┐        │
│                              │  SQLite WAL   │  │  Ollama :11434  │        │
│                              │  (local only) │  │  qwen2.5:3b     │        │
│                              │  data/invoices│  │  (local only)   │        │
│                              └───────────────┘  └─────────────────┘        │
│                                                                             │
│   ══════════════════════════════════════════════════════════════════════    │
│   ⚠  Aucune donnée de facturation ne quitte ce périmètre (BCT/RGPD)        │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Authentification

### 2.1 Modes d'authentification (AUTH_MODE)

```
AUTH_MODE=hybrid   ←  configuration actuelle
       │
       ├── @biat.local  ──►  LDAP  (OpenLDAP docker / mock LDIF)
       │                       │
       │                       └── bind DN + vérification mot de passe
       │                           attributs : uid, cn, mail, departmentNumber
       │
       └── autres      ──►  Base locale SQLite (UserORM)
                              │
                              └── bcrypt hash (argon2 prévu migration)
```

| Mode | Description | Cas d'usage |
|---|---|---|
| `local` | Comptes démo uniquement (`@biat-it.tn`) | Tests unitaires |
| `ldap` | Tous les utilisateurs via LDAP | Production BIAT |
| `hybrid` | LDAP pour `@biat.local`, local pour les autres | Développement |

### 2.2 Flux d'authentification complet

```
Utilisateur          Frontend              Backend                  LDAP / DB
    │                    │                    │                         │
    │── login form ──►   │                    │                         │
    │                    │── POST /auth/login ►│                         │
    │                    │                    │── bind + search ────────►│
    │                    │                    │◄─ entrée utilisateur ────│
    │                    │                    │                         │
    │                    │                    │── vérifier mot de passe  │
    │                    │                    │── check account_lockout  │
    │                    │                    │                         │
    │                    │                    │── générer OTP (6 chiffres)
    │                    │                    │── send_otp_email() ──────────► SMTP Gmail
    │                    │◄── {require_otp} ──│                         │
    │                    │                    │                         │
    │── code OTP ────►   │                    │                         │
    │                    │── POST /auth/verify-otp ►                    │
    │                    │                    │── vérifier OTP (TTL 10min)
    │                    │◄── access_token    │                         │
    │                    │    refresh_token   │                         │
    │                    │    (HttpOnly cookie)                         │
```

### 2.3 Protection contre le brute-force

| Paramètre | Valeur | Variable d'environnement |
|---|---|---|
| Tentatives max | 5 | `MAX_FAILED_LOGIN_ATTEMPTS` |
| Durée verrou | 15 min | `ACCOUNT_LOCKOUT_MINUTES` |
| Déverrouillage | Automatique à expiration | — |

---

## 3. Tokens JWT

### 3.1 Structure

```
Header  : { "alg": "HS256", "typ": "JWT" }

Payload : {
  "sub"   : "user_id",          ← identifiant unique
  "role"  : "Comptable",        ← rôle RBAC
  "email" : "user@biat.local",
  "type"  : "access",           ← access | refresh
  "iat"   : 1720000000,
  "exp"   : 1720028800,         ← durée : 8h (access) / 7j (refresh)
  "jti"   : "uuid-v4"           ← identifiant unique pour révocation
}

Signature : HMAC-SHA256(base64(header) + "." + base64(payload), JWT_SECRET)
```

### 3.2 Cycle de vie

```
Login réussi
    │
    ├──► access_token  (8h)   ──► Authorization: Bearer <token>
    └──► refresh_token (7j)   ──► Cookie HttpOnly (Secure en prod)
              │
              │ expiration access_token
              ▼
        POST /auth/refresh
              │
              ├── vérifier refresh_token
              ├── vérifier non-révoqué (table revoked_tokens)
              └──► nouveau access_token

Déconnexion
    └──► jti inscrit dans revoked_tokens (table SQLite)
```

### 3.3 Validation

- Algorithme : **HS256** uniquement (rejet de `alg:none`)
- Secret : minimum **32 caractères** (contrôle au démarrage)
- Révocation : liste noire `jti` en base (vérification à chaque requête)

---

## 4. Contrôle d'accès (RBAC)

### 4.1 Matrice des rôles

| Rôle | Source | Code départemental |
|---|---|---|
| `Admin` | Local ou LDAP dept=900 | 900 |
| `Comptable` | Local ou LDAP dept=300 | 300 |
| `Chef de Projet` | LDAP dept=200 | 200 |
| `Direction` | LDAP dept=100 | 100 |

### 4.2 Permissions par module

| Module / Route | Comptable | Chef de Projet | Direction | Admin |
|---|:---:|:---:|:---:|:---:|
| Upload facture | ✓ | — | — | ✓ |
| Valider facture | ✓ | — | — | ✓ |
| Voir journal comptable | ✓ | — | ✓ | ✓ |
| Gérer budget | ✓ | — | ✓ | ✓ |
| Roadmap / Risques | — | ✓ | ✓ | ✓ |
| Audit log | — | — | ✓ | ✓ |
| Gestion utilisateurs | — | — | — | ✓ |
| Tableau de bord sécurité | — | — | — | ✓ |

### 4.3 Implémentation

```python
# Décorateur FastAPI — vérifié avant chaque handler
@router.post("/upload")
async def upload_invoice(
    current_user: dict = Depends(require_role("Comptable", "Admin"))
):
    ...
```

---

## 5. Sécurité des données

### 5.1 Résidence des données — contrainte bancaire BCT

```
┌─────────────────────────────────────────────────────┐
│  RÈGLE ABSOLUE : données de facturation = LOCAL ONLY │
│                                                     │
│  ✓ Ollama (LLM local)     ← qwen2.5:3b sur :11434  │
│  ✓ SQLite (DB locale)     ← data/invoices.db        │
│  ✓ OCR Tesseract (local)  ← pas d'API cloud         │
│                                                     │
│  ✗ OpenAI / Anthropic / Groq  ← INTERDIT           │
│  ✗ AWS S3 hors Tunisie        ← INTERDIT (BCT)      │
│  ✗ Google Vision API          ← INTERDIT            │
└─────────────────────────────────────────────────────┘
```

### 5.2 Stockage

| Donnée | Stockage | Protection |
|---|---|---|
| Factures (texte extrait) | SQLite WAL | Fichier local, FK contraintes |
| PDF uploadés | `data/uploads/` | Hash SHA-256 comme nom de fichier |
| Mots de passe utilisateurs | SQLite + bcrypt | Hash non réversible |
| Tokens révoqués | SQLite (`revoked_tokens`) | TTL géré manuellement |
| Photos profil | SQLite (base64, max 2 MB) | Validation format + taille |
| Emails OTP | RAM uniquement | TTL 10 min, usage unique |
| Logs d'audit | SQLite | HMAC-SHA256 par ligne |

### 5.3 Intégrité des logs d'audit (HMAC)

```python
# Chaque ligne d'audit est signée à l'écriture
payload = f"{id}|{created_at}|{user_id}|{action}|{resource}|{status}|{ip}"
row_hash = HMAC-SHA256(payload, AUDIT_HMAC_SECRET)

# Vérification — détecte toute modification manuelle en base
verify_row_hash(log)  →  True | False (alerte si False)
```

---

## 6. Sécurité des fichiers uploadés

```
Fichier reçu
    │
    ├─ 1. Taille ──────► max 20 MB  (MAX_FILE_SIZE_MB)
    │
    ├─ 2. Extension ───► whitelist : pdf, jpg, jpeg, png, tiff
    │
    ├─ 3. Magic bytes ─► vérification des octets de tête
    │      ├── PDF    : %PDF
    │      ├── JPEG   : \xFF\xD8\xFF
    │      ├── PNG    : \x89PNG
    │      └── TIFF   : II* / MM\x00*
    │
    ├─ 4. Cohérence ───► extension = magic bytes  (ex: .pdf + magic PDF)
    │
    └─ 5. Stockage ────► data/uploads/{sha256}{ext}
                          nom de fichier = hash, jamais le nom original
```

---

## 7. Sécurité de l'API

### 7.1 Rate Limiting (SlowAPI)

| Endpoint | Limite |
|---|---|
| `POST /auth/login` | 10 req/min |
| `POST /invoices/upload` | 10 req/min |
| `POST /auth/request-otp` | 5 req/min |
| Autres endpoints | Non limité (authentification requise) |

### 7.2 CORS

```python
allow_origins  = ["http://localhost:5173", "http://localhost:5174"]  # dev
allow_methods  = ["GET", "POST", "PATCH", "DELETE", "OPTIONS"]
allow_headers  = ["Authorization", "Content-Type"]
allow_credentials = True  # cookies HttpOnly
```

### 7.3 Validation des entrées

- Toutes les données reçues passent par des schémas **Pydantic v2**
- Types stricts, longueurs max, formats vérifiés (UUID, date, email)
- Pas de requête SQL construite manuellement — **SQLAlchemy ORM** uniquement

---

## 8. Authentification LDAP mock (module développé)

```
backend/
├── mock_ldap_data/
│   └── users.ldif              ← annuaire simulé (5 utilisateurs)
└── src/services/
    ├── ldif_parser.py           ← parse LDIF + décode base64
    └── mock_ldap_auth.py        ← MockLDAPAuth singleton
           │
           ├── authenticate(uid, password) → dict | None
           ├── get_user(uid)               → dict | None
           └── Mapping departmentNumber → rôle applicatif
                  100 → Direction
                  200 → Chef_Projet
                  300 → Comptable
                  900 → Admin
```

---

## 9. Gestion des secrets

| Secret | Variable | Contrainte |
|---|---|---|
| Clé JWT | `JWT_SECRET` | ≥ 32 caractères, contrôlé au démarrage |
| Clé HMAC audit | `AUDIT_HMAC_SECRET` | Fallback sur `JWT_SECRET` si vide |
| Mot de passe SMTP | `SMTP_PASSWORD` | App Password Gmail (2FA) |
| Mot de passe LDAP admin | `LDAP_BIND_PASSWORD` | Jamais loggué |
| Mots de passe démo | `DEMO_*_PASSWORD` | Désactivables (`DISABLE_DEMO_USERS=true`) |

**En production** : ces variables doivent être injectées via un gestionnaire de secrets (HashiCorp Vault, AWS Secrets Manager) — jamais en clair dans le dépôt.

---

## 10. Menaces et contre-mesures

| Menace | Contre-mesure implémentée |
|---|---|
| Brute-force login | Account lockout (5 tentatives / 15 min) |
| Vol de token | Révocation JTI + expiration courte (8h) |
| Fuite de données vers cloud | Contrainte architecture locale (Ollama, SQLite) |
| Upload de fichier malveillant | Magic bytes + whitelist extension + taille max |
| Injection SQL | SQLAlchemy ORM (pas de SQL brut dynamique) |
| CSRF | Tokens JWT stateless + CORS strict |
| Falsification de logs | HMAC-SHA256 par ligne d'audit |
| XSS | React (échappement auto) + CSP (prod) |
| Élévation de privilèges | `require_role()` sur chaque route protégée |
| Écoute réseau | TLS (prod) + cookies `Secure` + `HttpOnly` |

---

## 11. Points d'amélioration (recommandations)

| Priorité | Recommandation |
|---|---|
| 🔴 Haute | Migrer vers **argon2id** pour le hachage des mots de passe (remplacer bcrypt) |
| 🔴 Haute | Activer **COOKIE_SECURE=true** dès passage en HTTPS |
| 🟡 Moyenne | Ajouter un **Content-Security-Policy** header en production |
| 🟡 Moyenne | Chiffrement au repos de `data/invoices.db` (SQLCipher) |
| 🟡 Moyenne | Rotation automatique des secrets JWT (clé versionnée) |
| 🟢 Basse | Centraliser les logs dans un SIEM (ex: Wazuh) |
| 🟢 Basse | Activer MFA hardware (TOTP) pour les comptes Admin |
