"""JWT authentication utilities + role guard for BIAT IT Billing API."""
from __future__ import annotations

import os
import secrets
import string
from pathlib import Path

import bcrypt

# Load .env file if present (dev convenience — production uses real env vars)
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            # Strip inline comments (e.g. KEY=value  # comment → value)
            _v = _v.split("#")[0].strip()
            os.environ.setdefault(_k.strip(), _v)

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from api.security.jwt_handler import (
    SECRET,
    create_access_token,
    create_refresh_token,
    create_token,        # legacy shim
    decode_any,
    verify_access_token,
)

# ── Demo fallback users ────────────────────────────────────────────────────────
# Passwords MUST be set via env vars — no hardcoded defaults.
# Use DISABLE_DEMO_USERS=true to skip entirely in production.
USERS: dict[str, dict[str, str]] = {
    "comptable@biat-it.tn": {
        "password": os.getenv("DEMO_COMPTABLE_PASSWORD", ""),
        "role": "Comptable",
    },
    "chef@biat-it.tn": {
        "password": os.getenv("DEMO_CHEF_PASSWORD", ""),
        "role": "Chef de Projet",
    },
    "directeur@biat-it.tn": {
        "password": os.getenv("DEMO_DIRECTION_PASSWORD", ""),
        "role": "Direction",
    },
    "admin@biat-it.tn": {
        "password": os.getenv("DEMO_ADMIN_PASSWORD", ""),
        "role": "Admin",
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


# ── FastAPI dependencies ───────────────────────────────────────────────────────

def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """FastAPI dependency — returns the full JWT payload dict."""
    return decode_any(token)


def require_role(*roles: str):
    """Dependency factory — raises 403 if the caller's role is not in `roles`."""
    def checker(user: dict = Depends(get_current_user)) -> dict:
        if user.get("role") not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès refusé.")
        return user
    return checker


def validate_demo_users() -> None:
    """Called at startup — warns/raises if demo env vars are missing."""
    disable = os.getenv("DISABLE_DEMO_USERS", "false").lower() == "true"
    if disable:
        return

    missing = []
    weak = []
    env_map = {
        "DEMO_COMPTABLE_PASSWORD": USERS["comptable@biat-it.tn"]["password"],
        "DEMO_CHEF_PASSWORD": USERS["chef@biat-it.tn"]["password"],
        "DEMO_DIRECTION_PASSWORD": USERS["directeur@biat-it.tn"]["password"],
        "DEMO_ADMIN_PASSWORD": USERS["admin@biat-it.tn"]["password"],
    }
    for var, val in env_map.items():
        if not val:
            missing.append(var)
        elif len(val) < 8:
            weak.append(var)

    if missing:
        import logging
        logging.getLogger(__name__).warning(
            "⚠️  Variables d'environnement demo manquantes: %s. "
            "Définissez-les dans .env ou mettez DISABLE_DEMO_USERS=true.",
            ", ".join(missing),
        )

    if weak:
        import logging
        logging.getLogger(__name__).warning(
            "⚠️  Mots de passe faibles pour les comptes démo: %s (minimum 8 caractères recommandé).",
            ", ".join(weak),
        )
