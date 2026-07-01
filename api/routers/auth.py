"""Authentication endpoints — login, refresh, logout, OTP, password reset."""
from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.auth import USERS, get_current_user, hash_password, verify_password
from api.deps import get_session
from api.limiter import limiter, limit
from api.security import jwt_handler, account_lockout
from src.models.audit import AuditLogCreate
from src.services.audit_service import log_action, _ip, _ua

router = APIRouter(prefix="/auth", tags=["auth"])

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


class RequestOtpRequest(BaseModel):
    new_password: str
    current_password: str | None = None


class ConfirmOtpRequest(BaseModel):
    otp_code: str
    new_password: str
    current_password: str | None = None


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


# ── Helpers ───────────────────────────────────────────────────────────────────

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


def _register_active_token(jti: str, user_id: str, expires_at: datetime,
                            ip: str | None, ua: str | None, db: Session) -> None:
    from src.storage.orm_models_auth import ActiveTokenORM
    db.merge(ActiveTokenORM(
        jti=jti,
        user_id=str(user_id),
        created_at=datetime.now(timezone.utc),
        expires_at=expires_at,
        ip_address=ip,
        user_agent=(ua or "")[:100],
        revoked=False,
    ))


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
def login(
    request: Request,
    response: Response,
    body: LoginRequest,
    session: Session = Depends(get_session),
) -> LoginResponse:
    from src.storage.orm_models_users import UserORM

    email = body.email.lower().strip()
    ip = _ip(request)
    ua = _ua(request)

    db_user = session.execute(select(UserORM).where(UserORM.email == email)).scalar_one_or_none()

    if db_user:
        # Check account status
        if not db_user.is_active:
            log_action(session, AuditLogCreate(
                user_email=email, action="LOGIN_FAILURE", resource_type="User",
                resource_id=str(db_user.id), status="FAILURE",
                detail="Compte désactivé", ip_address=ip, user_agent=ua,
            ))
            session.commit()
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Compte désactivé.")

        # Check lockout
        locked, remaining = account_lockout.check_locked(db_user)
        if locked:
            log_action(session, AuditLogCreate(
                user_id=str(db_user.id), user_email=email, action="LOGIN_FAILURE",
                resource_type="User", resource_id=str(db_user.id), status="FAILURE",
                detail=f"Compte verrouillé — {remaining} min restantes", ip_address=ip, user_agent=ua,
            ))
            session.commit()
            raise HTTPException(
                status.HTTP_423_LOCKED,
                detail=f"Compte verrouillé. Réessayez dans {remaining} minute(s).",
            )

        # Verify password
        if not verify_password(body.password, db_user.hashed_password):
            attempts = account_lockout.record_failed(db_user, session)
            remaining_attempts = max(0, account_lockout.MAX_ATTEMPTS - attempts)
            log_action(session, AuditLogCreate(
                user_id=str(db_user.id), user_email=email, action="LOGIN_FAILURE",
                resource_type="User", resource_id=str(db_user.id), status="FAILURE",
                detail=f"Tentative #{attempts} depuis {ip}", ip_address=ip, user_agent=ua,
            ))
            session.commit()
            detail = "Email ou mot de passe incorrect."
            if remaining_attempts == 0:
                detail = f"Compte verrouillé après {account_lockout.MAX_ATTEMPTS} tentatives. Réessayez dans {account_lockout.LOCKOUT_MINUTES} min."
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=detail)

        # Success
        account_lockout.record_success(db_user, session)
        db_user.last_login_ip = ip

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
        _register_active_token(
            acc_payload.get("jti", ""), str(db_user.id), expires_at, ip, ua, session
        )

        log_action(session, AuditLogCreate(
            user_id=str(db_user.id), user_email=db_user.email, user_role=db_user.role,
            action="LOGIN_SUCCESS", resource_type="User", resource_id=str(db_user.id),
            status="SUCCESS", detail=f"Connexion depuis {ip}", ip_address=ip, user_agent=ua,
        ))
        session.commit()
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
        log_action(session, AuditLogCreate(
            user_email=email, user_role=demo["role"],
            action="LOGIN_SUCCESS", resource_type="User", status="SUCCESS",
            detail=f"Compte démo depuis {ip}", ip_address=ip, user_agent=ua,
        ))
        session.commit()
        _set_refresh_cookie(response, refresh_token)
        return LoginResponse(
            access_token=access_token,
            role=demo["role"],
            user_id=f"demo:{email}",
        )

    log_action(session, AuditLogCreate(
        user_email=email, action="LOGIN_FAILURE", resource_type="User",
        status="FAILURE", detail=f"Utilisateur inconnu depuis {ip}", ip_address=ip, user_agent=ua,
    ))
    session.commit()
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Email ou mot de passe incorrect.")


