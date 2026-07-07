"""JWT generation and verification — access + refresh token pair."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import jwt
from fastapi import HTTPException, status
from dotenv import load_dotenv
from sqlalchemy.orm import Session

_ROOT_DIR = Path(__file__).resolve().parents[3]
_BACKEND_DIR = Path(__file__).resolve().parents[2]
for _env_path in (_ROOT_DIR / ".env", _BACKEND_DIR / ".env"):
    if _env_path.exists():
        load_dotenv(_env_path, override=False)


SECRET = os.getenv("JWT_SECRET", "biat_local_only_secret_2026")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_HOURS", "8"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("JWT_REFRESH_TOKEN_EXPIRE_DAYS", "7"))


def _validate_secret() -> None:
    if len(SECRET) < 32:
        raise RuntimeError(
            f"JWT_SECRET trop court ({len(SECRET)} chars — minimum 32). "
            "Définissez JWT_SECRET dans .env avant de démarrer."
        )


def create_access_token(user_id: str, role: str, email: str, extra: dict | None = None) -> str:
    now = datetime.now(timezone.utc)
    payload: dict = {
        "sub": user_id,
        "role": role,
        "email": email,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS),
        "jti": str(uuid4()),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, SECRET, algorithm=ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "type": "refresh",
        "iat": now,
        "exp": now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        "jti": str(uuid4()),
    }
    return jwt.encode(payload, SECRET, algorithm=ALGORITHM)


def decode_token_raw(token: str) -> dict | None:
    """Decode without revocation check — used internally."""
    try:
        return jwt.decode(token, SECRET, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None


def verify_access_token(token: str, db: Session | None = None) -> dict | None:
    payload = decode_token_raw(token)
    if not payload:
        return None
    if payload.get("type") != "access":
        return None
    if db is not None:
        jti = payload.get("jti")
        if jti and _is_token_revoked(jti, db):
            return None
    return payload


def verify_refresh_token(token: str, db: Session | None = None) -> dict | None:
    payload = decode_token_raw(token)
    if not payload:
        return None
    if payload.get("type") != "refresh":
        return None
    if db is not None:
        jti = payload.get("jti")
        if jti and _is_token_revoked(jti, db):
            return None
    return payload


def _is_token_revoked(jti: str, db: Session) -> bool:
    from src.storage.orm_models_auth import RevokedTokenORM
    return db.get(RevokedTokenORM, jti) is not None


def revoke_token(jti: str, reason: str, user_id: str | None, db: Session) -> None:
    from src.storage.orm_models_auth import RevokedTokenORM
    existing = db.get(RevokedTokenORM, jti)
    if not existing:
        db.add(RevokedTokenORM(
            jti=jti,
            revoked_at=datetime.now(timezone.utc),
            reason=reason,
            user_id=user_id,
        ))


# Legacy compatibility — wraps create_access_token for old callers
def create_token(role: str, extra: dict | None = None) -> str:
    """Legacy shim used by demo-user login path."""
    user_id = (extra or {}).get("user_id", "demo")
    email = (extra or {}).get("email", "")
    token_extra = {k: v for k, v in (extra or {}).items() if k not in ("user_id", "email", "role")}
    return create_access_token(user_id=str(user_id), role=role, email=str(email), extra=token_extra or None)


def decode_any(token: str) -> dict:
    """Decode and raise HTTPException on failure (FastAPI dependency use)."""
    try:
        return jwt.decode(token, SECRET, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Token expiré — reconnectez-vous.")
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Token invalide.")
