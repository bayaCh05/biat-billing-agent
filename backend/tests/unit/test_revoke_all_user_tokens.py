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

from api.security.jwt_handler import revoke_token
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
            patch(
                "src.storage.documents.refresh_token.RefreshTokenDocument.find",
                return_value=_fake_find([]),
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
            patch(
                "src.storage.documents.refresh_token.RefreshTokenDocument.find",
                return_value=_fake_find([]),
            ),
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
            patch(
                "src.storage.documents.refresh_token.RefreshTokenDocument.find",
                return_value=_fake_find([]),
            ),
            patch("api.security.jwt_handler.revoke_token", new=AsyncMock()) as mock_revoke,
        ):
            count = asyncio.run(revoke_all_user_tokens_native("user-1"))

        assert count == 0
        mock_revoke.assert_not_awaited()
        mock_get_coll.assert_not_called()  # nothing to bulk-update

    def test_revokes_every_distinct_refresh_family_and_adds_to_count(self):
        refresh_rows = [
            SimpleNamespace(family_id="fam-1"),
            SimpleNamespace(family_id="fam-1"),
            SimpleNamespace(family_id="fam-2"),
        ]
        with (
            patch(
                "src.storage.documents.active_token.ActiveTokenDocument.find",
                return_value=_fake_find([]),
            ),
            patch(
                "src.storage.documents.refresh_token.RefreshTokenDocument.find",
                return_value=_fake_find(refresh_rows),
            ) as mock_refresh_find,
            patch(
                "src.storage.documents.service_bridge.revoke_refresh_family_native",
                new=AsyncMock(return_value=2),
            ) as mock_revoke_family,
        ):
            count = asyncio.run(revoke_all_user_tokens_native("user-1", reason="password_change"))

        # Deux familles distinctes malgré 3 lignes -> une seule révocation par famille.
        assert mock_revoke_family.await_count == 2
        called_families = {c.args[0] for c in mock_revoke_family.await_args_list}
        assert called_families == {"fam-1", "fam-2"}
        for c in mock_revoke_family.await_args_list:
            assert c.args[1] == "password_change"
        assert count == 4  # 0 access + 2 familles * 2 (valeur mockée par appel)

        query = mock_refresh_find.call_args[0][0]
        assert query["user_id"] == "user-1"

    def test_except_jti_does_not_exclude_refresh_families(self):
        """`except_jti` ne s'applique qu'aux access tokens — il n'existe pas de
        correspondance propre entre le jti d'un access token et une famille
        de refresh token sans plomberie supplémentaire (voir docstring de
        revoke_all_user_tokens_native)."""
        refresh_rows = [SimpleNamespace(family_id="fam-keep")]
        with (
            patch(
                "src.storage.documents.active_token.ActiveTokenDocument.find",
                return_value=_fake_find([]),
            ),
            patch(
                "src.storage.documents.refresh_token.RefreshTokenDocument.find",
                return_value=_fake_find(refresh_rows),
            ) as mock_refresh_find,
            patch(
                "src.storage.documents.service_bridge.revoke_refresh_family_native",
                new=AsyncMock(return_value=1),
            ) as mock_revoke_family,
        ):
            asyncio.run(revoke_all_user_tokens_native("user-1", except_jti="jti-keep-me"))

        query = mock_refresh_find.call_args[0][0]
        assert "_id" not in query  # pas de filtre par jti pour les refresh tokens
        mock_revoke_family.assert_awaited_once_with("fam-keep", "password_change")


class TestJwtHandlerRevokeToken:
    """The actual blocklist write revoke_all_user_tokens_native() calls per
    token — verify_access_token() checks RevokedTokenDocument, so this is
    what actually invalidates a JWT (not ActiveTokenDocument.revoked alone).
    Uses get_pymongo_collection()+insert_one, not Document(...).insert() —
    the latter requires Beanie to be initialized just to construct the
    object, which is both untestable here and inconsistent with every other
    write in this codebase (see CLAUDE.md)."""

    def test_inserts_into_blocklist_when_not_already_revoked(self):
        coll = MagicMock()
        coll.insert_one = AsyncMock()
        with (
            patch(
                "src.storage.documents.revoked_token.RevokedTokenDocument.get",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "src.storage.documents.revoked_token.RevokedTokenDocument.get_pymongo_collection",
                return_value=coll,
            ),
        ):
            asyncio.run(revoke_token("jti-1", "logout", "user-1"))

        coll.insert_one.assert_awaited_once()
        doc = coll.insert_one.call_args[0][0]
        assert doc["_id"] == "jti-1"
        assert doc["reason"] == "logout"
        assert doc["user_id"] == "user-1"

    def test_is_idempotent_when_already_revoked(self):
        coll = MagicMock()
        coll.insert_one = AsyncMock()
        with (
            patch(
                "src.storage.documents.revoked_token.RevokedTokenDocument.get",
                new=AsyncMock(return_value=SimpleNamespace(id="jti-1")),
            ),
            patch(
                "src.storage.documents.revoked_token.RevokedTokenDocument.get_pymongo_collection",
                return_value=coll,
            ),
        ):
            asyncio.run(revoke_token("jti-1", "logout", "user-1"))

        coll.insert_one.assert_not_awaited()
