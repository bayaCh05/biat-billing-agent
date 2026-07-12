"""Authentication endpoints — login, refresh, logout, OTP, password reset."""
from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.auth import DEMO_AUTH_STATE, USERS, get_current_user, hash_password, needs_rehash, verify_password
from api.deps import get_session
from api.limiter import limiter, limit
from api.security import jwt_handler, account_lockout
from src.models.audit import AuditLogCreate
from src.services.audit_service import _ip, _ua

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# ── Mode d'authentification ───────────────────────────────────────────────────
# AUTH_MODE=local   → authentification locale uniquement (comportement par défaut)
# AUTH_MODE=ldap    → LDAP uniquement pour tous les utilisateurs
# AUTH_MODE=hybrid  → LDAP pour les emails @<LDAP_USER_DOMAIN>, local pour les autres
_AUTH_MODE       = os.getenv("AUTH_MODE", "local").lower()
_LDAP_USER_DOMAIN = os.getenv("LDAP_USER_DOMAIN", "biat.local")


def _validate_password_strength(password: str) -> None:
    """Lève HTTP 422 si le mot de passe ne respecte pas la politique de sécurité.

    Règles : min 8 caractères, au moins 1 majuscule, 1 chiffre, 1 caractère spécial.
    """
    import re
    if len(password) < 8:
        raise HTTPException(422, "Le mot de passe doit contenir au moins 8 caractères.")
    if not re.search(r"[A-Z]", password):
        raise HTTPException(422, "Le mot de passe doit contenir au moins une lettre majuscule.")
    if not re.search(r"\d", password):
        raise HTTPException(422, "Le mot de passe doit contenir au moins un chiffre.")
    if not re.search(r"[^A-Za-z0-9]", password):
        raise HTTPException(422, "Le mot de passe doit contenir au moins un caractère spécial.")


def _should_use_ldap(email: str) -> bool:
    if _AUTH_MODE == "local":
        return False
    if _AUTH_MODE == "ldap":
        return True
    # hybrid : seulement pour le domaine LDAP configuré
    return email.endswith(f"@{_LDAP_USER_DOMAIN}")

_REFRESH_COOKIE = "biat_refresh"
_REFRESH_DAYS = int(os.getenv("JWT_REFRESH_TOKEN_EXPIRE_DAYS", "7"))


# ── Request / response schemas ────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    user_id: str
    force_password_change: bool = False
    is_first_login: bool = False
    expires_in: int = jwt_handler.ACCESS_TOKEN_EXPIRE_HOURS * 3600


class RefreshResponse(BaseModel):
    access_token: str
    expires_in: int = jwt_handler.ACCESS_TOKEN_EXPIRE_HOURS * 3600


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str



class ConfirmOtpRequest(BaseModel):
    otp_code: str | None = None   # optional: skipped for demo accounts
    new_password: str
    current_password: str | None = None


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class RevokeSessionRequest(BaseModel):
    jti_prefix: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_demo_account(user_id: str, email: str) -> bool:
    """True for demo/test accounts that cannot receive real emails."""
    return user_id.startswith("demo:") or "biat-it.tn" in email


