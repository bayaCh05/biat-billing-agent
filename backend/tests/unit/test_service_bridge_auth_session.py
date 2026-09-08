"""Unit tests — service_bridge.py auth/session functions (Tier 1, sub-batch 1
of the test-coverage scoping plan: auth writes, then audit, then invoices).

service_bridge.py has 98 functions (down from 127 after removing 29 dead
ones — see the dead-code removal commit) and had ~4 with direct tests before
this file. This batch covers the 21 live auth/session functions not already
tested elsewhere in this suite: login/lockout, password/profile/avatar
updates, OTP, reset links, and session (ActiveToken/RevokedToken) lifecycle.

Convention: mock everything (Beanie Document classes + pymongo collections),
per CLAUDE.md unit-test conventions — no real Mongo connection.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.storage.documents.service_bridge import (
    _hash_otp_code,
    check_locked_native,
    generate_reset_link_native,
    get_user_by_email_mongo,
    get_user_by_email_native,
    get_user_by_id_native,
    list_active_sessions_mongo,
    list_users_mongo,
    record_login_failure_native,
    record_login_success_native,
    register_active_token_native,
    revoke_active_token_native,
    revoke_active_tokens_by_prefix_native,
    revoke_token_native,
    unlock_account_native,
    update_user_admin_native,
    update_user_avatar_native,
    update_user_password_native,
    update_user_profile_native,
    update_user_role_native,
    verify_otp_native,
    verify_reset_token_native,
)


def _run(coro):
    return asyncio.run(coro)


def _find_chain(return_value):
    """Mimic Document.find(query).sort(...).to_list() / .count()."""
    chain = MagicMock()
    chain.sort.return_value = chain
    chain.to_list = AsyncMock(return_value=return_value)
    chain.count = AsyncMock(return_value=len(return_value) if return_value is not None else 0)
    return chain


class TestListUsersMongo:
    def test_returns_sorted_list(self):
        docs = [SimpleNamespace(id="u1"), SimpleNamespace(id="u2")]
        with patch(
            "src.storage.documents.user.UserDocument.find",
            return_value=_find_chain(docs),
        ):
            result = _run(list_users_mongo())
        assert result == docs

    def test_returns_none_when_mongo_down(self):
        with patch(
            "src.storage.documents.user.UserDocument.find",
            side_effect=Exception("mongo down"),
        ):
            result = _run(list_users_mongo())
        assert result is None


class TestGetUserByEmailMongo:
    def test_returns_doc_when_found(self):
        doc = SimpleNamespace(id="u1", email="a@biat-it.tn")
        with patch(
            "src.storage.documents.user.UserDocument.find_one",
            new=AsyncMock(return_value=doc),
        ):
            result = _run(get_user_by_email_mongo("a@biat-it.tn"))
        assert result is doc

    def test_returns_not_found_sentinel_when_absent(self):
        from src.storage.documents.service_bridge import _NOT_FOUND

        with patch(
            "src.storage.documents.user.UserDocument.find_one",
            new=AsyncMock(return_value=None),
        ):
            result = _run(get_user_by_email_mongo("nobody@biat-it.tn"))
        assert result is _NOT_FOUND

    def test_returns_none_when_mongo_down(self):
        with patch(
            "src.storage.documents.user.UserDocument.find_one",
            side_effect=Exception("mongo down"),
        ):
            result = _run(get_user_by_email_mongo("a@biat-it.tn"))
        assert result is None


class TestListActiveSessionsMongo:
    def test_returns_sessions(self):
        docs = [SimpleNamespace(id="jti-1")]
        with patch(
            "src.storage.documents.active_token.ActiveTokenDocument.find",
            return_value=_find_chain(docs),
        ):
            result = _run(list_active_sessions_mongo("user-1"))
        assert result == docs

    def test_returns_none_when_mongo_down(self):
        with patch(
            "src.storage.documents.active_token.ActiveTokenDocument.find",
            side_effect=Exception("mongo down"),
        ):
            result = _run(list_active_sessions_mongo("user-1"))
        assert result is None


class TestGetUserByIdNative:
    def test_delegates_to_get_by_str_id(self):
        user = SimpleNamespace(id="user-1")
        with patch(
            "src.storage.documents.service_bridge._get_by_str_id",
            new=AsyncMock(return_value=user),
        ) as mock_get:
            result = _run(get_user_by_id_native("user-1"))
        assert result is user
        mock_get.assert_awaited_once()


class TestGetUserByEmailNative:
    def test_uses_dict_filtered_find_one(self):
        user = SimpleNamespace(id="user-1", email="a@biat-it.tn")
        with patch(
            "src.storage.documents.user.UserDocument.find_one",
            new=AsyncMock(return_value=user),
        ) as mock_find:
            result = _run(get_user_by_email_native("a@biat-it.tn"))
        assert result is user
        mock_find.assert_awaited_once_with({"email": "a@biat-it.tn"})


class TestRecordLoginSuccessNative:
    def test_resets_lockout_state_and_sets_login_metadata(self):
        coll = MagicMock()
        coll.update_one = AsyncMock()
        with patch(
            "src.storage.documents.user.UserDocument.get_pymongo_collection",
            return_value=coll,
        ):
            _run(record_login_success_native("user-1", "1.2.3.4"))

        args = coll.update_one.call_args
        assert args[0][0] == {"_id": "user-1"}
        update = args[0][1]["$set"]
        assert update["failed_login_attempts"] == 0
        assert update["locked_until"] is None
        assert update["last_login_ip"] == "1.2.3.4"


class TestRecordLoginFailureNative:
    def test_increments_attempts_without_locking_below_threshold(self, monkeypatch):
        monkeypatch.setenv("MAX_FAILED_LOGIN_ATTEMPTS", "5")
        user_doc = SimpleNamespace(id="user-1", failed_login_attempts=1)
        coll = MagicMock()
        coll.update_one = AsyncMock()
        with patch(
            "src.storage.documents.user.UserDocument.get_pymongo_collection",
            return_value=coll,
        ):
            attempts = _run(record_login_failure_native(user_doc))

        assert attempts == 2
        update = coll.update_one.call_args[0][1]["$set"]
        assert update["failed_login_attempts"] == 2
        assert "locked_until" not in update

    def test_locks_account_at_threshold(self, monkeypatch):
        monkeypatch.setenv("MAX_FAILED_LOGIN_ATTEMPTS", "5")
        monkeypatch.setenv("ACCOUNT_LOCKOUT_MINUTES", "15")
        user_doc = SimpleNamespace(id="user-1", failed_login_attempts=4)
        coll = MagicMock()
        coll.update_one = AsyncMock()
        with patch(
            "src.storage.documents.user.UserDocument.get_pymongo_collection",
            return_value=coll,
        ):
            attempts = _run(record_login_failure_native(user_doc))

        assert attempts == 5
        update = coll.update_one.call_args[0][1]["$set"]
        assert update["locked_until"] is not None


class TestCheckLockedNative:
    def test_not_locked_when_no_locked_until(self):
        user_doc = SimpleNamespace(locked_until=None)
        assert check_locked_native(user_doc) == (False, 0)

    def test_locked_when_locked_until_in_future(self):
        future = datetime.now(timezone.utc) + timedelta(minutes=10)
        user_doc = SimpleNamespace(locked_until=future)
        locked, remaining = check_locked_native(user_doc)
        assert locked is True
        assert 1 <= remaining <= 10

    def test_not_locked_when_locked_until_in_past(self):
        past = datetime.now(timezone.utc) - timedelta(minutes=1)
        user_doc = SimpleNamespace(locked_until=past)
        assert check_locked_native(user_doc) == (False, 0)

    def test_handles_naive_datetime(self):
        # SQLite/legacy rows can read back naive datetimes (see codebase convention)
        future_naive = (datetime.now(timezone.utc) + timedelta(minutes=5)).replace(tzinfo=None)
        user_doc = SimpleNamespace(locked_until=future_naive)
        locked, _ = check_locked_native(user_doc)
        assert locked is True


class TestUpdateUserRoleNative:
    def test_sets_role(self):
        coll = MagicMock()
        coll.update_one = AsyncMock()
        with patch(
            "src.storage.documents.user.UserDocument.get_pymongo_collection",
            return_value=coll,
        ):
            _run(update_user_role_native("user-1", "Direction"))
        coll.update_one.assert_awaited_once_with({"_id": "user-1"}, {"$set": {"role": "Direction"}})


class TestUpdateUserPasswordNative:
    def test_sets_password_and_first_login_flag(self):
        coll = MagicMock()
        coll.update_one = AsyncMock()
        with patch(
            "src.storage.documents.user.UserDocument.get_pymongo_collection",
            return_value=coll,
        ):
            _run(update_user_password_native("user-1", "hashed", is_first_login=True))
        coll.update_one.assert_awaited_once_with(
            {"_id": "user-1"},
            {"$set": {"hashed_password": "hashed", "is_first_login": True}},
        )


class TestRegisterActiveTokenNative:
    def test_registers_new_session_below_cap(self):
        coll = MagicMock()
        coll.update_many = AsyncMock()
        coll.replace_one = AsyncMock()
        with patch(
            "src.storage.documents.service_bridge._MAX_ACTIVE_SESSIONS", 5,
        ), patch(
            "src.storage.documents.active_token.ActiveTokenDocument.find",
            return_value=_find_chain([]),
        ), patch(
            "src.storage.documents.active_token.ActiveTokenDocument.get_pymongo_collection",
            return_value=coll,
        ):
            _run(register_active_token_native(
                "jti-new", "user-1", datetime.now(timezone.utc) + timedelta(hours=8), "1.2.3.4", "pytest-ua",
            ))

        coll.update_many.assert_not_awaited()
        coll.replace_one.assert_awaited_once()

    def test_evicts_oldest_sessions_when_at_cap(self):
        existing = [SimpleNamespace(id="jti-old-1"), SimpleNamespace(id="jti-old-2")]
        coll = MagicMock()
        coll.update_many = AsyncMock()
        coll.replace_one = AsyncMock()
        with patch(
            "src.storage.documents.service_bridge._MAX_ACTIVE_SESSIONS", 2,
        ), patch(
            "src.storage.documents.active_token.ActiveTokenDocument.find",
            return_value=_find_chain(existing),
        ), patch(
            "src.storage.documents.active_token.ActiveTokenDocument.get_pymongo_collection",
            return_value=coll,
        ):
            _run(register_active_token_native(
                "jti-new", "user-1", datetime.now(timezone.utc) + timedelta(hours=8), None, None,
            ))

        coll.update_many.assert_awaited_once()
        evicted_ids = coll.update_many.call_args[0][0]["_id"]["$in"]
        assert evicted_ids == ["jti-old-1"]  # 2 existing + 1 new > cap(2) -> evict 1 oldest


class TestRevokeActiveTokenNative:
    def test_marks_token_revoked(self):
        coll = MagicMock()
        coll.update_one = AsyncMock()
        with patch(
            "src.storage.documents.active_token.ActiveTokenDocument.get_pymongo_collection",
            return_value=coll,
        ):
            _run(revoke_active_token_native("jti-1"))
        coll.update_one.assert_awaited_once_with({"_id": "jti-1"}, {"$set": {"revoked": True}})


class TestRevokeActiveTokensByPrefixNative:
    def test_non_admin_scopes_to_own_user(self):
        rows = [SimpleNamespace(id="jti-abc123")]
        coll = MagicMock()
        coll.update_many = AsyncMock()
        with patch(
            "src.storage.documents.active_token.ActiveTokenDocument.find",
            return_value=_find_chain(rows),
        ) as mock_find, patch(
            "src.storage.documents.active_token.ActiveTokenDocument.get_pymongo_collection",
            return_value=coll,
        ), patch(
            "src.storage.documents.service_bridge.revoke_token_native",
            new=AsyncMock(),
        ) as mock_revoke:
            count = _run(revoke_active_tokens_by_prefix_native("jti-abc", "user-1", is_admin=False))

        assert count == 1
        query = mock_find.call_args[0][0]
        assert query["user_id"] == "user-1"
        mock_revoke.assert_awaited_once_with("jti-abc123", "session_revoked", "user-1")

    def test_admin_is_not_scoped_to_a_user(self):
        with patch(
            "src.storage.documents.active_token.ActiveTokenDocument.find",
            return_value=_find_chain([]),
        ) as mock_find, patch(
            "src.storage.documents.service_bridge.revoke_token_native",
            new=AsyncMock(),
        ):
            count = _run(revoke_active_tokens_by_prefix_native("jti-abc", None, is_admin=True))

        assert count == 0
        query = mock_find.call_args[0][0]
        assert "user_id" not in query

    def test_no_matches_returns_zero_without_touching_collection(self):
        with patch(
            "src.storage.documents.active_token.ActiveTokenDocument.find",
            return_value=_find_chain([]),
        ), patch(
            "src.storage.documents.active_token.ActiveTokenDocument.get_pymongo_collection",
        ) as mock_get_coll:
            count = _run(revoke_active_tokens_by_prefix_native("jti-abc", "user-1", is_admin=False))
        assert count == 0
        mock_get_coll.assert_not_called()


class TestRevokeTokenNative:
    def test_inserts_when_not_already_revoked(self):
        coll = MagicMock()
        coll.insert_one = AsyncMock()
        with patch(
            "src.storage.documents.revoked_token.RevokedTokenDocument.get",
            new=AsyncMock(return_value=None),
        ), patch(
            "src.storage.documents.revoked_token.RevokedTokenDocument.get_pymongo_collection",
            return_value=coll,
        ):
            _run(revoke_token_native("jti-1", "logout", "user-1"))
        coll.insert_one.assert_awaited_once()
        doc = coll.insert_one.call_args[0][0]
        assert doc["_id"] == "jti-1"
        assert doc["reason"] == "logout"
        assert doc["user_id"] == "user-1"

    def test_is_idempotent_when_already_revoked(self):
        coll = MagicMock()
        coll.insert_one = AsyncMock()
        with patch(
            "src.storage.documents.revoked_token.RevokedTokenDocument.get",
            new=AsyncMock(return_value=SimpleNamespace(id="jti-1")),
        ), patch(
            "src.storage.documents.revoked_token.RevokedTokenDocument.get_pymongo_collection",
            return_value=coll,
        ):
            _run(revoke_token_native("jti-1", "logout", "user-1"))
        coll.insert_one.assert_not_awaited()


class TestVerifyOtpNative:
    """verify_otp_native() iterates candidates (async for coll.find(...))
    instead of a single find_one — the salt is per-record so the hash can't
    be queried directly, see _hash_otp_code's docstring in service_bridge.py."""

    def test_valid_code_marks_used_and_returns_true(self):
        salt = "abc123"

        async def _candidates(*_a, **_kw):
            yield {"_id": "pv-1", "salt": salt, "code_hash": _hash_otp_code("123456", salt)}

        coll = MagicMock()
        coll.find = _candidates
        coll.update_one = AsyncMock()
        with patch(
            "src.storage.documents.password_verification.PasswordVerificationDocument.get_pymongo_collection",
            return_value=coll,
        ):
            result = _run(verify_otp_native("user-1", "123456"))
        assert result is True
        coll.update_one.assert_awaited_once_with({"_id": "pv-1"}, {"$set": {"used": True}})

    def test_wrong_code_against_real_candidate_returns_false(self):
        salt = "abc123"

        async def _candidates(*_a, **_kw):
            yield {"_id": "pv-1", "salt": salt, "code_hash": _hash_otp_code("123456", salt)}

        coll = MagicMock()
        coll.find = _candidates
        coll.update_one = AsyncMock()
        with patch(
            "src.storage.documents.password_verification.PasswordVerificationDocument.get_pymongo_collection",
            return_value=coll,
        ):
            result = _run(verify_otp_native("user-1", "000000"))
        assert result is False
        coll.update_one.assert_not_awaited()

    def test_no_candidates_returns_false(self):
        async def _candidates(*_a, **_kw):
            return
            yield  # pragma: no cover — makes this an async generator with 0 items

        coll = MagicMock()
        coll.find = _candidates
        coll.update_one = AsyncMock()
        with patch(
            "src.storage.documents.password_verification.PasswordVerificationDocument.get_pymongo_collection",
            return_value=coll,
        ):
            result = _run(verify_otp_native("user-1", "000000"))
        assert result is False
        coll.update_one.assert_not_awaited()


