"""HTTP security headers middleware."""
from __future__ import annotations

import os

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

# Activer HSTS uniquement en production HTTPS (désactivé par défaut en dev)
_ENABLE_HSTS = os.getenv("ENABLE_HSTS", "false").lower() == "true"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        # script-src sans 'unsafe-inline' — les builds React/Vite n'utilisent pas
        # de scripts inline en production. 'unsafe-inline' dans style-src est conservé
        # car les librairies UI (Recharts, lucide-react) injectent des styles inline.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "connect-src 'self' http://localhost:11434 http://localhost:8000"
        )
        if _ENABLE_HSTS:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        for hdr in ("server", "x-powered-by"):
            if hdr in response.headers:
                del response.headers[hdr]
        return response