def _mask_email(email: str) -> str:
    try:
        local, domain = email.split("@", 1)
        if len(local) <= 2:
            return f"{local[0]}***@{domain}"
        return f"{local[0]}***{local[-1]}@{domain}"
    except Exception:
        return "***@***"


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    response.set_cookie(
        key=_REFRESH_COOKIE,
        value=refresh_token,
        httponly=True,
        secure=os.getenv("COOKIE_SECURE", "false").lower() == "true",
        samesite="lax",
        max_age=_REFRESH_DAYS * 86400,
        path="/api/auth",
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Connexion utilisateur",
    description=(
        "Authentification par email et mot de passe. "
        "Retourne un access_token JWT (8h) et pose un refresh_token httpOnly cookie (7j). "
        "Verrouillage après 5 tentatives échouées (15 min). "
        "Limité à 5 tentatives par minute par IP."
    ),
    responses={
        401: {"description": "Email ou mot de passe incorrect"},
        423: {"description": "Compte verrouillé"},
    },
)
@limiter.limit(limit("5/minute"))
async def login(
    request: Request,
    response: Response,
    body: LoginRequest,
) -> LoginResponse:
    from src.storage.documents.service_bridge import (
        check_locked_native, create_user_native, get_user_by_email_native,
        log_audit_event_native, record_login_failure_native, record_login_success_native,
        register_active_token_native, update_user_password_native, update_user_role_native,
    )

    email = body.email.lower().strip()
    ip = _ip(request)
    ua = _ua(request)

    # ── Authentification LDAP (si AUTH_MODE=ldap|hybrid) ──────────────────────
    if _should_use_ldap(email):
        from src.services.ldap_service import authenticate_ldap

        ldap_result = authenticate_ldap(email, body.password)
        if ldap_result is None:
            await log_audit_event_native(AuditLogCreate(
                user_email=email, action="LOGIN_FAILURE", resource_type="User",
                status="FAILURE", detail=f"Échec LDAP depuis {ip}",
                ip_address=ip, user_agent=ua,
            ))
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Email ou mot de passe incorrect.")

        role = ldap_result.get("role") or "Comptable"

        # Provisioning automatique : crée le compte local si inexistant
        db_user = await get_user_by_email_native(email)

        if db_user is None:
            db_user = await create_user_native(
                nom=ldap_result.get("sn") or email.split("@")[0].capitalize(),
                prenom=ldap_result.get("givenName") or "LDAP",
                email=email,
                # Mot de passe aléatoire — l'utilisateur s'authentifie toujours via LDAP
                hashed_password=hash_password(secrets.token_hex(32)),
                role=role,
                departement="IT",
            )
            if db_user is None:  # créé entre-temps par une requête concurrente
                db_user = await get_user_by_email_native(email)
            _log.info("Compte provisionné depuis LDAP : %s (%s)", email, role)
        else:
            if not db_user.is_active:
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Compte désactivé.")
            # Le rôle LDAP fait autorité — mise à jour si nécessaire
            if role and db_user.role != role:
                await update_user_role_native(str(db_user.id), role)
                db_user.role = role

        await record_login_success_native(str(db_user.id), ip)

        access_token = jwt_handler.create_access_token(
            user_id=str(db_user.id),
            role=db_user.role,
            email=db_user.email,
            extra={
                "nom": db_user.nom,
                "prenom": db_user.prenom,
                "departement": db_user.departement,
                "force_password_change": False,
                "auth_method": "ldap",
            },
        )
        refresh_token = jwt_handler.create_refresh_token(user_id=str(db_user.id))

        acc_payload = jwt_handler.decode_token_raw(access_token) or {}
        expires_at = datetime.now(timezone.utc) + timedelta(hours=jwt_handler.ACCESS_TOKEN_EXPIRE_HOURS)
        await register_active_token_native(acc_payload.get("jti", ""), str(db_user.id), expires_at, ip, ua)

        await log_audit_event_native(AuditLogCreate(
            user_id=str(db_user.id), user_email=db_user.email, user_role=db_user.role,
            action="LOGIN_SUCCESS", resource_type="User", resource_id=str(db_user.id),
            status="SUCCESS", detail=f"Connexion LDAP depuis {ip}",
            ip_address=ip, user_agent=ua,
        ))
        _set_refresh_cookie(response, refresh_token)

        return LoginResponse(
            access_token=access_token,
            role=db_user.role,
            user_id=str(db_user.id),
            force_password_change=False,
            is_first_login=False,
        )

    # ── Authentification locale ────────────────────────────────────────────────
    db_user = await get_user_by_email_native(email)

    if db_user:
        # Check account status
        if not db_user.is_active:
            await log_audit_event_native(AuditLogCreate(
                user_email=email, action="LOGIN_FAILURE", resource_type="User",
                resource_id=str(db_user.id), status="FAILURE",
                detail="Compte désactivé", ip_address=ip, user_agent=ua,
            ))
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Compte désactivé.")

        # Check lockout
        locked, remaining = check_locked_native(db_user)
        if locked:
            await log_audit_event_native(AuditLogCreate(
                user_id=str(db_user.id), user_email=email, action="LOGIN_FAILURE",
                resource_type="User", resource_id=str(db_user.id), status="FAILURE",
                detail=f"Compte verrouillé — {remaining} min restantes", ip_address=ip, user_agent=ua,
            ))
            raise HTTPException(
                status.HTTP_423_LOCKED,
                detail=f"Compte verrouillé. Réessayez dans {remaining} minute(s).",
            )

        # Verify password
        if not verify_password(body.password, db_user.hashed_password):
            attempts = await record_login_failure_native(db_user)
            remaining_attempts = max(0, account_lockout.MAX_ATTEMPTS - attempts)
            await log_audit_event_native(AuditLogCreate(
                user_id=str(db_user.id), user_email=email, action="LOGIN_FAILURE",
                resource_type="User", resource_id=str(db_user.id), status="FAILURE",
                detail=f"Tentative #{attempts} depuis {ip}", ip_address=ip, user_agent=ua,
            ))
            detail = "Email ou mot de passe incorrect."
            if remaining_attempts == 0:
                detail = f"Compte verrouillé après {account_lockout.MAX_ATTEMPTS} tentatives. Réessayez dans {account_lockout.LOCKOUT_MINUTES} min."
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=detail)

        # Success
        await record_login_success_native(str(db_user.id), ip)

        # Lazy migration bcrypt → argon2id (transparent to the user)
        if needs_rehash(db_user.hashed_password):
            await update_user_password_native(str(db_user.id), hash_password(body.password), db_user.is_first_login)
            _log.info("Password rehashed to argon2id for user %s", email)

        access_token = jwt_handler.create_access_token(
            user_id=str(db_user.id),
            role=db_user.role,
            email=db_user.email,
            extra={
                "nom": db_user.nom,
                "prenom": db_user.prenom,
                "departement": db_user.departement,
                "force_password_change": db_user.is_first_login,
            },
        )
        refresh_token = jwt_handler.create_refresh_token(user_id=str(db_user.id))

        # Decode jti for tracking
        acc_payload = jwt_handler.decode_token_raw(access_token) or {}
        expires_at = datetime.now(timezone.utc) + timedelta(hours=jwt_handler.ACCESS_TOKEN_EXPIRE_HOURS)
        await register_active_token_native(acc_payload.get("jti", ""), str(db_user.id), expires_at, ip, ua)

        await log_audit_event_native(AuditLogCreate(
            user_id=str(db_user.id), user_email=db_user.email, user_role=db_user.role,
            action="LOGIN_SUCCESS", resource_type="User", resource_id=str(db_user.id),
            status="SUCCESS", detail=f"Connexion depuis {ip}", ip_address=ip, user_agent=ua,
        ))
        _set_refresh_cookie(response, refresh_token)

        return LoginResponse(
            access_token=access_token,
            role=db_user.role,
            user_id=str(db_user.id),
            force_password_change=db_user.is_first_login,
            is_first_login=db_user.is_first_login,
        )

    # Demo user path
    demo = USERS.get(email)
    if demo and demo.get("password") and secrets.compare_digest(demo["password"], body.password):
        access_token = jwt_handler.create_access_token(
            user_id=f"demo:{email}",
            role=demo["role"],
            email=email,
        )
        refresh_token = jwt_handler.create_refresh_token(user_id=f"demo:{email}")
        await log_audit_event_native(AuditLogCreate(
            user_email=email, user_role=demo["role"],
            action="LOGIN_SUCCESS", resource_type="User", status="SUCCESS",
            detail=f"Compte démo depuis {ip}", ip_address=ip, user_agent=ua,
        ))
        _set_refresh_cookie(response, refresh_token)
        return LoginResponse(
            access_token=access_token,
            role=demo["role"],
            user_id=f"demo:{email}",
            force_password_change=DEMO_AUTH_STATE.get(email, {}).get("is_first_login", False),
            is_first_login=DEMO_AUTH_STATE.get(email, {}).get("is_first_login", False),
        )

    await log_audit_event_native(AuditLogCreate(
        user_email=email, action="LOGIN_FAILURE", resource_type="User",
        status="FAILURE", detail=f"Utilisateur inconnu depuis {ip}", ip_address=ip, user_agent=ua,
    ))
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Email ou mot de passe incorrect.")