class TestGenerateResetLinkNative:
    def test_invalidates_prior_links_and_emails_new_one(self):
        user_doc = SimpleNamespace(id="user-1", email="a@biat-it.tn")
        coll = MagicMock()
        coll.update_many = AsyncMock()
        coll.insert_one = AsyncMock()
        with patch(
            "src.storage.documents.password_verification.PasswordVerificationDocument.get_pymongo_collection",
            return_value=coll,
        ), patch(
            "src.services.email_service.send_reset_link_email",
        ) as mock_send:
            link = _run(generate_reset_link_native(user_doc, "FORGOT_PASSWORD"))

        assert "token=" in link
        coll.update_many.assert_awaited_once()
        coll.insert_one.assert_awaited_once()
        mock_send.assert_called_once()


class TestVerifyResetTokenNative:
    def test_valid_token_marks_used_and_returns_user(self):
        user = SimpleNamespace(id="user-1")
        coll = MagicMock()
        coll.find_one = AsyncMock(return_value={"_id": "pv-1", "user_id": "user-1"})
        coll.update_one = AsyncMock()
        with patch(
            "src.storage.documents.password_verification.PasswordVerificationDocument.get_pymongo_collection",
            return_value=coll,
        ), patch(
            "src.storage.documents.user.UserDocument.find_one",
            new=AsyncMock(return_value=user),
        ):
            result = _run(verify_reset_token_native("some-token"))
        assert result is user
        coll.update_one.assert_awaited_once_with({"_id": "pv-1"}, {"$set": {"used": True}})

    def test_invalid_token_returns_none(self):
        coll = MagicMock()
        coll.find_one = AsyncMock(return_value=None)
        with patch(
            "src.storage.documents.password_verification.PasswordVerificationDocument.get_pymongo_collection",
            return_value=coll,
        ):
            result = _run(verify_reset_token_native("bad-token"))
        assert result is None


