"""Unit tests — JWT_SECRET startup validation (api.security.jwt_handler).

Covers Fix 1 of the security audit: the app must never fall back to a
hardcoded/default JWT secret. `_validate_secret()` runs at module import time
(i.e. before the FastAPI app object is even built), so an invalid secret
must make the process fail to start rather than silently default.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from api.security import jwt_handler

_BACKEND_DIR = Path(__file__).resolve().parents[2]


class TestValidateSecretFunction:
    """Direct checks on the pure validation function."""

    def test_none_raises(self):
        with pytest.raises(RuntimeError, match="n'est pas défini"):
            jwt_handler._validate_secret(None)

    def test_empty_string_raises(self):
        with pytest.raises(RuntimeError, match="n'est pas défini"):
            jwt_handler._validate_secret("")

    def test_too_short_raises(self):
        with pytest.raises(RuntimeError, match="trop court"):
            jwt_handler._validate_secret("short-secret")

    def test_known_hardcoded_fallback_raises(self):
        # Only 27 chars — caught by the length check before the default check,
        # which is fine: either way it must never be accepted.
        with pytest.raises(RuntimeError, match="trop court"):
            jwt_handler._validate_secret("biat_local_only_secret_2026")

    def test_env_example_placeholder_raises(self):
        with pytest.raises(RuntimeError, match="valeur par défaut"):
            jwt_handler._validate_secret("change-me-in-production-min-32-chars")

    def test_low_entropy_raises(self):
        with pytest.raises(RuntimeError, match="entropie"):
            jwt_handler._validate_secret("a" * 40)

    def test_valid_secret_passes(self):
        secret = "a-perfectly-fine-random-secret-value-1234"
        assert jwt_handler._validate_secret(secret) == secret


class TestAppFailsToStartWithoutSecret:
    """End-to-end: importing the module in a fresh process with a bad/missing
    JWT_SECRET must abort the process instead of silently defaulting."""

    def _run_import(self, jwt_secret: str) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        # Present-but-empty so python-dotenv (override=False) does not backfill
        # the real .env's valid secret from the repo root during this subprocess.
        env["JWT_SECRET"] = jwt_secret
        return subprocess.run(
            [sys.executable, "-c", "import api.security.jwt_handler"],
            cwd=str(_BACKEND_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_unset_jwt_secret_fails_to_start(self):
        result = self._run_import("")
        assert result.returncode != 0
        assert "JWT_SECRET" in result.stderr

    def test_hardcoded_default_fails_to_start(self):
        result = self._run_import("change-me-in-production-min-32-chars")
        assert result.returncode != 0
        assert "JWT_SECRET" in result.stderr

    def test_valid_secret_starts_cleanly(self):
        result = self._run_import("a-perfectly-fine-random-secret-value-1234")
        assert result.returncode == 0, result.stderr