@router.post(
    "/refresh",
    response_model=RefreshResponse,
    summary="Renouveler le token d'accès",
    description="Émet un nouveau access_token à partir du refresh_token (cookie httpOnly ou corps).",
)
@limiter.limit(limit("10/minute"))
async def refresh_token(
    request: Request,
    response: Response,
    cookie_refresh: str | None = Cookie(default=None, alias=_REFRESH_COOKIE),
):
    # Accept refresh token from cookie OR from JSON body
    body_token: str | None = None
    try:
        data = request.scope.get("_body_cache")
        if data is None:
            body_bytes = await request.body()
            request.scope["_body_cache"] = body_bytes
            data = body_bytes
        if data:
            import json
            body_token = json.loads(data).get("refresh_token")
    except Exception:
        pass

    token = cookie_refresh or body_token
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Refresh token manquant.")

    payload = await jwt_handler.verify_refresh_token(token)
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Refresh token invalide ou expiré.")

    user_id = payload.get("sub", "")

    # Look up DB user for fresh role/email
    role = "Comptable"
    email = ""
    extra: dict = {}
    try:
        from src.storage.documents.service_bridge import get_user_by_id_native
        from uuid import UUID
        UUID(user_id)  # valide le format — lève ValueError pour les comptes démo
        db_user = await get_user_by_id_native(user_id)
        if db_user and db_user.is_active:
            role = db_user.role
            email = db_user.email
            extra = {"nom": db_user.nom, "prenom": db_user.prenom, "departement": db_user.departement}
    except Exception:
        # demo user or UUID parse error — best-effort
        pass

    new_access = jwt_handler.create_access_token(user_id=user_id, role=role, email=email, extra=extra or None)

    acc_payload = jwt_handler.decode_token_raw(new_access) or {}
    expires_at = datetime.now(timezone.utc) + timedelta(hours=jwt_handler.ACCESS_TOKEN_EXPIRE_HOURS)
    ip = _ip(request)
    ua = _ua(request)
    from src.storage.documents.service_bridge import log_audit_event_native, register_active_token_native
    await register_active_token_native(acc_payload.get("jti", ""), user_id, expires_at, ip, ua)

    await log_audit_event_native(AuditLogCreate(
        user_id=user_id, action="TOKEN_REFRESHED", resource_type="User",
        status="SUCCESS", detail=f"Token renouvelé depuis {ip}", ip_address=ip, user_agent=ua,
    ))
    return RefreshResponse(access_token=new_access)


