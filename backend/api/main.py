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

from api.auth import get_current_user, seed_demo_users, validate_demo_users, refresh_demo_passwords
from api.limiter import limiter
from api.security.security_headers import SecurityHeadersMiddleware
from src.storage.mongodb import close_mongodb, init_beanie

_log = logging.getLogger(__name__)

from api.routers import invoices, review, journal, budget, capex, kpi, billing, nl_query, suivi, notifications, projects, payments
from api.routers import auth as auth_router
from api.routers import admin, users, roadmap, projet_budget, livrables, audit, risks, security as security_router
from api.routers import ai as ai_router
from api.routers import audit_reports

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
    {"name": "risks",          "description": "Gestion des risques projet — matrice probabilité × impact"},
    {"name": "audit-reports",  "description": "Rapports d'audit périodiques transversaux (Audit Agent) — distinct de /audit (intégrité HMAC)"},
]


@asynccontextmanager
async def _lifespan(app: FastAPI):
    _startup()
    await init_beanie()
    from api.scheduler import start_scheduler, stop_scheduler
    start_scheduler()
    yield
    stop_scheduler()
    await close_mongodb()


def _startup() -> None:
    from src.utils.logging import configure_logging

    configure_logging(
        level=os.getenv("LOG_LEVEL", "INFO"),
        log_file=os.getenv("LOG_FILE") or None,
    )

    # Validate demo user env vars
    validate_demo_users()

    # Seed demo accounts into the DB so login, reset link and password change
    # all use the same backend path in local development. DISABLE_DEMO_USERS=true
    # skips this entirely (see validate_demo_users()'s own check above) — without
    # this gate, demo accounts were silently re-created/unlocked on every restart
    # even with the flag set, contradicting its documented purpose.
    if os.getenv("DISABLE_DEMO_USERS", "false").lower() != "true":
        try:
            from api.deps import get_session_ctx

            with get_session_ctx() as session:
                seed_demo_users(session)
                refresh_demo_passwords(session)
        except Exception as exc:
            _log.warning("Impossible de préparer les comptes démo en base : %s", exc)

    # JWT_SECRET itself is validated at import time in api.security.jwt_handler
    # (_validate_secret) — the app fails to start entirely if it's missing, too
    # short, or a known placeholder, so no redundant check is needed here.

    # Warn if AUDIT_HMAC_SECRET is missing (fallback sur JWT_SECRET = clés non séparées)
    if not os.getenv("AUDIT_HMAC_SECRET", "").strip():
        _log.warning(
            "⚠️  AUDIT_HMAC_SECRET non défini — la clé HMAC de l'audit trail utilise JWT_SECRET "
            "par défaut. Définir AUDIT_HMAC_SECRET séparément dans .env pour isoler les deux secrets."
        )

    # Fail fast if LDAP is enabled but LDAP_BIND_PASSWORD is missing — no
    # hardcoded fallback (see src/services/ldap_service.py). Checked here
    # rather than at import time because that module is only imported lazily,
    # on the first LDAP login attempt — this way a misconfiguration is caught
    # at startup instead of on some user's first login.
    auth_mode = os.getenv("AUTH_MODE", "local").lower()
    if auth_mode in ("ldap", "hybrid") and not os.getenv("LDAP_BIND_PASSWORD", "").strip():
        raise RuntimeError(
            f"AUTH_MODE={auth_mode} nécessite LDAP_BIND_PASSWORD, qui n'est pas défini. "
            "Définissez-le dans .env avant de démarrer."
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

    # Index PCE tunisien dans ChromaDB pour la classification RAG (Pass C).
    # Désactivé par défaut pour éviter de télécharger/charger le modèle
    # sentence-transformers à chaque reload local.
    if os.getenv("PCE_VECTORSTORE_AUTO_INDEX", "false").lower() == "true":
        try:
            from api.deps import get_catalog
            from src.ai_agents.rag.pce_vectorstore import PCEVectorStore
            catalog = get_catalog()
            store   = PCEVectorStore.get()
            if store.available:
                entries = catalog.all_entries()
                store.initialize_pce(entries)
                _log.info("✓ PCE vectorstore prêt (%d entrées indexées).", len(entries))
            else:
                _log.warning("⚠️  ChromaDB indisponible — classification RAG désactivée.")
        except Exception as exc:
            _log.warning("Impossible d'initialiser le vectorstore PCE : %s", exc)
    else:
        _log.info(
            "Indexation PCE vectorstore ignorée au démarrage "
            "(PCE_VECTORSTORE_AUTO_INDEX=false)."
        )


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

# Security headers on all responses
app.add_middleware(SecurityHeadersMiddleware)

# CORS: restrict to known frontend origins only
_CORS_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://localhost:5174,http://localhost:4173",
    ).split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    expose_headers=["X-Total-Count", "X-Request-ID"],
    max_age=600,
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
app.include_router(payments.router,      prefix="/api", dependencies=_PROTECTED)
app.add_api_route(
    "/api/installments/{installment_id}/mark-paid",
    payments.mark_paid,
    methods=["PATCH"],
    tags=["payments"],
    dependencies=_PROTECTED,
)
app.include_router(notifications.router, prefix="/api", dependencies=_PROTECTED)
app.include_router(projects.router,        prefix="/api", dependencies=_PROTECTED)
app.include_router(admin.router,           prefix="/api", dependencies=_PROTECTED)
app.include_router(users.router,           prefix="/api", dependencies=_PROTECTED)
app.include_router(roadmap.router,         prefix="/api", dependencies=_PROTECTED)
app.include_router(projet_budget.router,   prefix="/api", dependencies=_PROTECTED)
app.include_router(livrables.router,       prefix="/api", dependencies=_PROTECTED)
app.include_router(audit.router,           prefix="/api", dependencies=_PROTECTED)
app.include_router(kpi.analytics_router,   prefix="/api", dependencies=_PROTECTED)
app.include_router(risks.router,            prefix="/api", dependencies=_PROTECTED)
app.include_router(ai_router.router,        prefix="/api", dependencies=_PROTECTED)
app.include_router(audit_reports.router,    prefix="/api", dependencies=_PROTECTED)
app.include_router(security_router.router,  prefix="/api", dependencies=_PROTECTED)


