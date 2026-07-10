"""Integration test — PATCH /users/me/avatar rate limiting.

Runs the actual check in a clean subprocess rather than reloading modules
in-process. Two reasons:
  1. Rate-limit state is baked into route decorators at import time (see
     api/limiter.py: `_ENABLED` is read from RATE_LIMIT_ENABLED once, at
     module import). test_api_e2e.py sets RATE_LIMIT_ENABLED=false before
     importing the real app, and since pytest runs the whole suite in one
     process, whichever test module imports api.limiter first fixes that
     constant for every test that follows.
  2. importlib.reload() is not a safe workaround for (1): slowapi's
     Limiter registers each decorated route under a plain
     f"{module}.{qualname}" string key that accumulates across repeated
     decorations of the same function name — reloading the router module
     N times makes the same endpoint's hit count increase by N+1 per
     request (verified experimentally), a pure test artifact with no
     bearing on real behavior (the app is only ever imported once in
     production).
A fresh subprocess with RATE_LIMIT_ENABLED=true set before any import
sidesteps both problems entirely.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap

_CHILD_SCRIPT = textwrap.dedent(
    """
    import os
    os.environ["RATE_LIMIT_ENABLED"] = "true"

    from datetime import datetime, timezone
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded

    import api.limiter as limiter_module
    import api.routers.users as users_module
    from api.auth import get_current_user

    app = FastAPI()
    app.state.limiter = limiter_module.limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(users_module.router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: {
        "email": "test@biat-it.tn", "role": "Comptable",
    }
    client = TestClient(app, raise_server_exceptions=True)

    fake_user = SimpleNamespace(
        id="u1", nom="Test", prenom="User", email="test@biat-it.tn",
        role="Comptable", departement="IT",
        created_at=datetime.now(timezone.utc), profile_picture=None,
    )
    body = {"avatar": "data:image/png;base64,aGVsbG8="}

    with patch(
        "src.storage.documents.service_bridge.update_user_avatar_native",
        new=AsyncMock(return_value=fake_user),
    ):
        statuses = [client.patch("/api/users/me/avatar", json=body).status_code for _ in range(11)]

    assert statuses[:10] == [200] * 10, f"expected 10 successes, got {statuses[:10]}"
    assert statuses[10] == 429, f"expected 11th request to be rate-limited, got {statuses[10]}"
    print("OK")
    """
)


class TestAvatarUploadRateLimit:
    def test_11th_request_within_a_minute_is_rejected_with_429(self):
        result = subprocess.run(
            [sys.executable, "-c", _CHILD_SCRIPT],
            cwd="backend",
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"subprocess failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "OK" in result.stdout