@router.post(
    "/logout",
    summary="Déconnexion",
    description="Révoque l'access_token courant et le refresh_token cookie.",
)
async def logout(
    request: Request,
    response: Response,
    current_user: dict = Depends(get_current_user),
    cookie_refresh: str | None = Cookie(default=None, alias=_REFRESH_COOKIE),
):
    from src.storage.documents.service_bridge import log_audit_event_native, revoke_active_token_native

    ip = _ip(request)
    ua = _ua(request)
    user_id = current_user.get("sub")

    # Revoke access token
    jti = current_user.get("jti")
    if jti:
        await jwt_handler.revoke_token(jti, "logout", user_id)
        await revoke_active_token_native(jti)

    # Revoke refresh token cookie
    if cookie_refresh:
        ref_payload = await jwt_handler.verify_refresh_token(cookie_refresh)
        if ref_payload:
            await jwt_handler.revoke_token(ref_payload["jti"], "logout", user_id)

    await log_audit_event_native(AuditLogCreate(
        user_id=user_id, user_email=current_user.get("email"),
        user_role=current_user.get("role"),
        action="LOGOUT", resource_type="User", resource_id=user_id,
        status="SUCCESS", detail=f"Déconnexion depuis {ip}", ip_address=ip, user_agent=ua,
    ))

    # Clear cookie
    response.delete_cookie(_REFRESH_COOKIE, path="/api/auth")
    return {"message": "Déconnexion réussie."}