@app.get("/api/health", tags=["admin"])
def health():
    from datetime import datetime, timezone
    status = "ok"
    components: dict = {}

    # Database check
    try:
        from api.deps import get_engine
        from sqlalchemy import text
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        components["database"] = "ok"
    except Exception:
        components["database"] = "error"
        status = "degraded"

    # MongoDB check — MONGODB_URI absent est un mode SQLite-only documenté, pas une panne
    from src.storage.mongodb import MONGODB_URI
    if not MONGODB_URI:
        components["mongodb"] = "not_configured"
    else:
        try:
            from src.storage.sync_mongo_repository import _get_db
            _get_db().client.admin.command("ping")
            components["mongodb"] = "ok"
        except Exception:
            components["mongodb"] = "error"
            status = "degraded"

    # Ollama check
    try:
        from src.ai_agents.ollama_client import OllamaClient
        components["ollama"] = "ok" if OllamaClient.get().is_available() else "unavailable"
    except Exception:
        components["ollama"] = "unavailable"

    # Scheduler check
    try:
        from api.scheduler import get_scheduler
        sched = get_scheduler()
        components["scheduler"] = "ok" if (sched and sched.running) else "stopped"
    except Exception:
        components["scheduler"] = "unknown"

    return {
        "status": status,
        "version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "components": components,
    }


@app.get("/api/health/live", tags=["admin"], summary="Liveness probe")
def health_live():
    """Kubernetes liveness : l'application est démarrée et répond."""
    return {"status": "ok"}


@app.get("/api/health/ready", tags=["admin"], summary="Readiness probe")
def health_ready():
    """Kubernetes readiness : l'application peut recevoir du trafic (au moins un store disponible).

    SQLite et MongoDB coexistent durant la migration — on n'échoue la sonde que si
    les DEUX sont indisponibles, pas si un seul l'est (voir CLAUDE.md "MongoDB
    Migration Status" pour la répartition des domaines entre les deux stores).
    """
    sqlite_ok = False
    try:
        from api.deps import get_engine
        from sqlalchemy import text as _text
        with get_engine().connect() as conn:
            conn.execute(_text("SELECT 1"))
        sqlite_ok = True
    except Exception:
        pass

    mongo_ok = False
    try:
        from src.storage.sync_mongo_repository import _get_db
        _get_db().client.admin.command("ping")
        mongo_ok = True
    except Exception:
        pass

    if sqlite_ok or mongo_ok:
        return {"status": "ready", "sqlite": sqlite_ok, "mongodb": mongo_ok}

    from fastapi import Response
    return Response(
        content='{"status":"not_ready","reason":"no_datastore_available"}',
        status_code=503,
        media_type="application/json",
    )


# ── Serve React SPA (production / Docker) ─────────────────────────────────────
# Only mounted when the compiled dist/ directory is present.
# In local dev the Vite dev server handles the frontend separately.
_DIST = Path(__file__).parent.parent.parent / "frontend" / "dist"

if _DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(_DIST / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_spa(full_path: str) -> FileResponse:  # noqa: ARG001
        return FileResponse(str(_DIST / "index.html"))
