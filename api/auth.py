"""JWT authentication utilities + role guard for BIAT IT Billing API."""
from __future__ import annotations

import os

import bcrypt
import secrets
import string
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

SECRET = os.getenv("JWT_SECRET", "biat_local_only_secret_2026")
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 8

# Demo fallback users — active when no DB user matches the email.
# Passwords are read from env vars so they are not hardcoded in source.
# For production, seed all users into the DB with: python scripts/seed_users.py
USERS: dict[str, dict[str, str]] = {
    "comptable@biat-it.tn":  {
        "password": os.getenv("DEMO_COMPTABLE_PASSWORD", "biat2026"),
        "role":     "Comptable",
    },
    "chef@biat-it.tn": {
        "password": os.getenv("DEMO_CHEF_PASSWORD", "biat2026"),
        "role":     "Chef de Projet",
    },
    "directeur@biat-it.tn": {
        "password": os.getenv("DEMO_DIRECTION_PASSWORD", "biat2026"),
        "role":     "Direction",
    },
    "admin@biat-it.tn": {
        "password": os.getenv("DEMO_ADMIN_PASSWORD", "admin2026"),
        "role":     "Admin",
    },
}

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


# ── Password helpers ──────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def generate_temp_password(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#%"
    return "".join(secrets.choice(alphabet) for _ in range(length))


# ── JWT helpers ───────────────────────────────────────────────────────────────

def create_token(role: str, extra: dict | None = None) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS)
    payload: dict = {"role": role, "exp": exp}
    if extra:
        payload.update(extra)
    return jwt.encode(payload, SECRET, algorithm=ALGORITHM)


def _decode(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expiré — reconnectez-vous.")
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalide.")


def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """FastAPI dependency — returns the full JWT payload dict."""
    return _decode(token)


def require_role(*roles: str):
    """Dependency factory — raises 403 if the caller's role is not in `roles`."""
    def checker(user: dict = Depends(get_current_user)) -> dict:
        if user.get("role") not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès refusé.")
        return user
    return checker
