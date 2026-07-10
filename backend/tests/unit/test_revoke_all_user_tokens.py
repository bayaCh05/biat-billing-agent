"""Unit tests — src.storage.documents.service_bridge.revoke_all_user_tokens_native.

Post-audit follow-up fix: password-change/reset flows (OTP, reset-link,
admin-forced reset, direct change-password) previously never revoked other
active sessions, so a JWT stolen before the change stayed valid indefinitely.

This is the core primitive all 4 call sites share — mock everything below
(no real Mongo), per CLAUDE.md unit-test conventions.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.storage.documents.service_bridge import revoke_all_user_tokens_native


def _fake_find(tokens):
    find_result = MagicMock()
    find_result.to_list = AsyncMock(return_value=tokens)
    return find_result


class TestRevokeAllUserTokensNative:
    def test_revokes_every_active_token_and_returns_count(self):
        tokens = [SimpleNamespace(id="jti-1"), SimpleNamespace(id="jti-2")]
        coll = MagicMock()
        coll.update_many = AsyncMock()

        with (
            patch(
                "src.storage.documents.active_token.ActiveTokenDocument.find",
                return_value=_fake_find(tokens),
            ) as mock_find,
            patch(
                "src.storage.documents.active_token.ActiveTokenDocument.get_pymongo_collection",
                return_value=coll,
            ),
            patch("api.security.jwt_handler.revoke_token", new=AsyncMock()) as mock_revoke,
        ):
            count = asyncio.run(revoke_all_user_tokens_native("user-1", reason="test_reason"))

        assert count == 2
        assert mock_revoke.await_count == 2
        mock_revoke.assert_any_call("jti-1", "test_reason", "user-1")
        mock_revoke.assert_any_call("jti-2", "test_reason", "user-1")
        coll.update_many.assert_awaited_once()
        update_filter = coll.update_many.call_args[0][0]
        assert set(update_filter["_id"]["$in"]) == {"jti-1", "jti-2"}

        query = mock_find.call_args[0][0]
        assert query["user_id"] == "user-1"
        assert "_id" not in query  # no except_jti -> no exclusion clause

    def test_excludes_current_jti_when_given(self):
        with (
            patch(
                "src.storage.documents.active_token.ActiveTokenDocument.find",
                return_value=_fake_find([]),
            ) as mock_find,
            patch("api.security.jwt_handler.revoke_token", new=AsyncMock()),
        ):
            asyncio.run(revoke_all_user_tokens_native("user-1", except_jti="jti-keep-me"))

        query = mock_find.call_args[0][0]
        assert query["_id"] == {"$ne": "jti-keep-me"}

    def test_no_active_tokens_is_a_noop_and_returns_zero(self):
        with (
            patch(
                "src.storage.documents.active_token.ActiveTokenDocument.find",
                return_value=_fake_find([]),
            ),
            patch(
                "src.storage.documents.active_token.ActiveTokenDocument.get_pymongo_collection",
            ) as mock_get_coll,
            patch("api.security.jwt_handler.revoke_token", new=AsyncMock()) as mock_revoke,
        ):
            count = asyncio.run(revoke_all_user_tokens_native("user-1"))

        assert count == 0
        mock_revoke.assert_not_awaited()
        mock_get_coll.assert_not_called()  # nothing to bulk-update
