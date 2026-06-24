"""JWT authentication utilities for the BIAT IT Billing API (local demo)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

SECRET = "biat_local_only_secret_2026"
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 8

# Hardcoded demo users — role is embedded in the JWT claim
USERS: dict[str, dict[str, str]] = {
    "comptable@biat-it.tn":  {"password": "biat2026", "role": "Comptable"},
    "chef@biat-it.tn":       {"password": "biat2026", "role": "Chef de Projet"},
    "directeur@biat-it.tn":  {"password": "biat2026", "role": "Direction"},
}

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def create_token(role: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS)
    return jwt.encode({"role": role, "exp": exp}, SECRET, algorithm=ALGORITHM)


def _decode(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expiré — reconnectez-vous.")
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalide.")


def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """FastAPI dependency — injects {role} or raises 401."""
    return _decode(token)