class TestUpdateUserAdminNative:
    def test_returns_none_when_user_not_found(self):
        with patch(
            "src.storage.documents.service_bridge._get_by_str_id",
            new=AsyncMock(return_value=None),
        ):
            result = _run(update_user_admin_native("user-1", "Admin", None, None))
        assert result is None

    def test_blocks_deactivating_last_active_admin(self):
        user = SimpleNamespace(id="user-1", role="Admin")
        with patch(
            "src.storage.documents.service_bridge._get_by_str_id",
            new=AsyncMock(return_value=user),
        ), patch(
            "src.storage.documents.user.UserDocument.find",
            return_value=_find_chain([user]),  # count() -> 1 active admin
        ):
            result = _run(update_user_admin_native("user-1", None, False, None))
        assert result == "LAST_ADMIN"

    def test_allows_deactivating_when_other_admins_remain(self):
        user = SimpleNamespace(id="user-1", role="Admin")
        coll = MagicMock()
        coll.update_one = AsyncMock()
        with patch(
            "src.storage.documents.service_bridge._get_by_str_id",
            new=AsyncMock(return_value=user),
        ), patch(
            "src.storage.documents.user.UserDocument.find",
            return_value=_find_chain([user, SimpleNamespace(id="user-2")]),  # 2 active admins
        ), patch(
            "src.storage.documents.user.UserDocument.get_pymongo_collection",
            return_value=coll,
        ):
            result = _run(update_user_admin_native("user-1", None, False, None))
        assert result is user
        coll.update_one.assert_awaited_once_with({"_id": "user-1"}, {"$set": {"is_active": False}})

    def test_updates_role_and_departement_without_touching_active_status(self):
        user = SimpleNamespace(id="user-1", role="Comptable")
        coll = MagicMock()
        coll.update_one = AsyncMock()
        with patch(
            "src.storage.documents.service_bridge._get_by_str_id",
            new=AsyncMock(return_value=user),
        ), patch(
            "src.storage.documents.user.UserDocument.get_pymongo_collection",
            return_value=coll,
        ):
            _run(update_user_admin_native("user-1", "Direction", None, "IT"))
        update = coll.update_one.call_args[0][1]["$set"]
        assert update == {"role": "Direction", "departement": "IT"}


