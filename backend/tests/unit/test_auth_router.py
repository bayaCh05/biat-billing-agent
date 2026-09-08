"""Unit tests for api/routers/auth.py — login, refresh, logout, OTP, password reset.

All Mongo access (src.storage.documents.service_bridge) and JWT revocation
checks (api.security.jwt_handler) are mocked. Route handlers are called via
their `.__wrapped__` attribute (functools.wraps set by @limiter.limit) so
these stay hermetic unit tests, independent of slowapi's rate-limit state
and any live Request/ASGI machinery — see api/limiter.py.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from api.auth import hash_password
from api.routers.auth import (
    ChangePasswordRequest,
    ConfirmOtpRequest,
    ForgotPasswordRequest,
    LoginRequest,
    ResetPasswordRequest,
    RevokeSessionRequest,
    _mask_email,
    _should_use_ldap,
    _validate_password_strength,
    change_password,
    confirm_otp,
    forgot_password,
    list_sessions,
    login,
    logout,
    refresh_token,
    request_otp,
    reset_password,
    revoke_session,
)

_SB = "src.storage.documents.service_bridge"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_request(ip: str = "203.0.113.5", ua: str = "pytest-agent", body: bytes = b"") -> MagicMock:
    req = MagicMock()
    req.client.host = ip
    req.headers = {"user-agent": ua}
    req.scope = {}
    req.body = AsyncMock(return_value=body)
    return req


def _make_response() -> MagicMock:
    return MagicMock()


def _make_db_user(**overrides) -> SimpleNamespace:
    defaults = dict(
        id=uuid4(),
        email="user@example.com",
        role="Comptable",
        nom="Doe",
        prenom="Jane",
        departement="IT",
        is_active=True,
        is_first_login=False,
        hashed_password=hash_password("CurrentPass1!"),
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_refresh_doc(**overrides) -> SimpleNamespace:
    defaults = dict(
        id="jti-refresh-1",
        family_id="fam-1",
        user_id="user-1",
        expires_at=datetime.now(UTC) + timedelta(days=5),
        used=False,
        used_at=None,
        replaced_by=None,
        revoked=False,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ── _validate_password_strength ─────────────────────────────────────────────

class TestValidatePasswordStrength:
    def test_too_short_raises(self):
        with pytest.raises(HTTPException) as exc:
            _validate_password_strength("Ab1!")
        assert exc.value.status_code == 422
        assert "8 caractères" in exc.value.detail

    def test_missing_uppercase_raises(self):
        with pytest.raises(HTTPException) as exc:
            _validate_password_strength("lowercase1!")
        assert "majuscule" in exc.value.detail

    def test_missing_digit_raises(self):
        with pytest.raises(HTTPException) as exc:
            _validate_password_strength("NoDigitsHere!")
        assert "chiffre" in exc.value.detail

    def test_missing_special_char_raises(self):
        with pytest.raises(HTTPException) as exc:
            _validate_password_strength("NoSpecial123")
        assert "spécial" in exc.value.detail

    def test_valid_password_does_not_raise(self):
        _validate_password_strength("Valid1Pass!")


# ── _should_use_ldap ─────────────────────────────────────────────────────────

class TestShouldUseLdap:
    def test_local_mode_never_uses_ldap(self):
        with patch("api.routers.auth._AUTH_MODE", "local"):
            assert _should_use_ldap("anyone@biat.local") is False

    def test_ldap_mode_always_uses_ldap(self):
        with patch("api.routers.auth._AUTH_MODE", "ldap"):
            assert _should_use_ldap("anyone@example.com") is True

    def test_hybrid_mode_matches_ldap_domain(self):
        with (
            patch("api.routers.auth._AUTH_MODE", "hybrid"),
            patch("api.routers.auth._LDAP_USER_DOMAIN", "biat.local"),
        ):
            assert _should_use_ldap("jdoe@biat.local") is True

    def test_hybrid_mode_falls_back_to_local_for_other_domains(self):
        with (
            patch("api.routers.auth._AUTH_MODE", "hybrid"),
            patch("api.routers.auth._LDAP_USER_DOMAIN", "biat.local"),
        ):
            assert _should_use_ldap("jdoe@biat-it.tn") is False


# ── _mask_email ──────────────────────────────────────────────────────────────

class TestMaskEmail:
    def test_normal_email_is_masked(self):
        assert _mask_email("jeandoe@biat.local") == "j***e@biat.local"

    def test_short_local_part_is_masked(self):
        assert _mask_email("jd@biat.local") == "j***@biat.local"

    def test_malformed_email_returns_generic_mask(self):
        assert _mask_email("not-an-email") == "***@***"


# ── login() — local authentication ──────────────────────────────────────────

class TestLoginLocal:
    def _patched(self, **overrides):
        patches = dict(
            check_locked_native=MagicMock(return_value=(False, 0)),
            create_user_native=AsyncMock(),
            get_user_by_email_native=AsyncMock(return_value=None),
            log_audit_event_native=AsyncMock(),
            record_login_failure_native=AsyncMock(return_value=1),
            record_login_success_native=AsyncMock(),
            register_active_token_native=AsyncMock(),
            register_refresh_token_native=AsyncMock(),
            update_user_password_native=AsyncMock(),
            update_user_role_native=AsyncMock(),
        )
        patches.update(overrides)
        return [patch(f"{_SB}.{name}", new=val) for name, val in patches.items()]

    def _run(self, body, **overrides):
        with patch("api.routers.auth._AUTH_MODE", "local"):
            patches = self._patched(**overrides)
            for p in patches:
                p.start()
            try:
                import asyncio
                return asyncio.run(
                    login.__wrapped__(_make_request(), _make_response(), body)
                )
            finally:
                for p in patches:
                    p.stop()

    def test_unknown_email_raises_401(self):
        with pytest.raises(HTTPException) as exc:
            self._run(LoginRequest(email="nobody@nowhere.tn", password="whatever"))
        assert exc.value.status_code == 401

    def test_disabled_account_raises_401(self):
        user = _make_db_user(is_active=False)
        with pytest.raises(HTTPException) as exc:
            self._run(
                LoginRequest(email=user.email, password="whatever"),
                get_user_by_email_native=AsyncMock(return_value=user),
            )
        assert exc.value.status_code == 401
        assert "désactivé" in exc.value.detail

    def test_locked_account_raises_423(self):
        user = _make_db_user()
        with pytest.raises(HTTPException) as exc:
            self._run(
                LoginRequest(email=user.email, password="whatever"),
                get_user_by_email_native=AsyncMock(return_value=user),
                check_locked_native=MagicMock(return_value=(True, 7)),
            )
        assert exc.value.status_code == 423
        assert "7 minute" in exc.value.detail

    def test_wrong_password_raises_401_with_remaining_attempts(self):
        user = _make_db_user()
        with pytest.raises(HTTPException) as exc:
            self._run(
                LoginRequest(email=user.email, password="WrongPass1!"),
                get_user_by_email_native=AsyncMock(return_value=user),
                record_login_failure_native=AsyncMock(return_value=2),
            )
        assert exc.value.status_code == 401
        assert exc.value.detail == "Email ou mot de passe incorrect."

    def test_wrong_password_final_attempt_mentions_lockout(self):
        import api.security.account_lockout as lockout
        user = _make_db_user()
        with pytest.raises(HTTPException) as exc:
            self._run(
                LoginRequest(email=user.email, password="WrongPass1!"),
                get_user_by_email_native=AsyncMock(return_value=user),
                record_login_failure_native=AsyncMock(return_value=lockout.MAX_ATTEMPTS),
            )
        assert exc.value.status_code == 401
        assert "verrouillé" in exc.value.detail

    def test_correct_password_succeeds(self):
        user = _make_db_user()
        result = self._run(
            LoginRequest(email=user.email, password="CurrentPass1!"),
            get_user_by_email_native=AsyncMock(return_value=user),
        )
        assert result.role == user.role
        assert result.user_id == str(user.id)
        assert result.force_password_change is False

    def test_correct_password_first_login_sets_force_change(self):
        user = _make_db_user(is_first_login=True)
        result = self._run(
            LoginRequest(email=user.email, password="CurrentPass1!"),
            get_user_by_email_native=AsyncMock(return_value=user),
        )
        assert result.force_password_change is True
        assert result.is_first_login is True

    def test_legacy_bcrypt_hash_triggers_rehash(self):
        import bcrypt
        bcrypt_hash = bcrypt.hashpw(b"CurrentPass1!", bcrypt.gensalt()).decode()
        user = _make_db_user(hashed_password=bcrypt_hash)
        update_mock = AsyncMock()
        self._run(
            LoginRequest(email=user.email, password="CurrentPass1!"),
            get_user_by_email_native=AsyncMock(return_value=user),
            update_user_password_native=update_mock,
        )
        update_mock.assert_called_once()

# ── login() — LDAP authentication ───────────────────────────────────────────

class TestLoginLdap:
    def _run(self, body, ldap_result, **overrides):
        patches = dict(
            create_user_native=AsyncMock(return_value=_make_db_user(email=body.email)),
            get_user_by_email_native=AsyncMock(return_value=None),
            log_audit_event_native=AsyncMock(),
            record_login_success_native=AsyncMock(),
            register_active_token_native=AsyncMock(),
            register_refresh_token_native=AsyncMock(),
            update_user_role_native=AsyncMock(),
        )
        patches.update(overrides)
        ctxs = [patch(f"{_SB}.{name}", new=val) for name, val in patches.items()]
        ctxs.append(patch("api.routers.auth._AUTH_MODE", "ldap"))
        ctxs.append(patch("src.services.ldap_service.authenticate_ldap", return_value=ldap_result))
        for c in ctxs:
            c.start()
        try:
            import asyncio
            return asyncio.run(login.__wrapped__(_make_request(), _make_response(), body))
        finally:
            for c in ctxs:
                c.stop()

    def test_wrong_ldap_credentials_raise_401(self):
        with pytest.raises(HTTPException) as exc:
            self._run(
                LoginRequest(email="jdoe@biat.local", password="wrong"),
                ldap_result=None,
                log_audit_event_native=AsyncMock(),
            )
        assert exc.value.status_code == 401

    def test_new_ldap_user_is_auto_provisioned(self):
        ldap_result = {"role": "Chef_Projet", "sn": "Doe", "givenName": "Jean"}
        create_mock = AsyncMock(return_value=_make_db_user(email="jdoe@biat.local", role="Chef_Projet"))
        result = self._run(
            LoginRequest(email="jdoe@biat.local", password="whatever"),
            ldap_result=ldap_result,
            get_user_by_email_native=AsyncMock(return_value=None),
            create_user_native=create_mock,
        )
        create_mock.assert_called_once()
        assert result.role == "Chef_Projet"

    def test_new_ldap_user_concurrent_creation_refetches(self):
        """create_user_native() returning None means another request created
        the account first — the handler must re-fetch instead of crashing."""
        user = _make_db_user(email="concurrent@biat.local", role="Comptable")
        result = self._run(
            LoginRequest(email="concurrent@biat.local", password="whatever"),
            ldap_result={"role": "Comptable"},
            get_user_by_email_native=AsyncMock(side_effect=[None, user]),
            create_user_native=AsyncMock(return_value=None),
        )
        assert result.user_id == str(user.id)

    def test_existing_ldap_user_disabled_raises_401(self):
        user = _make_db_user(is_active=False)
        with pytest.raises(HTTPException) as exc:
            self._run(
                LoginRequest(email=user.email, password="whatever"),
                ldap_result={"role": "Comptable"},
                get_user_by_email_native=AsyncMock(return_value=user),
            )
        assert exc.value.status_code == 401
        assert "désactivé" in exc.value.detail

    def test_existing_ldap_user_role_is_updated_from_ldap(self):
        user = _make_db_user(role="Comptable")
        update_mock = AsyncMock()
        result = self._run(
            LoginRequest(email=user.email, password="whatever"),
            ldap_result={"role": "Direction"},
            get_user_by_email_native=AsyncMock(return_value=user),
            update_user_role_native=update_mock,
        )
        update_mock.assert_called_once_with(str(user.id), "Direction")
        assert result.role == "Direction"

    def test_existing_ldap_user_matching_role_skips_update(self):
        user = _make_db_user(role="Comptable")
        update_mock = AsyncMock()
        self._run(
            LoginRequest(email=user.email, password="whatever"),
            ldap_result={"role": "Comptable"},
            get_user_by_email_native=AsyncMock(return_value=user),
            update_user_role_native=update_mock,
        )
        update_mock.assert_not_called()

    def test_ldap_bind_ok_but_no_group_mapped_denies_login(self):
        """Valid LDAP credentials but no recognized group and no
        LDAP_DEFAULT_ROLE configured must deny login, not silently grant
        the Comptable role (ldap_service.py documents empty
        LDAP_DEFAULT_ROLE as "refus de connexion")."""
        create_mock = AsyncMock()
        with pytest.raises(HTTPException) as exc:
            self._run(
                LoginRequest(email="noone@biat.local", password="whatever"),
                ldap_result={"role": None, "dn": "cn=noone,ou=users,dc=biat,dc=local"},
                create_user_native=create_mock,
            )
        assert exc.value.status_code == 401
        create_mock.assert_not_called()


# ── refresh_token() ──────────────────────────────────────────────────────────

class TestRefreshToken:
    def _run(self, cookie_refresh=None, verify_result=None, body: bytes = b"",
             refresh_doc=None, **sb_overrides):
        patches = dict(
            log_audit_event_native=AsyncMock(),
            register_active_token_native=AsyncMock(),
            register_refresh_token_native=AsyncMock(),
            mark_refresh_token_used_native=AsyncMock(),
            revoke_refresh_family_native=AsyncMock(),
            get_refresh_token_native=AsyncMock(return_value=refresh_doc),
            get_user_by_id_native=AsyncMock(return_value=None),
        )
        patches.update(sb_overrides)
        ctxs = [patch(f"{_SB}.{name}", new=val) for name, val in patches.items()]
        ctxs.append(patch("api.routers.auth.jwt_handler.verify_refresh_token",
                           new=AsyncMock(return_value=verify_result)))
        for c in ctxs:
            c.start()
        try:
            import asyncio
            return asyncio.run(
                refresh_token.__wrapped__(_make_request(body=body), _make_response(), cookie_refresh)
            )
        finally:
            for c in ctxs:
                c.stop()

    def test_missing_token_raises_401(self):
        with pytest.raises(HTTPException) as exc:
            self._run(cookie_refresh=None)
        assert exc.value.status_code == 401
        assert "manquant" in exc.value.detail

    def test_token_accepted_from_json_body_when_no_cookie(self):
        user = _make_db_user()
        result = self._run(
            cookie_refresh=None,
            verify_result={"sub": str(user.id), "jti": "jti-1", "family_id": "fam-1"},
            body=b'{"refresh_token": "from-body"}',
            get_user_by_id_native=AsyncMock(return_value=user),
            refresh_doc=_make_refresh_doc(id="jti-1", family_id="fam-1", user_id=str(user.id)),
        )
        assert result.access_token

    def test_invalid_token_raises_401(self):
        with pytest.raises(HTTPException) as exc:
            self._run(cookie_refresh="bad-token", verify_result=None)
        assert exc.value.status_code == 401
        assert "invalide" in exc.value.detail

    def test_valid_token_for_active_db_user_uses_fresh_role(self):
        user = _make_db_user(role="Direction")
        result = self._run(
            cookie_refresh="good-token",
            verify_result={"sub": str(user.id), "jti": "jti-1", "family_id": "fam-1"},
            get_user_by_id_native=AsyncMock(return_value=user),
            refresh_doc=_make_refresh_doc(id="jti-1", family_id="fam-1", user_id=str(user.id)),
        )
        assert result.access_token

    def test_valid_token_for_demo_sub_is_best_effort(self):
        # "demo:foo@bar.tn" is not a valid UUID -> ValueError is caught silently.
        result = self._run(
            cookie_refresh="good-token",
            verify_result={
                "sub": "demo:comptable@biat-it.tn", "jti": "jti-1", "family_id": "fam-1",
            },
            refresh_doc=_make_refresh_doc(
                id="jti-1", family_id="fam-1", user_id="demo:comptable@biat-it.tn",
            ),
        )
        assert result.access_token

    def test_valid_token_for_inactive_user_keeps_default_role(self):
        user = _make_db_user(is_active=False)
        result = self._run(
            cookie_refresh="good-token",
            verify_result={"sub": str(user.id), "jti": "jti-1", "family_id": "fam-1"},
            get_user_by_id_native=AsyncMock(return_value=user),
            refresh_doc=_make_refresh_doc(id="jti-1", family_id="fam-1", user_id=str(user.id)),
        )
        assert result.access_token

    # ── migration fail-closed ────────────────────────────────────────────────

    def test_legacy_token_without_family_id_fails_closed(self):
        with pytest.raises(HTTPException) as exc:
            self._run(
                cookie_refresh="pre-migration-token",
                verify_result={"sub": "user-1", "jti": "jti-1"},  # no family_id
            )
        assert exc.value.status_code == 401

    def test_no_matching_refresh_doc_fails_closed(self):
        with pytest.raises(HTTPException) as exc:
            self._run(
                cookie_refresh="tok",
                verify_result={"sub": "user-1", "jti": "jti-1", "family_id": "fam-1"},
                refresh_doc=None,
            )
        assert exc.value.status_code == 401

    # ── revocation / reuse detection (security-critical path) ──────────────────

    def test_revoked_family_raises_401_without_re_revoking(self):
        revoke_mock = AsyncMock()
        with pytest.raises(HTTPException) as exc:
            self._run(
                cookie_refresh="tok",
                verify_result={"sub": "user-1", "jti": "jti-1", "family_id": "fam-1"},
                refresh_doc=_make_refresh_doc(
                    id="jti-1", family_id="fam-1", user_id="user-1", revoked=True,
                ),
                revoke_refresh_family_native=revoke_mock,
            )
        assert exc.value.status_code == 401
        assert "révoqué" in exc.value.detail
        revoke_mock.assert_not_called()

    def test_reused_token_revokes_whole_family(self):
        revoke_mock = AsyncMock(return_value=2)
        with pytest.raises(HTTPException) as exc:
            self._run(
                cookie_refresh="stolen-token",
                verify_result={"sub": "user-1", "jti": "jti-old", "family_id": "fam-1"},
                refresh_doc=_make_refresh_doc(
                    id="jti-old", family_id="fam-1", user_id="user-1", used=True,
                ),
                revoke_refresh_family_native=revoke_mock,
            )
        assert exc.value.status_code == 401
        assert "utilisé" in exc.value.detail
        revoke_mock.assert_called_once_with("fam-1", "reuse_detected")

    def test_reused_token_logs_reuse_detected_audit_event(self):
        audit_mock = AsyncMock()
        with pytest.raises(HTTPException):
            self._run(
                cookie_refresh="stolen-token",
                verify_result={"sub": "user-1", "jti": "jti-old", "family_id": "fam-1"},
                refresh_doc=_make_refresh_doc(
                    id="jti-old", family_id="fam-1", user_id="user-1", used=True,
                ),
                log_audit_event_native=audit_mock,
            )
        audit_mock.assert_called_once()
        logged = audit_mock.call_args.args[0]
        assert logged.action == "REFRESH_TOKEN_REUSE_DETECTED"
        assert logged.status == "FAILURE"
        assert logged.user_id == "user-1"

    def test_reused_token_does_not_mint_new_tokens(self):
        register_active = AsyncMock()
        register_refresh = AsyncMock()
        with pytest.raises(HTTPException):
            self._run(
                cookie_refresh="stolen-token",
                verify_result={"sub": "user-1", "jti": "jti-old", "family_id": "fam-1"},
                refresh_doc=_make_refresh_doc(
                    id="jti-old", family_id="fam-1", user_id="user-1", used=True,
                ),
                register_active_token_native=register_active,
                register_refresh_token_native=register_refresh,
            )
        register_active.assert_not_called()
        register_refresh.assert_not_called()

    # ── successful rotation ──────────────────────────────────────────────────

    def test_successful_rotation_marks_old_token_used(self):
        mark_mock = AsyncMock()
        result = self._run(
            cookie_refresh="good-token",
            verify_result={"sub": "user-1", "jti": "jti-old", "family_id": "fam-1"},
            refresh_doc=_make_refresh_doc(id="jti-old", family_id="fam-1", user_id="user-1"),
            mark_refresh_token_used_native=mark_mock,
        )
        assert result.access_token
        mark_mock.assert_called_once()
        assert mark_mock.call_args.args[0] == "jti-old"
        assert mark_mock.call_args.kwargs["replaced_by"] != "jti-old"

    def test_successful_rotation_registers_new_token_with_same_family_and_ceiling(self):
        register_mock = AsyncMock()
        doc = _make_refresh_doc(id="jti-old", family_id="fam-1", user_id="user-1")
        result = self._run(
            cookie_refresh="good-token",
            verify_result={"sub": "user-1", "jti": "jti-old", "family_id": "fam-1"},
            refresh_doc=doc,
            register_refresh_token_native=register_mock,
        )
        assert result.access_token
        register_mock.assert_called_once()
        new_jti, family_id, user_id, expires_at = register_mock.call_args.args
        assert new_jti != "jti-old"
        assert family_id == "fam-1"
        assert user_id == "user-1"
        assert expires_at == doc.expires_at  # plafond absolu inchangé, pas prolongé


# ── logout() ─────────────────────────────────────────────────────────────────

class TestLogout:
    def _run(self, current_user, cookie_refresh=None, verify_result=None,
              revoke_token_mock=None, **sb_overrides):
        patches = dict(
            log_audit_event_native=AsyncMock(),
            revoke_active_token_native=AsyncMock(),
            revoke_refresh_family_native=AsyncMock(),
        )
        patches.update(sb_overrides)
        ctxs = [patch(f"{_SB}.{name}", new=val) for name, val in patches.items()]
        ctxs.append(patch("api.routers.auth.jwt_handler.revoke_token",
                           new=revoke_token_mock or AsyncMock()))
        ctxs.append(patch("api.routers.auth.jwt_handler.verify_refresh_token",
                           new=AsyncMock(return_value=verify_result)))
        for c in ctxs:
            c.start()
        try:
            import asyncio
            return asyncio.run(
                logout(_make_request(), _make_response(), current_user, cookie_refresh)
            )
        finally:
            for c in ctxs:
                c.stop()

    def test_logout_with_jti_and_legacy_cookie_revokes_both(self):
        # Cookie sans family_id (pré-migration) -> fallback single-jti pour le refresh.
        current_user = {"sub": "user-1", "jti": "jti-access", "email": "a@b.tn", "role": "Comptable"}
        revoke_mock = AsyncMock()
        result = self._run(current_user, cookie_refresh="refresh-tok",
                            verify_result={"jti": "jti-refresh"}, revoke_token_mock=revoke_mock)
        assert result == {"message": "Déconnexion réussie."}
        assert revoke_mock.await_count == 2  # access jti + refresh jti (fallback)

    def test_logout_without_jti_or_cookie_still_succeeds(self):
        current_user = {"sub": "user-1", "email": "a@b.tn", "role": "Comptable"}
        result = self._run(current_user, cookie_refresh=None, verify_result=None)
        assert result == {"message": "Déconnexion réussie."}

    def test_logout_with_family_id_revokes_whole_family(self):
        current_user = {
            "sub": "user-1", "jti": "jti-access", "email": "a@b.tn", "role": "Comptable",
        }
        revoke_token_mock = AsyncMock()
        revoke_family_mock = AsyncMock()
        result = self._run(
            current_user, cookie_refresh="refresh-tok",
            verify_result={"jti": "jti-refresh", "family_id": "fam-1"},
            revoke_token_mock=revoke_token_mock,
            revoke_refresh_family_native=revoke_family_mock,
        )
        assert result == {"message": "Déconnexion réussie."}
        revoke_family_mock.assert_awaited_once_with("fam-1", "logout")
        # jwt_handler.revoke_token n'est appelé qu'une fois — pour l'access
        # token — pas pour le refresh, qui passe par la famille.
        assert revoke_token_mock.await_count == 1


# ── list_sessions() ──────────────────────────────────────────────────────────

class TestListSessions:
    def _run(self, current_user, mongo_rows):
        with patch(f"{_SB}.list_active_sessions_mongo", new=AsyncMock(return_value=mongo_rows)):
            import asyncio
            return asyncio.run(list_sessions(current_user))

    def test_mongo_unavailable_returns_empty_list(self):
        result = self._run({"sub": "u1", "jti": "abc"}, mongo_rows=None)
        assert result == {"sessions": []}

    def test_current_session_is_flagged(self):
        from datetime import datetime, timezone
        row = SimpleNamespace(
            id="abcd1234efgh", created_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc), ip_address="1.2.3.4",
        )
        result = self._run({"sub": "u1", "jti": "abcd1234efgh"}, mongo_rows=[row])
        assert result["sessions"][0]["is_current"] is True
        assert result["sessions"][0]["jti"] == "abcd1234"

    def test_other_session_is_not_flagged(self):
        from datetime import datetime, timezone
        row = SimpleNamespace(
            id="zzzz9999yyyy", created_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc), ip_address="5.6.7.8",
        )
        result = self._run({"sub": "u1", "jti": "abcd1234efgh"}, mongo_rows=[row])
        assert result["sessions"][0]["is_current"] is False


# ── revoke_session() ─────────────────────────────────────────────────────────

class TestRevokeSession:
    def test_short_prefix_raises_400(self):
        with pytest.raises(HTTPException) as exc:
            import asyncio
            asyncio.run(revoke_session(
                _make_request(), RevokeSessionRequest(jti_prefix="short"),
                {"sub": "u1", "role": "Comptable"},
            ))
        assert exc.value.status_code == 400

    def test_valid_prefix_revokes_and_returns_count(self):
        with (
            patch(f"{_SB}.revoke_active_tokens_by_prefix_native",
                  new=AsyncMock(return_value=3)) as revoke_mock,
            patch(f"{_SB}.log_audit_event_native", new=AsyncMock()),
        ):
            import asyncio
            result = asyncio.run(revoke_session(
                _make_request(), RevokeSessionRequest(jti_prefix="abcd1234"),
                {"sub": "u1", "role": "Admin"},
            ))
        assert result == {"revoked": 3}
        revoke_mock.assert_called_once_with("abcd1234", "u1", True)


# ── change_password() ────────────────────────────────────────────────────────

class TestChangePassword:
    def _run(self, current_user, body, **sb_overrides):
        patches = dict(
            get_user_by_email_native=AsyncMock(return_value=None),
            log_audit_event_native=AsyncMock(),
            revoke_all_user_tokens_native=AsyncMock(return_value=0),
            update_user_password_native=AsyncMock(),
        )
        patches.update(sb_overrides)
        ctxs = [patch(f"{_SB}.{name}", new=val) for name, val in patches.items()]
        for c in ctxs:
            c.start()
        try:
            import asyncio
            return asyncio.run(
                change_password.__wrapped__(_make_request(), body, current_user)
            )
        finally:
            for c in ctxs:
                c.stop()

    def test_token_without_email_claim_raises_400(self):
        with pytest.raises(HTTPException) as exc:
            self._run(
                {"sub": "some-uuid"},
                ChangePasswordRequest(current_password="a", new_password="NewPass1!"),
            )
        assert exc.value.status_code == 400

    def test_wrong_current_password_raises_400(self):
        user = _make_db_user()
        with pytest.raises(HTTPException) as exc:
            self._run(
                {"email": user.email, "sub": str(user.id)},
                ChangePasswordRequest(current_password="WrongOne!", new_password="NewPass1!"),
                get_user_by_email_native=AsyncMock(return_value=user),
            )
        assert exc.value.status_code == 400
        assert "incorrect" in exc.value.detail

    def test_correct_password_updates_and_revokes_other_sessions(self):
        user = _make_db_user()
        revoke_mock = AsyncMock(return_value=2)
        result = self._run(
            {"email": user.email, "sub": str(user.id), "jti": "current-jti"},
            ChangePasswordRequest(current_password="CurrentPass1!", new_password="NewPass1!"),
            get_user_by_email_native=AsyncMock(return_value=user),
            revoke_all_user_tokens_native=revoke_mock,
        )
        assert result["message"] == "Mot de passe modifié avec succès."
        revoke_mock.assert_called_once_with(str(user.id), except_jti="current-jti", reason="password_change")

    def test_user_not_found_anywhere_raises_404(self):
        with pytest.raises(HTTPException) as exc:
            self._run(
                {"email": "ghost@nowhere.tn", "sub": "x"},
                ChangePasswordRequest(current_password="a", new_password="NewPass1!"),
            )
        assert exc.value.status_code == 404


# ── request_otp() ────────────────────────────────────────────────────────────

class TestRequestOtp:
    def _run(self, current_user, **sb_overrides):
        patches = dict(
            generate_otp_native=AsyncMock(return_value="123456"),
            get_user_by_email_native=AsyncMock(return_value=None),
            log_audit_event_native=AsyncMock(),
        )
        patches.update(sb_overrides)
        ctxs = [patch(f"{_SB}.{name}", new=val) for name, val in patches.items()]
        for c in ctxs:
            c.start()
        try:
            import asyncio
            return asyncio.run(request_otp.__wrapped__(_make_request(), current_user))
        finally:
            for c in ctxs:
                c.stop()

    def test_no_email_raises_400(self):
        with pytest.raises(HTTPException) as exc:
            self._run({"sub": "some-uuid"})
        assert exc.value.status_code == 400

    def test_real_user_generates_otp(self):
        user = _make_db_user()
        generate_mock = AsyncMock(return_value="654321")
        result = self._run(
            {"sub": str(user.id), "email": user.email},
            get_user_by_email_native=AsyncMock(return_value=user),
            generate_otp_native=generate_mock,
        )
        assert "message" in result
        generate_mock.assert_called_once()

    def test_user_not_found_raises_404(self):
        with pytest.raises(HTTPException) as exc:
            self._run({"sub": "some-uuid", "email": "ghost@biat.local"})
        assert exc.value.status_code == 404


# ── confirm_otp() ─────────────────────────────────────────────────────────────

class TestConfirmOtp:
    def _run(self, current_user, body, **sb_overrides):
        patches = dict(
            get_user_by_email_native=AsyncMock(return_value=None),
            log_audit_event_native=AsyncMock(),
            revoke_all_user_tokens_native=AsyncMock(return_value=0),
            update_user_password_native=AsyncMock(),
            verify_otp_native=AsyncMock(return_value=True),
        )
        patches.update(sb_overrides)
        ctxs = [patch(f"{_SB}.{name}", new=val) for name, val in patches.items()]
        for c in ctxs:
            c.start()
        try:
            import asyncio
            return asyncio.run(confirm_otp.__wrapped__(_make_request(), body, current_user))
        finally:
            for c in ctxs:
                c.stop()

    def test_no_email_raises_400(self):
        with pytest.raises(HTTPException) as exc:
            self._run({"sub": "some-uuid"}, ConfirmOtpRequest(new_password="NewPass1!"))
        assert exc.value.status_code == 400

    def test_real_user_wrong_current_password_raises_400(self):
        user = _make_db_user()
        with pytest.raises(HTTPException) as exc:
            self._run(
                {"sub": str(user.id), "email": user.email},
                ConfirmOtpRequest(new_password="NewPass1!", current_password="Wrong!"),
                get_user_by_email_native=AsyncMock(return_value=user),
            )
        assert exc.value.status_code == 400
        assert "incorrect" in exc.value.detail

    def test_real_user_missing_otp_code_raises_400(self):
        user = _make_db_user()
        with pytest.raises(HTTPException) as exc:
            self._run(
                {"sub": str(user.id), "email": user.email},
                ConfirmOtpRequest(new_password="NewPass1!"),
                get_user_by_email_native=AsyncMock(return_value=user),
            )
        assert exc.value.status_code == 400
        assert "OTP requis" in exc.value.detail

    def test_real_user_invalid_otp_raises_400(self):
        user = _make_db_user()
        with pytest.raises(HTTPException) as exc:
            self._run(
                {"sub": str(user.id), "email": user.email},
                ConfirmOtpRequest(new_password="NewPass1!", otp_code="000000"),
                get_user_by_email_native=AsyncMock(return_value=user),
                verify_otp_native=AsyncMock(return_value=False),
            )
        assert exc.value.status_code == 400
        assert "incorrect ou expiré" in exc.value.detail

    def test_real_user_success(self):
        user = _make_db_user()
        result = self._run(
            {"sub": str(user.id), "email": user.email, "jti": "j1"},
            ConfirmOtpRequest(new_password="NewPass1!", otp_code="123456"),
            get_user_by_email_native=AsyncMock(return_value=user),
            verify_otp_native=AsyncMock(return_value=True),
        )
        assert result["success"] is True

    def test_real_user_not_found_raises_404(self):
        with pytest.raises(HTTPException) as exc:
            self._run(
                {"sub": "some-uuid", "email": "ghost@biat.local"},
                ConfirmOtpRequest(new_password="NewPass1!", otp_code="123456"),
            )
        assert exc.value.status_code == 404


# ── forgot_password() ────────────────────────────────────────────────────────

class TestForgotPassword:
    _EXPECTED_MESSAGE = (
        "Si cet email est associé à un compte actif, un lien de réinitialisation a été envoyé."
    )

    def _run(self, email, **sb_overrides):
        patches = dict(
            generate_reset_link_native=AsyncMock(return_value="tok"),
            get_user_by_email_native=AsyncMock(return_value=None),
            log_audit_event_native=AsyncMock(),
        )
        patches.update(sb_overrides)
        ctxs = [patch(f"{_SB}.{name}", new=val) for name, val in patches.items()]
        for c in ctxs:
            c.start()
        try:
            import asyncio
            return asyncio.run(
                forgot_password.__wrapped__(_make_request(), ForgotPasswordRequest(email=email))
            )
        finally:
            for c in ctxs:
                c.stop()

    def test_active_user_generates_reset_link(self):
        user = _make_db_user()
        generate_mock = AsyncMock(return_value="tok")
        result = self._run(user.email, get_user_by_email_native=AsyncMock(return_value=user),
                            generate_reset_link_native=generate_mock)
        generate_mock.assert_called_once()
        assert result["message"] == self._EXPECTED_MESSAGE

    def test_unknown_email_gives_identical_message(self):
        """Same response regardless of outcome — prevents user enumeration."""
        result = self._run("nobody@nowhere.tn")
        assert result["message"] == self._EXPECTED_MESSAGE


# ── reset_password() ─────────────────────────────────────────────────────────

class TestResetPassword:
    def _run(self, body, **sb_overrides):
        patches = dict(
            log_audit_event_native=AsyncMock(),
            revoke_all_user_tokens_native=AsyncMock(return_value=0),
            update_user_password_native=AsyncMock(),
            verify_reset_token_native=AsyncMock(return_value=None),
        )
        patches.update(sb_overrides)
        ctxs = [patch(f"{_SB}.{name}", new=val) for name, val in patches.items()]
        for c in ctxs:
            c.start()
        try:
            import asyncio
            return asyncio.run(reset_password.__wrapped__(_make_request(), body))
        finally:
            for c in ctxs:
                c.stop()

    def test_weak_password_rejected_before_lookup(self):
        lookup_mock = AsyncMock(return_value=None)
        with pytest.raises(HTTPException) as exc:
            self._run(
                ResetPasswordRequest(token="tok", new_password="weak"),
                verify_reset_token_native=lookup_mock,
            )
        assert exc.value.status_code == 422
        lookup_mock.assert_not_called()

    def test_valid_real_token_resets_and_revokes_all_sessions(self):
        user = _make_db_user()
        revoke_mock = AsyncMock(return_value=4)
        result = self._run(
            ResetPasswordRequest(token="good-tok", new_password="NewPass1!"),
            verify_reset_token_native=AsyncMock(return_value=user),
            revoke_all_user_tokens_native=revoke_mock,
        )
        assert result["success"] is True
        revoke_mock.assert_called_once_with(str(user.id), except_jti=None, reason="password_reset_link")

    def test_invalid_token_raises_400(self):
        with pytest.raises(HTTPException) as exc:
            self._run(ResetPasswordRequest(token="bad-tok", new_password="NewPass1!"))
        assert exc.value.status_code == 400
