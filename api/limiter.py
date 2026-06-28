"""Centralised rate-limiter instance.

Import `limiter` and `limit` from here — never instantiate Limiter elsewhere
so the same in-memory store is shared across all routers.

Usage in a router:
    from fastapi import Request
    from api.limiter import limiter

    @router.post("/login")
    @limiter.limit("5/minute")
    def login(request: Request, body: LoginRequest, ...):
        ...

The `request: Request` parameter is required by slowapi (used to extract
the client IP). FastAPI injects it automatically — no change to callers.
"""
from __future__ import annotations

import os

from slowapi import Limiter
from slowapi.util import get_remote_address

# When RATE_LIMIT_ENABLED=false (e.g. in tests or local dev), swap every
# rule for a permissive ceiling so the decorator is still applied but
# never actually blocks.
_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true"

limiter = Limiter(key_func=get_remote_address)


def limit(rule: str) -> str:
    """Return *rule* when rate limiting is enabled, or '10000/minute' if not."""
    return rule if _ENABLED else "10000/minute"