@router.get(
    "/sessions",
    summary="Sessions actives",
    description="Retourne les tokens actifs de l'utilisateur courant.",
)
async def list_sessions(
    current_user: dict = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    from src.storage.documents.service_bridge import list_active_sessions_mongo

    user_id = str(current_user.get("sub", ""))
    current_jti = current_user.get("jti", "")

    mongo_rows = await list_active_sessions_mongo(user_id)
    if mongo_rows is not None:
        rows = mongo_rows
    else:
        from src.storage.orm_models_auth import ActiveTokenORM
        from sqlalchemy import select as sa_select

        now = datetime.now(timezone.utc)
        rows = session.execute(
            sa_select(ActiveTokenORM).where(
                ActiveTokenORM.user_id == user_id,
                ActiveTokenORM.revoked == False,  # noqa: E712
                ActiveTokenORM.expires_at > now,
            ).order_by(ActiveTokenORM.created_at.desc())
        ).scalars().all()

    def _jti(r) -> str:
        # ActiveTokenORM.jti (SQLAlchemy) vs ActiveTokenDocument.id (Beanie).
        return r.jti if hasattr(r, "jti") else r.id

    return {
        "sessions": [
            {
                "jti": _jti(r)[:8],
                "created_at": r.created_at.isoformat(),
                "expires_at": r.expires_at.isoformat(),
                "ip_address": r.ip_address,
                "is_current": _jti(r) == current_jti,
            }
            for r in rows
        ]
    }


@router.post(
    "/revoke-session",
    summary="Révoquer une session",
    description="Révoque un token actif par préfixe JTI (8 premiers caractères).",
)
async def revoke_session(
    request: Request,
    body: RevokeSessionRequest,
    current_user: dict = Depends(get_current_user),
):
    from src.storage.documents.service_bridge import (
        log_audit_event_native, revoke_active_tokens_by_prefix_native,
    )

    jti_prefix = body.jti_prefix.strip()
    if len(jti_prefix) < 8:
        raise HTTPException(400, "jti_prefix doit faire au moins 8 caractères.")

    user_id = str(current_user.get("sub", ""))
    is_admin = current_user.get("role") == "Admin"

    revoked_count = await revoke_active_tokens_by_prefix_native(jti_prefix, user_id, is_admin)

    await log_audit_event_native(AuditLogCreate(
        user_id=user_id, action="SESSION_REVOKED", resource_type="User",
        status="SUCCESS", detail=f"{revoked_count} session(s) révoquée(s) — prefix {jti_prefix}",
        ip_address=_ip(request), user_agent=_ua(request),
    ))
    return {"revoked": revoked_count}


# ── Password management (unchanged from original) ─────────────────────────────

@router.patch(
    "/change-password",
    summary="Changer le mot de passe (direct — sans OTP)",
)
@limiter.limit(limit("3/minute"))
async def change_password(
    request: Request,
    body: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
):
    from src.storage.documents.service_bridge import (
        get_user_by_email_native, log_audit_event_native,
        revoke_all_user_tokens_native, update_user_password_native,
    )

    email = current_user.get("email")
    if not email:
        raise HTTPException(400, "Changement de mot de passe non disponible pour les comptes de démonstration.")
    _validate_password_strength(body.new_password)

    user = await get_user_by_email_native(email)
    if user:
        if not verify_password(body.current_password, user.hashed_password):
            raise HTTPException(400, "Mot de passe actuel incorrect.")

        await update_user_password_native(str(user.id), hash_password(body.new_password), is_first_login=False)

        # Revoke every OTHER active session so a token stolen before this
        # change can't survive it — the session making this change stays
        # logged in (the user just proved their identity with current_password).
        jti = current_user.get("jti")
        revoked_count = await revoke_all_user_tokens_native(
            str(user.id), except_jti=jti, reason="password_change",
        )

        await log_audit_event_native(AuditLogCreate(
            user_id=str(user.id), user_email=user.email, user_role=user.role,
            action="PASSWORD_CHANGED", resource_type="User", resource_id=str(user.id),
            status="SUCCESS",
            detail=f"Mot de passe changé (direct) — {revoked_count} autre(s) session(s) révoquée(s)",
            ip_address=_ip(request), user_agent=_ua(request),
        ))
        return {"message": "Mot de passe modifié avec succès."}

    if email in USERS:
        if not secrets.compare_digest(body.current_password, USERS[email]["password"]):
            raise HTTPException(400, "Mot de passe actuel incorrect.")
        USERS[email]["password"] = body.new_password
        DEMO_AUTH_STATE.setdefault(email, {})["is_first_login"] = False
        await log_audit_event_native(AuditLogCreate(
            user_email=email, user_role=USERS[email]["role"],
            action="PASSWORD_CHANGED", resource_type="User", resource_id=email,
            status="SUCCESS", detail="Mot de passe démo changé (direct)",
            ip_address=_ip(request), user_agent=_ua(request),
        ))
        return {"message": "Mot de passe modifié avec succès."}

    raise HTTPException(404, "Utilisateur non trouvé.")


@router.post("/change-password/request-otp", summary="Demander un OTP")
@limiter.limit(limit("3/minute"))
async def request_otp(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Generate and email a 6-digit OTP. Demo accounts skip email entirely."""
    from src.storage.documents.service_bridge import (
        generate_otp_native, get_user_by_email_native, log_audit_event_native,
    )

    email = current_user.get("email")
    if not email:
        raise HTTPException(400, "Non disponible pour les comptes de démonstration.")

    user_id = current_user.get("sub", "")

    # Demo accounts cannot receive real emails — skip OTP entirely
    if _is_demo_account(user_id, email):
        await log_audit_event_native(AuditLogCreate(
            user_email=email, action="OTP_REQUESTED", resource_type="User",
            status="SUCCESS", detail="OTP ignoré — compte de démonstration",
            ip_address=_ip(request), user_agent=_ua(request),
        ))
        return {
            "skip_otp": True,
            "message": "Compte de démonstration — vérification email ignorée.",
            "masked_email": _mask_email(email),
        }

    user = await get_user_by_email_native(email)
    if user:
        purpose = "FIRST_LOGIN" if user.is_first_login else "VOLUNTARY_CHANGE"
        await generate_otp_native(user, purpose)
        await log_audit_event_native(AuditLogCreate(
            user_id=str(user.id), user_email=user.email, user_role=user.role,
            action="OTP_REQUESTED", resource_type="User", resource_id=str(user.id),
            status="SUCCESS", detail=f"OTP demandé (purpose={purpose})",
            ip_address=_ip(request), user_agent=_ua(request),
        ))
        return {
            "skip_otp": False,
            "message": "Code de vérification envoyé par email.",
            "masked_email": _mask_email(email),
        }

    raise HTTPException(404, "Utilisateur non trouvé.")


@router.post("/change-password/confirm", summary="Confirmer changement via OTP")
@limiter.limit(limit("5/minute"))
async def confirm_otp(
    request: Request,
    body: ConfirmOtpRequest,
    current_user: dict = Depends(get_current_user),
):
    from src.storage.documents.service_bridge import (
        get_user_by_email_native, log_audit_event_native,
        revoke_all_user_tokens_native, update_user_password_native, verify_otp_native,
    )

    email = current_user.get("email")
    if not email:
        raise HTTPException(400, "Non disponible pour les comptes de démonstration.")
    _validate_password_strength(body.new_password)

    user_id = current_user.get("sub", "")

    # Demo accounts: skip OTP — just update the password directly
    if _is_demo_account(user_id, email):
        user = await get_user_by_email_native(email)
        if user:
            await update_user_password_native(str(user.id), hash_password(body.new_password), is_first_login=False)
            revoked_count = await revoke_all_user_tokens_native(
                str(user.id), except_jti=current_user.get("jti"), reason="password_change_otp",
            )
            await log_audit_event_native(AuditLogCreate(
                user_id=str(user.id), user_email=user.email, user_role=user.role,
                action="PASSWORD_CHANGED", resource_type="User", resource_id=str(user.id),
                status="SUCCESS",
                detail=f"Mot de passe changé (compte démo — sans OTP) — {revoked_count} autre(s) session(s) révoquée(s)",
                ip_address=_ip(request), user_agent=_ua(request),
            ))
            return {"success": True, "message": "Mot de passe modifié avec succès."}
        if email in USERS:
            USERS[email]["password"] = body.new_password
            DEMO_AUTH_STATE.setdefault(email, {})["is_first_login"] = False
            await log_audit_event_native(AuditLogCreate(
                user_email=email, user_role=USERS[email].get("role", ""),
                action="PASSWORD_CHANGED", resource_type="User", resource_id=email,
                status="SUCCESS", detail="Mot de passe démo changé (sans OTP)",
                ip_address=_ip(request), user_agent=_ua(request),
            ))
            return {"success": True, "message": "Mot de passe modifié avec succès."}
        raise HTTPException(404, "Utilisateur non trouvé.")

    # Real users: verify OTP
    user = await get_user_by_email_native(email)
    if user:
        if body.current_password and not verify_password(body.current_password, user.hashed_password):
            await log_audit_event_native(AuditLogCreate(
                user_id=str(user.id), user_email=user.email, user_role=user.role,
                action="OTP_VERIFIED", resource_type="User", resource_id=str(user.id),
                status="FAILURE", detail="Mot de passe actuel incorrect",
                ip_address=_ip(request), user_agent=_ua(request),
            ))
            raise HTTPException(400, "Mot de passe actuel incorrect.")

        if not body.otp_code:
            raise HTTPException(400, "Code OTP requis pour les comptes réels.")

        valid = await verify_otp_native(str(user.id), body.otp_code)
        if not valid:
            await log_audit_event_native(AuditLogCreate(
                user_id=str(user.id), user_email=user.email, user_role=user.role,
                action="OTP_VERIFIED", resource_type="User", resource_id=str(user.id),
                status="FAILURE", detail="Code OTP invalide ou expiré",
                ip_address=_ip(request), user_agent=_ua(request),
            ))
            raise HTTPException(400, "Code incorrect ou expiré. Demandez un nouveau code.")

        await update_user_password_native(str(user.id), hash_password(body.new_password), is_first_login=False)

        # Same policy as the direct change-password path: revoke every OTHER
        # active session (current one — the one that just completed OTP — stays
        # logged in), so a token stolen before this change can't survive it.
        current_jti = current_user.get("jti")
        revoked_count = await revoke_all_user_tokens_native(
            str(user.id), except_jti=current_jti, reason="password_change_otp",
        )

        await log_audit_event_native(AuditLogCreate(
            user_id=str(user.id), user_email=user.email, user_role=user.role,
            action="PASSWORD_CHANGED", resource_type="User", resource_id=str(user.id),
            status="SUCCESS",
            detail=f"Mot de passe changé via OTP — {revoked_count} autre(s) session(s) révoquée(s)",
            ip_address=_ip(request), user_agent=_ua(request),
        ))
        return {"success": True, "message": "Mot de passe modifié avec succès."}

    raise HTTPException(404, "Utilisateur non trouvé.")


@router.post("/forgot-password", summary="Demander un lien de réinitialisation")
@limiter.limit(limit("3/minute"))
async def forgot_password(
    request: Request,
    body: ForgotPasswordRequest,
):
    from src.services.password_verification_service import generate_demo_reset_link
    from src.storage.documents.service_bridge import (
        generate_reset_link_native, get_user_by_email_native, log_audit_event_native,
    )

    email = body.email.lower().strip()
    user = await get_user_by_email_native(email)

    if user and user.is_active:
        await generate_reset_link_native(user, "FORGOT_PASSWORD")
        await log_audit_event_native(AuditLogCreate(
            user_id=str(user.id), user_email=user.email, user_role=user.role,
            action="PASSWORD_RESET_REQUESTED", resource_type="User", resource_id=str(user.id),
            status="SUCCESS", detail="Lien de réinitialisation envoyé",
            ip_address=_ip(request), user_agent=_ua(request),
        ))
    elif email in USERS:
        generate_demo_reset_link(email, "FORGOT_PASSWORD")
        await log_audit_event_native(AuditLogCreate(
            user_email=email, user_role=USERS[email]["role"],
            action="PASSWORD_RESET_REQUESTED", resource_type="User", resource_id=email,
            status="SUCCESS", detail="Lien de réinitialisation démo envoyé",
            ip_address=_ip(request), user_agent=_ua(request),
        ))
    else:
        await log_audit_event_native(AuditLogCreate(
            user_email=email, action="PASSWORD_RESET_REQUESTED",
            resource_type="User", status="FAILURE",
            detail="Email non trouvé ou compte inactif",
            ip_address=_ip(request), user_agent=_ua(request),
        ))

    return {"message": "Si cet email est associé à un compte actif, un lien de réinitialisation a été envoyé."}


@router.post("/reset-password", summary="Réinitialiser le mot de passe via token")
@limiter.limit(limit("5/minute"))
async def reset_password(
    request: Request,
    body: ResetPasswordRequest,
):
    from src.services.password_verification_service import verify_demo_reset_token
    from src.storage.documents.service_bridge import (
        log_audit_event_native, revoke_all_user_tokens_native,
        update_user_password_native, verify_reset_token_native,
    )

    _validate_password_strength(body.new_password)

    user = await verify_reset_token_native(body.token)
    if user:
        await update_user_password_native(str(user.id), hash_password(body.new_password), is_first_login=False)

        # Unauthenticated flow — there is no "current session" to preserve
        # (that's the whole point of this recovery path), so every session
        # is revoked. A JWT stolen before the reset must not survive it.
        revoked_count = await revoke_all_user_tokens_native(
            str(user.id), except_jti=None, reason="password_reset_link",
        )

        await log_audit_event_native(AuditLogCreate(
            user_id=str(user.id), user_email=user.email, user_role=user.role,
            action="PASSWORD_RESET_COMPLETED", resource_type="User", resource_id=str(user.id),
            status="SUCCESS",
            detail=f"Mot de passe réinitialisé via lien — {revoked_count} session(s) révoquée(s)",
            ip_address=_ip(request), user_agent=_ua(request),
        ))
        return {"success": True, "message": "Mot de passe réinitialisé avec succès."}

    demo_email = verify_demo_reset_token(body.token)
    if demo_email and demo_email in USERS:
        USERS[demo_email]["password"] = body.new_password
        DEMO_AUTH_STATE.setdefault(demo_email, {})["is_first_login"] = False
        await log_audit_event_native(AuditLogCreate(
            user_email=demo_email, user_role=USERS[demo_email]["role"],
            action="PASSWORD_RESET_COMPLETED", resource_type="User", resource_id=demo_email,
            status="SUCCESS", detail="Mot de passe démo réinitialisé via lien",
            ip_address=_ip(request), user_agent=_ua(request),
        ))
        return {"success": True, "message": "Mot de passe réinitialisé avec succès."}

    raise HTTPException(400, "Lien invalide ou expiré. Faites une nouvelle demande.")