@router.post(
    "/refresh",
    response_model=RefreshResponse,
    summary="Renouveler le token d'accès",
    description="Émet un nouveau access_token à partir du refresh_token (cookie httpOnly ou corps).",
)
@limiter.limit(limit("10/minute"))
def refresh_token(
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
    cookie_refresh: str | None = Cookie(default=None, alias=_REFRESH_COOKIE),
):
    # Accept refresh token from cookie OR from JSON body
    body_token: str | None = None
    try:
        data = request.scope.get("_body_cache")
        if data is None:
            import asyncio
            body_bytes = asyncio.get_event_loop().run_until_complete(request.body())
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

    payload = jwt_handler.verify_refresh_token(token, db=session)
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Refresh token invalide ou expiré.")

    user_id = payload.get("sub", "")

    # Look up DB user for fresh role/email
    role = "Comptable"
    email = ""
    extra: dict = {}
    try:
        from src.storage.orm_models_users import UserORM
        from uuid import UUID
        uid = UUID(user_id)
        db_user = session.get(UserORM, uid)
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
    _register_active_token(acc_payload.get("jti", ""), user_id, expires_at, ip, ua, session)

    log_action(session, AuditLogCreate(
        user_id=user_id, action="TOKEN_REFRESHED", resource_type="User",
        status="SUCCESS", detail=f"Token renouvelé depuis {ip}", ip_address=ip, user_agent=ua,
    ))
    session.commit()
    return RefreshResponse(access_token=new_access)


@router.post(
    "/logout",
    summary="Déconnexion",
    description="Révoque l'access_token courant et le refresh_token cookie.",
)
def logout(
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
    cookie_refresh: str | None = Cookie(default=None, alias=_REFRESH_COOKIE),
):
    ip = _ip(request)
    ua = _ua(request)
    user_id = current_user.get("sub")

    # Revoke access token
    jti = current_user.get("jti")
    if jti:
        jwt_handler.revoke_token(jti, "logout", user_id, session)
        # Mark in active_tokens table
        try:
            from src.storage.orm_models_auth import ActiveTokenORM
            active = session.get(ActiveTokenORM, jti)
            if active:
                active.revoked = True
        except Exception:
            pass

    # Revoke refresh token cookie
    if cookie_refresh:
        ref_payload = jwt_handler.verify_refresh_token(cookie_refresh)
        if ref_payload:
            jwt_handler.revoke_token(ref_payload["jti"], "logout", user_id, session)

    log_action(session, AuditLogCreate(
        user_id=user_id, user_email=current_user.get("email"),
        user_role=current_user.get("role"),
        action="LOGOUT", resource_type="User", resource_id=user_id,
        status="SUCCESS", detail=f"Déconnexion depuis {ip}", ip_address=ip, user_agent=ua,
    ))
    session.commit()

    # Clear cookie
    response.delete_cookie(_REFRESH_COOKIE, path="/api/auth")
    return {"message": "Déconnexion réussie."}


