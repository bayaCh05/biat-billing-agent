"""BIAT IT Billing Agent — FastAPI REST layer.

Start with:
    uvicorn api.main:app --reload --port 8000
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.auth import get_current_user
from api.routers import invoices, review, journal, budget, capex, kpi, billing, nl_query, suivi, notifications, projects
from api.routers import auth as auth_router

_PROTECTED = [Depends(get_current_user)]

app = FastAPI(
    title="BIAT IT Billing Agent API",
    version="1.0.0",
    description="Local-only REST API for invoice processing. All LLM inference via Ollama.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auth endpoints — no token required
app.include_router(auth_router.router, prefix="/api")

# All other endpoints — JWT required
app.include_router(invoices.router,      prefix="/api", dependencies=_PROTECTED)
app.include_router(review.router,        prefix="/api", dependencies=_PROTECTED)
app.include_router(journal.router,       prefix="/api", dependencies=_PROTECTED)
app.include_router(budget.router,        prefix="/api", dependencies=_PROTECTED)
app.include_router(capex.router,         prefix="/api", dependencies=_PROTECTED)
app.include_router(kpi.router,           prefix="/api", dependencies=_PROTECTED)
app.include_router(billing.router,       prefix="/api", dependencies=_PROTECTED)
app.include_router(nl_query.router,      prefix="/api", dependencies=_PROTECTED)
app.include_router(suivi.router,         prefix="/api", dependencies=_PROTECTED)
app.include_router(notifications.router, prefix="/api", dependencies=_PROTECTED)
app.include_router(projects.router,      prefix="/api", dependencies=_PROTECTED)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "biat-billing-api"}


# ── Serve React SPA (production / Docker) ─────────────────────────────────────
# Only mounted when the compiled dist/ directory is present.
# In local dev the Vite dev server handles the frontend separately.
_DIST = Path(__file__).parent.parent / "frontend" / "dist"

if _DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(_DIST / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_spa(full_path: str) -> FileResponse:  # noqa: ARG001
        return FileResponse(str(_DIST / "index.html"))