class TestUpdateUserProfileNative:
    def test_returns_none_when_user_not_found(self):
        with patch(
            "src.storage.documents.user.UserDocument.find_one",
            new=AsyncMock(return_value=None),
        ):
            result = _run(update_user_profile_native("nobody@biat-it.tn", "Nom", None, None))
        assert result is None

    def test_updates_only_provided_fields(self):
        user = SimpleNamespace(id="user-1", email="a@biat-it.tn")
        coll = MagicMock()
        coll.update_one = AsyncMock()
        with patch(
            "src.storage.documents.user.UserDocument.find_one",
            new=AsyncMock(return_value=user),
        ), patch(
            "src.storage.documents.user.UserDocument.get_pymongo_collection",
            return_value=coll,
        ):
            _run(update_user_profile_native("a@biat-it.tn", "NouveauNom", None, None))
        update = coll.update_one.call_args[0][1]["$set"]
        assert update == {"nom": "NouveauNom"}


class TestUpdateUserAvatarNative:
    def test_returns_none_when_user_not_found(self):
        with patch(
            "src.storage.documents.user.UserDocument.find_one",
            new=AsyncMock(return_value=None),
        ):
            result = _run(update_user_avatar_native("nobody@biat-it.tn", "data:image/png;base64,xx"))
        assert result is None

    def test_sets_profile_picture(self):
        user = SimpleNamespace(id="user-1", email="a@biat-it.tn")
        coll = MagicMock()
        coll.update_one = AsyncMock()
        with patch(
            "src.storage.documents.user.UserDocument.find_one",
            new=AsyncMock(return_value=user),
        ), patch(
            "src.storage.documents.user.UserDocument.get_pymongo_collection",
            return_value=coll,
        ):
            _run(update_user_avatar_native("a@biat-it.tn", "data:image/png;base64,xx"))
        coll.update_one.assert_awaited_once_with(
            {"_id": "user-1"}, {"$set": {"profile_picture": "data:image/png;base64,xx"}},
        )


class TestUnlockAccountNative:
    def test_returns_none_when_user_not_found(self):
        with patch(
            "src.storage.documents.service_bridge._get_by_str_id",
            new=AsyncMock(return_value=None),
        ):
            result = _run(unlock_account_native("user-1"))
        assert result is None

    def test_clears_lockout_fields(self):
        user = SimpleNamespace(id="user-1")
        coll = MagicMock()
        coll.update_one = AsyncMock()
        with patch(
            "src.storage.documents.service_bridge._get_by_str_id",
            new=AsyncMock(return_value=user),
        ), patch(
            "src.storage.documents.user.UserDocument.get_pymongo_collection",
            return_value=coll,
        ):
            result = _run(unlock_account_native("user-1"))
        assert result is user
        coll.update_one.assert_awaited_once_with(
            {"_id": "user-1"},
            {"$set": {"failed_login_attempts": 0, "locked_until": None, "last_failed_login": None}},
        )
