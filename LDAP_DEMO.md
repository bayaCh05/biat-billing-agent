# Authentification LDAP — Guide de démonstration

Ce guide explique comment lancer le serveur LDAP mock (Docker), tester le flux
d'authentification et présenter la fonctionnalité au superviseur.

---

## Prérequis

- Docker Desktop installé et démarré
- Python virtual env activé (`source .venv/bin/activate`)
- Serveur API démarré (`python scripts/run_api.py`)

---

## 1. Lancer le serveur LDAP mock

Depuis la racine du dépôt (`/Users/mac/Documents/internship_biat`), exécuter :

```bash
docker compose -f docker/ldap/docker-compose.yml up -d
```

Attendre ~20 secondes le temps que OpenLDAP importe les données de test.

**Vérifier que le conteneur est sain :**
```bash
docker compose -f docker/ldap/docker-compose.yml ps
# STATUS doit être "healthy"
```

**Interface web phpLDAPadmin (optionnel) :**
- URL : http://localhost:8081
- Login DN : `cn=admin,dc=biat,dc=local`
- Mot de passe : `admin_secret` (pas `admin_password`)

---

## 2. Comptes de test disponibles

| Email | Mot de passe | Rôle applicatif | Groupe LDAP |
|-------|-------------|-----------------|-------------|
| `abenali@biat.local` | `Biat2026!` | Admin | `cn=admins` |
| `mtrabelsi@biat.local` | `Biat2026!` | Comptable | `cn=comptables` |
| `kbouaziz@biat.local` | `Biat2026!` | Comptable | `cn=comptables` |
| `sbouhdid@biat.local` | `Biat2026!` | Chef de Projet | `cn=chefs_projet` |
| `lfradj@biat.local` | `Biat2026!` | Chef de Projet | `cn=chefs_projet` |
| `rchakroun@biat.local` | `Biat2026!` | Direction | `cn=direction` |

Les comptes démo `@biat-it.tn` continuent de fonctionner via l'authentification
locale (voir `.env` → `AUTH_MODE`).

---

## 3. Activer l'authentification LDAP

Modifier le fichier `.env` :

```ini
# Mode hybride : LDAP pour @biat.local, local pour @biat-it.tn
AUTH_MODE=hybrid
LDAP_USER_DOMAIN=biat.local
```

Redémarrer le serveur API pour que les nouvelles valeurs soient prises en compte :
```bash
lsof -ti :8000 | xargs kill -9
python scripts/run_api.py
```

**Modes disponibles :**

| `AUTH_MODE` | Comportement |
|------------|--------------|
| `local` | Uniquement la base de données locale (défaut — comptes démo) |
| `ldap` | LDAP uniquement pour tous les utilisateurs |
| `hybrid` | LDAP pour `@<LDAP_USER_DOMAIN>`, local pour les autres |

---

## 4. Tester un login LDAP

```bash
curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"mtrabelsi@biat.local","password":"Biat2026!"}' | python3 -m json.tool
```

Réponse attendue :
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "role": "Comptable",
  "user_id": "<uuid>",
  "force_password_change": false,
  "is_first_login": false
}
```

**Provisioning automatique :** à la première connexion LDAP, un compte local est
créé automatiquement en base de données avec le rôle mappé depuis le groupe LDAP.
Les connexions suivantes mettent à jour le rôle si le groupe LDAP a changé.

---

## 5. Vérifier la connexion LDAP manuellement

```bash
source .venv/bin/activate
python3 - << 'EOF'
from src.services.ldap_service import authenticate_ldap
result = authenticate_ldap("mtrabelsi@biat.local", "Biat2026!")
if result:
    print(f"✅  Authentifié : {result['givenName']} {result['sn']} — rôle : {result['role']}")
    print(f"    Groupes : {result['groups']}")
else:
    print("❌  Échec d'authentification (serveur injoignable ou mauvais mot de passe)")
EOF
```

---

## 6. Arrêter et réinitialiser le serveur LDAP

```bash
# Arrêt simple (conserve les données)
docker compose -f docker/ldap/docker-compose.yml stop

# Suppression complète + reset des données LDAP
docker compose -f docker/ldap/docker-compose.yml down -v
```

---

## Architecture du flux LDAP

```
Frontend (login)
    │
    ▼ POST /api/auth/login { email, password }
FastAPI (api/routers/auth.py)
    │
    ├─ AUTH_MODE=local  ──────────────────────────────────► Base locale (UserORM)
    │
    ├─ AUTH_MODE=ldap   ──────────────────────────────────►  LDAP uniquement
    │                                                         (401 si échec)
    │
    └─ AUTH_MODE=hybrid
        ├─ email @biat.local  ──► ldap_service.authenticate_ldap()
        │                              │
        │                              ├─ Admin bind → search user DN
        │                              ├─ User bind  → valide le mot de passe
        │                              └─ Group search → role mapping
        │                         ┌────────────┐
        │                         │ Provisioning│  (1ère connexion)
        │                         │  UserORM   │  Crée compte local
        │                         └────────────┘
        │                         ► JWT access_token + refresh cookie
        │
        └─ email @biat-it.tn ──► Base locale (comportement inchangé)
```

---

## Variables d'environnement LDAP

| Variable | Défaut | Description |
|----------|--------|-------------|
| `AUTH_MODE` | `local` | Mode d'authentification |
| `LDAP_USER_DOMAIN` | `biat.local` | Domaine routé vers LDAP (mode hybrid) |
| `LDAP_URL` | `ldap://localhost:389` | URL du serveur LDAP |
| `LDAP_BASE_DN` | `dc=biat,dc=local` | DN de base de l'annuaire |
| `LDAP_USERS_OU` | `ou=users,dc=biat,dc=local` | OU des utilisateurs |
| `LDAP_GROUPS_OU` | `ou=groups,dc=biat,dc=local` | OU des groupes |
| `LDAP_BIND_DN` | `cn=admin,dc=biat,dc=local` | Compte de service (recherches) |
| `LDAP_BIND_PASSWORD` | `admin_secret` | Mot de passe du compte de service |
| `LDAP_SEARCH_ATTR` | `mail` | Attribut de recherche (`mail` ou `uid`) |
| `LDAP_TIMEOUT` | `5` | Délai de connexion (secondes) |
| `LDAP_DEFAULT_ROLE` | _(vide)_ | Rôle par défaut si aucun groupe ne correspond (vide = refus) |
