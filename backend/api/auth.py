"""JWT authentication utilities + role guard for BIAT IT Billing API."""
from __future__ import annotations

import secrets
import string
from pathlib import Path

import bcrypt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from dotenv import load_dotenv

# Load .env files before importing modules that read secrets at import time.
# External environment variables keep priority; repo-root .env is the canonical
# local file, and backend/.env remains supported as a fallback.
_ROOT_DIR = Path(__file__).resolve().parents[2]
_BACKEND_DIR = Path(__file__).resolve().parents[1]
for _env_path in (_ROOT_DIR / ".env", _BACKEND_DIR / ".env"):
    if _env_path.exists():
        load_dotenv(_env_path, override=False)

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from api.security.jwt_handler import (
    verify_access_token,
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


# ── Password helpers ──────────────────────────────────────────────────────────

_PH = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)

_BCRYPT_PREFIXES = ("$2b$", "$2a$", "$2y$")


def hash_password(password: str) -> str:
    """Hash with argon2id. All new hashes use this algorithm."""
    return _PH.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    """Verify password against argon2id or legacy bcrypt hash."""
    if hashed.startswith(_BCRYPT_PREFIXES):
        try:
            return bcrypt.checkpw(password.encode(), hashed.encode())
        except Exception:
            return False
    try:
        return _PH.verify(hashed, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(hashed: str) -> bool:
    """True if the hash must be upgraded (bcrypt → argon2id, or outdated argon2id params)."""
    if hashed.startswith(_BCRYPT_PREFIXES):
        return True
    try:
        return _PH.check_needs_rehash(hashed)
    except InvalidHashError:
        return False


def generate_temp_password(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#%"
    return "".join(secrets.choice(alphabet) for _ in range(length))


# ── FastAPI dependencies ───────────────────────────────────────────────────────

async def get_current_user(
    token: str = Depends(oauth2_scheme),
) -> dict:
    """FastAPI dependency — vérifie signature, expiration ET révocation (après logout)."""
    payload = await verify_access_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalide ou révoqué — reconnectez-vous.",
        )
    return payload


def require_role(*roles: str):
    """Dependency factory — raises 403 if the caller's role is not in `roles`."""
    def checker(user: dict = Depends(get_current_user)) -> dict:
        if user.get("role") not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès refusé.")
        return user
    return checker
