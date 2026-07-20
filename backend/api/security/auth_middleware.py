"""Baseline authentication safety net for all /api/* routes.

Every protected router in api/main.py is already included with
`dependencies=_PROTECTED` (= Depends(get_current_user)), which FastAPI
applies to every route registered through that include_router() call —
verified live: an unauthenticated GET /api/kpi (no Depends of its own)
correctly returns 401. That mechanism works and is the idiomatic FastAPI
pattern (it integrates with OpenAPI docs and dependency-override testing
in a way raw ASGI middleware doesn't).

What it does NOT protect against: a *future* router registered in main.py
via `app.include_router(new_router, prefix="/api")` without remembering to
also pass `dependencies=_PROTECTED`. This middleware closes that residual
gap at the ASGI level, independent of anyone remembering the per-router
parameter — it runs before routing/dependency resolution even happens, so
it protects a brand-new, entirely unprotected router automatically.

This checks authentication only (a valid, non-revoked access token) — it
does NOT replace require_role() for role-specific authorization, which
stays a per-route concern.
"""
from __future__ import annotations

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

# Only these /api/* paths may be called with no token at all — every other
# /api/* path requires a valid access token, even if the route itself (or
# its router's own dependencies=) doesn't already enforce that.
_PUBLIC_API_PATHS = frozenset({
    "/api/health",
    "/api/health/live",
    "/api/health/ready",
    "/api/auth/login",
    "/api/auth/refresh",
    "/api/auth/forgot-password",
    "/api/auth/reset-password",
})


class RequireAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if (
            request.method == "OPTIONS"          # CORS preflight — CORSMiddleware handles this
            or not path.startswith("/api/")      # SPA static files, /docs, /openapi.json, /redoc
            or path in _PUBLIC_API_PATHS
        ):
            return await call_next(request)

        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)

        from api.security.jwt_handler import verify_access_token
        payload = await verify_access_token(auth_header[len("Bearer "):])
        if payload is None:
            return JSONResponse(
                {"detail": "Token invalide ou révoqué — reconnectez-vous."},
                status_code=401,
            )

        return await call_next(request)
