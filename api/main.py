"""BIAT IT Billing Agent — FastAPI REST layer.

Start with:
    uvicorn api.main:app --reload --port 8000
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from api.auth import SECRET, get_current_user
from api.limiter import limiter

_log = logging.getLogger(__name__)

from api.routers import invoices, review, journal, budget, capex, kpi, billing, nl_query, suivi, notifications, projects
from api.routers import auth as auth_router
from api.routers import admin, users, roadmap, projet_budget, livrables, bct_export, audit

_PROTECTED = [Depends(get_current_user)]

_TAGS: list[dict] = [
    {"name": "auth",           "description": "Authentification et gestion des sessions JWT"},
    {"name": "invoices",       "description": "Factures fournisseurs — pipeline OCR+LLM, révision humaine"},
    {"name": "journal",        "description": "Journal comptable PCE tunisien — écritures en partie double"},
    {"name": "assets",         "description": "Immobilisations CAPEX — registre et plan d'amortissement"},
    {"name": "client-invoices","description": "Facturation client intra-groupe — génération et suivi"},
    {"name": "projects",       "description": "Chartes de projet, phases et livrables"},
    {"name": "budget",         "description": "Lignes budgétaires par projet — prévu vs consommé"},
    {"name": "roadmap",        "description": "Feuille de route IT 2026 — jalons et priorités"},
    {"name": "admin",          "description": "Gestion des utilisateurs et habilitations — ADMIN uniquement"},
    {"name": "analytics",      "description": "Tableaux de bord, KPIs, suivi de trésorerie, requêtes NL"},
    {"name": "notifications",  "description": "Notifications persistantes — alertes factures et budget"},
    {"name": "bct-export",     "description": "Conformité BCT — Circulaire 2025-13 : suivi rapatriement exports, rapport signé SHA-256"},
]


@asynccontextmanager
async def _lifespan(app: FastAPI):
    _startup()
    yield


def _startup() -> None:
    # Warn if JWT secret is below recommended minimum length for HMAC-SHA256
    if len(SECRET) < 32:
        _log.warning(
            "⚠️  JWT_SECRET est trop court (%d octets — minimum recommandé : 32). "
            "Définir JWT_SECRET dans les variables d'environnement avant la mise en production.",
            len(SECRET),
        )

    # Warn if DB is not at the latest Alembic revision
    db_url = os.getenv("DATABASE_URL", "sqlite:///./data/invoices.db")
    if ":memory:" in db_url:
        return

    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        from sqlalchemy import create_engine, text

        alembic_cfg = Config("alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", db_url)
        script = ScriptDirectory.from_config(alembic_cfg)
        head_rev = script.get_current_head()

        engine = create_engine(db_url)
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT version_num FROM alembic_version LIMIT 1")
            ).scalar_one_or_none()
        engine.dispose()

        if result != head_rev:
            _log.warning(
                "⚠️  Base de données en retard sur les migrations Alembic. "
                "Révision actuelle : %s — Head : %s. "
                "Exécuter : alembic upgrade head",
                result, head_rev,
            )
        else:
            _log.info("✓ Base de données à jour (révision %s).", result)
    except Exception as exc:
        _log.warning("Impossible de vérifier les migrations Alembic : %s", exc)


app = FastAPI(
    title="BIAT IT Billing Agent API",
    version="1.0.0",
    description=(
        "Système de facturation intelligent pour BIAT IT. "
        "Automatisation OCR+LLM des factures fournisseurs, "
        "génération d'écritures PCE tunisiennes, gestion CAPEX. "
        "Toute l'inférence IA est locale via Ollama — aucune donnée n'est transmise au cloud."
    ),
    contact={"name": "BIAT IT", "email": "it@biat.com.tn"},
    openapi_tags=_TAGS,
    lifespan=_lifespan,
)

# ── Rate limiting ─────────────────────────────────────────────────────────────
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)


async def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": "Trop de tentatives. Réessayez dans 60 secondes."},
    )


app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)

# CORS: allow Vite dev server origins only; in Docker the SPA is served
# from the same origin so the wildcard is never needed in production.
_CORS_ORIGINS = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:5173,http://localhost:5174,http://localhost:4173",
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
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
app.include_router(projects.router,        prefix="/api", dependencies=_PROTECTED)
app.include_router(admin.router,           prefix="/api", dependencies=_PROTECTED)
app.include_router(users.router,           prefix="/api", dependencies=_PROTECTED)
app.include_router(roadmap.router,         prefix="/api", dependencies=_PROTECTED)
app.include_router(projet_budget.router,   prefix="/api", dependencies=_PROTECTED)
app.include_router(livrables.router,       prefix="/api", dependencies=_PROTECTED)
app.include_router(bct_export.router,      prefix="/api", dependencies=_PROTECTED)
app.include_router(audit.router,           prefix="/api", dependencies=_PROTECTED)
app.include_router(kpi.analytics_router,   prefix="/api", dependencies=_PROTECTED)


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
