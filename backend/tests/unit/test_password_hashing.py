"""Unit tests — argon2id hashing + bcrypt backward-compatibility + lazy migration."""
from __future__ import annotations

from unittest.mock import MagicMock

import bcrypt
import pytest

from api.auth import hash_password, needs_rehash, verify_password


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def bcrypt_hash():
    """A real bcrypt hash of 'S3cret!pw'."""
    return bcrypt.hashpw(b"S3cret!pw", bcrypt.gensalt()).decode()


@pytest.fixture()
def argon2_hash():
    """A fresh argon2id hash of 'S3cret!pw'."""
    return hash_password("S3cret!pw")


# ── hash_password ──────────────────────────────────────────────────────────────

class TestHashPassword:
    def test_produces_argon2id_prefix(self, argon2_hash):
        assert argon2_hash.startswith("$argon2id$")

    def test_two_hashes_differ(self):
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2  # salt randomisation

    def test_verify_roundtrip(self, argon2_hash):
        assert verify_password("S3cret!pw", argon2_hash) is True

    def test_wrong_password_fails(self, argon2_hash):
        assert verify_password("wrong", argon2_hash) is False


# ── verify_password — argon2id ─────────────────────────────────────────────────

class TestVerifyPasswordArgon2:
    def test_correct_password(self, argon2_hash):
        assert verify_password("S3cret!pw", argon2_hash) is True

    def test_incorrect_password(self, argon2_hash):
        assert verify_password("badpass", argon2_hash) is False

    def test_empty_password_fails(self, argon2_hash):
        assert verify_password("", argon2_hash) is False

    def test_corrupted_hash_returns_false(self):
        assert verify_password("S3cret!pw", "$argon2id$v=19$garbage") is False


# ── verify_password — bcrypt (backward-compat) ────────────────────────────────

class TestVerifyPasswordBcrypt:
    def test_correct_password_against_bcrypt_hash(self, bcrypt_hash):
        assert verify_password("S3cret!pw", bcrypt_hash) is True

    def test_wrong_password_against_bcrypt_hash(self, bcrypt_hash):
        assert verify_password("nope", bcrypt_hash) is False

    def test_2a_prefix_accepted(self):
        raw = bcrypt.hashpw(b"abc123!X", bcrypt.gensalt(prefix=b"2a")).decode()
        assert raw.startswith("$2a$")
        assert verify_password("abc123!X", raw) is True

    def test_corrupted_bcrypt_hash_returns_false(self):
        assert verify_password("S3cret!pw", "$2b$12$corrupted") is False


# ── needs_rehash ──────────────────────────────────────────────────────────────

class TestNeedsRehash:
    def test_bcrypt_2b_needs_rehash(self, bcrypt_hash):
        assert bcrypt_hash.startswith("$2b$")
        assert needs_rehash(bcrypt_hash) is True

    def test_bcrypt_2a_needs_rehash(self):
        raw = bcrypt.hashpw(b"pw", bcrypt.gensalt(prefix=b"2a")).decode()
        assert needs_rehash(raw) is True

    def test_fresh_argon2id_does_not_need_rehash(self, argon2_hash):
        assert needs_rehash(argon2_hash) is False

    def test_argon2id_outdated_params_needs_rehash(self):
        from argon2 import PasswordHasher
        weak_ph = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
        old_hash = weak_ph.hash("pw")
        # Current _PH has stricter params → check_needs_rehash should return True
        assert needs_rehash(old_hash) is True

    def test_garbage_string_returns_false(self):
        assert needs_rehash("notahash") is False


# ── Full lazy-migration flow ───────────────────────────────────────────────────

class TestLazyMigrationFlow:
    """Simulate: login with bcrypt hash → verify → rehash → update in DB."""

    def _make_db_user(self, hashed: str):
        user = MagicMock()
        user.hashed_password = hashed
        user.is_active = True
        user.email = "user@biat-it.tn"
        user.role = "Comptable"
        return user

    def test_bcrypt_hash_is_updated_after_login(self, bcrypt_hash):
        user = self._make_db_user(bcrypt_hash)
        password = "S3cret!pw"

        assert verify_password(password, user.hashed_password)
        if needs_rehash(user.hashed_password):
            user.hashed_password = hash_password(password)

        assert user.hashed_password.startswith("$argon2id$")
        assert verify_password(password, user.hashed_password)

    def test_argon2id_hash_is_not_needlessly_rehashed(self, argon2_hash):
        user = self._make_db_user(argon2_hash)
        original = user.hashed_password
        password = "S3cret!pw"

        assert verify_password(password, user.hashed_password)
        if needs_rehash(user.hashed_password):
            user.hashed_password = hash_password(password)

        assert user.hashed_password == original  # unchanged

    def test_rehashed_password_still_verifies(self, bcrypt_hash):
        password = "S3cret!pw"
        new_hash = hash_password(password)
        assert verify_password(password, new_hash)
        assert not needs_rehash(new_hash)

    def test_wrong_password_does_not_trigger_rehash(self, bcrypt_hash):
        user = self._make_db_user(bcrypt_hash)

        verified = verify_password("wrongpassword", user.hashed_password)
        assert verified is False
        # Migration must NEVER happen on a failed login
        # (calling code only rehashes when verify_password returns True)
        assert user.hashed_password == bcrypt_hash