@router.get(
    "/sessions",
    summary="Sessions actives",
    description="Retourne les tokens actifs de l'utilisateur courant.",
)
def list_sessions(
    current_user: dict = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    from src.storage.orm_models_auth import ActiveTokenORM
    from sqlalchemy import select as sa_select

    user_id = str(current_user.get("sub", ""))
    current_jti = current_user.get("jti", "")
    now = datetime.now(timezone.utc)

    rows = session.execute(
        sa_select(ActiveTokenORM).where(
            ActiveTokenORM.user_id == user_id,
            ActiveTokenORM.revoked == False,  # noqa: E712
            ActiveTokenORM.expires_at > now,
        ).order_by(ActiveTokenORM.created_at.desc())
    ).scalars().all()

    return {
        "sessions": [
            {
                "jti": r.jti[:8],
                "created_at": r.created_at.isoformat(),
                "expires_at": r.expires_at.isoformat(),
                "ip_address": r.ip_address,
                "is_current": r.jti == current_jti,
            }
            for r in rows
        ]
    }


@router.post(
    "/revoke-session",
    summary="Révoquer une session",
    description="Révoque un token actif par préfixe JTI (8 premiers caractères).",
)
def revoke_session(
    request: Request,
    body: dict,
    current_user: dict = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    from src.storage.orm_models_auth import ActiveTokenORM
    from sqlalchemy import select as sa_select

    jti_prefix = (body.get("jti_prefix") or "").strip()
    if len(jti_prefix) < 8:
        raise HTTPException(400, "jti_prefix doit faire au moins 8 caractères.")

    user_id = str(current_user.get("sub", ""))
    is_admin = current_user.get("role") == "Admin"

    rows = session.execute(
        sa_select(ActiveTokenORM).where(
            ActiveTokenORM.jti.startswith(jti_prefix),
            ActiveTokenORM.revoked == False,  # noqa: E712
        )
    ).scalars().all()

    revoked_count = 0
    for tok in rows:
        if not is_admin and tok.user_id != user_id:
            continue
        tok.revoked = True
        jwt_handler.revoke_token(tok.jti, "session_revoked", user_id, session)
        revoked_count += 1

    log_action(session, AuditLogCreate(
        user_id=user_id, action="SESSION_REVOKED", resource_type="User",
        status="SUCCESS", detail=f"{revoked_count} session(s) révoquée(s) — prefix {jti_prefix}",
        ip_address=_ip(request), user_agent=_ua(request),
    ))
    session.commit()
    return {"revoked": revoked_count}


# ── Password management (unchanged from original) ─────────────────────────────

@router.patch(
    "/change-password",
    summary="Changer le mot de passe (direct — sans OTP)",
)
@limiter.limit(limit("3/minute"))
def change_password(
    request: Request,
    body: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    from src.storage.orm_models_users import UserORM

    email = current_user.get("email")
    if not email:
        raise HTTPException(400, "Changement de mot de passe non disponible pour les comptes de démonstration.")
    if len(body.new_password) < 8:
        raise HTTPException(422, "Le mot de passe doit contenir au moins 8 caractères.")

    user = session.execute(select(UserORM).where(UserORM.email == email)).scalar_one_or_none()
    if not user:
        raise HTTPException(404, "Utilisateur non trouvé.")
    if not verify_password(body.current_password, user.hashed_password):
        raise HTTPException(400, "Mot de passe actuel incorrect.")

    user.hashed_password = hash_password(body.new_password)
    user.is_first_login = False

    # Revoke current access token so user must re-login
    jti = current_user.get("jti")
    if jti:
        jwt_handler.revoke_token(jti, "password_change", str(user.id), session)

    log_action(session, AuditLogCreate(
        user_id=str(user.id), user_email=user.email, user_role=user.role,
        action="PASSWORD_CHANGED", resource_type="User", resource_id=str(user.id),
        status="SUCCESS", detail="Mot de passe changé (direct)",
        ip_address=_ip(request), user_agent=_ua(request),
    ))
    session.commit()
    return {"message": "Mot de passe modifié avec succès."}


@router.post("/change-password/request-otp", summary="Demander un OTP")
@limiter.limit(limit("3/minute"))
def request_otp(
    request: Request,
    body: RequestOtpRequest,
    current_user: dict = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    from src.storage.orm_models_users import UserORM
    from src.services.password_verification_service import generate_otp

    email = current_user.get("email")
    if not email:
        raise HTTPException(400, "Non disponible pour les comptes de démonstration.")
    if len(body.new_password) < 8:
        raise HTTPException(422, "Le mot de passe doit contenir au moins 8 caractères.")

    user = session.execute(select(UserORM).where(UserORM.email == email)).scalar_one_or_none()
    if not user:
        raise HTTPException(404, "Utilisateur non trouvé.")
    if body.current_password and not verify_password(body.current_password, user.hashed_password):
        log_action(session, AuditLogCreate(
            user_id=str(user.id), user_email=user.email, user_role=user.role,
            action="OTP_REQUESTED", resource_type="User", resource_id=str(user.id),
            status="FAILURE", detail="Mot de passe actuel incorrect",
            ip_address=_ip(request), user_agent=_ua(request),
        ))
        session.commit()
        raise HTTPException(400, "Mot de passe actuel incorrect.")

    purpose = "FIRST_LOGIN" if user.is_first_login else "VOLUNTARY_CHANGE"
    generate_otp(session, user, purpose)
    log_action(session, AuditLogCreate(
        user_id=str(user.id), user_email=user.email, user_role=user.role,
        action="OTP_REQUESTED", resource_type="User", resource_id=str(user.id),
        status="SUCCESS", detail=f"OTP demandé (purpose={purpose})",
        ip_address=_ip(request), user_agent=_ua(request),
    ))
    session.commit()
    return {"message": "Code de vérification envoyé par email."}


@router.post("/change-password/confirm", summary="Confirmer changement via OTP")
@limiter.limit(limit("5/minute"))
def confirm_otp(
    request: Request,
    body: ConfirmOtpRequest,
    current_user: dict = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    from src.storage.orm_models_users import UserORM
    from src.services.password_verification_service import verify_otp

    email = current_user.get("email")
    if not email:
        raise HTTPException(400, "Non disponible pour les comptes de démonstration.")
    if len(body.new_password) < 8:
        raise HTTPException(422, "Le mot de passe doit contenir au moins 8 caractères.")

    user = session.execute(select(UserORM).where(UserORM.email == email)).scalar_one_or_none()
    if not user:
        raise HTTPException(404, "Utilisateur non trouvé.")
    if body.current_password and not verify_password(body.current_password, user.hashed_password):
        log_action(session, AuditLogCreate(
            user_id=str(user.id), user_email=user.email, user_role=user.role,
            action="OTP_VERIFIED", resource_type="User", resource_id=str(user.id),
            status="FAILURE", detail="Mot de passe actuel incorrect",
            ip_address=_ip(request), user_agent=_ua(request),
        ))
        session.commit()
        raise HTTPException(400, "Mot de passe actuel incorrect.")

    valid = verify_otp(session, user.id, body.otp_code)
    if not valid:
        log_action(session, AuditLogCreate(
            user_id=str(user.id), user_email=user.email, user_role=user.role,
            action="OTP_VERIFIED", resource_type="User", resource_id=str(user.id),
            status="FAILURE", detail="Code OTP invalide ou expiré",
            ip_address=_ip(request), user_agent=_ua(request),
        ))
        session.commit()
        raise HTTPException(400, "Code incorrect ou expiré. Demandez un nouveau code.")

    user.hashed_password = hash_password(body.new_password)
    user.is_first_login = False
    log_action(session, AuditLogCreate(
        user_id=str(user.id), user_email=user.email, user_role=user.role,
        action="PASSWORD_CHANGED", resource_type="User", resource_id=str(user.id),
        status="SUCCESS", detail="Mot de passe changé via OTP",
        ip_address=_ip(request), user_agent=_ua(request),
    ))
    session.commit()
    return {"success": True, "message": "Mot de passe modifié avec succès."}


@router.post("/forgot-password", summary="Demander un lien de réinitialisation")
@limiter.limit(limit("3/minute"))
def forgot_password(
    request: Request,
    body: ForgotPasswordRequest,
    session: Session = Depends(get_session),
):
    from src.storage.orm_models_users import UserORM
    from src.services.password_verification_service import generate_reset_link

    email = body.email.lower().strip()
    user = session.execute(select(UserORM).where(UserORM.email == email)).scalar_one_or_none()

    if user and user.is_active:
        generate_reset_link(session, user, "FORGOT_PASSWORD")
        log_action(session, AuditLogCreate(
            user_id=str(user.id), user_email=user.email, user_role=user.role,
            action="PASSWORD_RESET_REQUESTED", resource_type="User", resource_id=str(user.id),
            status="SUCCESS", detail="Lien de réinitialisation envoyé",
            ip_address=_ip(request), user_agent=_ua(request),
        ))
    else:
        log_action(session, AuditLogCreate(
            user_email=email, action="PASSWORD_RESET_REQUESTED",
            resource_type="User", status="FAILURE",
            detail="Email non trouvé ou compte inactif",
            ip_address=_ip(request), user_agent=_ua(request),
        ))

    session.commit()
    return {"message": "Si cet email est associé à un compte actif, un lien de réinitialisation a été envoyé."}


@router.post("/reset-password", summary="Réinitialiser le mot de passe via token")
@limiter.limit(limit("5/minute"))
def reset_password(
    request: Request,
    body: ResetPasswordRequest,
    session: Session = Depends(get_session),
):
    from src.services.password_verification_service import verify_reset_token

    if len(body.new_password) < 8:
        raise HTTPException(422, "Le mot de passe doit contenir au moins 8 caractères.")

    user = verify_reset_token(session, body.token)
    if not user:
        raise HTTPException(400, "Lien invalide ou expiré. Faites une nouvelle demande.")

    user.hashed_password = hash_password(body.new_password)
    user.is_first_login = False
    log_action(session, AuditLogCreate(
        user_id=str(user.id), user_email=user.email, user_role=user.role,
        action="PASSWORD_RESET_COMPLETED", resource_type="User", resource_id=str(user.id),
        status="SUCCESS", detail="Mot de passe réinitialisé via lien",
        ip_address=_ip(request), user_agent=_ua(request),
    ))
    session.commit()
    return {"success": True, "message": "Mot de passe réinitialisé avec succès."}
