"""BIAT IT Billing Agent — FastAPI REST layer.

Start with:
    uvicorn api.main:app --reload --port 8000
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import invoices, review, journal, budget, capex, kpi, billing, nl_query, suivi, notifications

app = FastAPI(
    title="BIAT IT Billing Agent API",
    version="1.0.0",
    description="Local-only REST API for invoice processing. All LLM inference via Ollama.",
)

# Allow all origins for local development (no credentials sent from the SPA)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(invoices.router, prefix="/api")
app.include_router(review.router, prefix="/api")
app.include_router(journal.router, prefix="/api")
app.include_router(budget.router, prefix="/api")
app.include_router(capex.router, prefix="/api")
app.include_router(kpi.router, prefix="/api")
app.include_router(billing.router, prefix="/api")
app.include_router(nl_query.router, prefix="/api")
app.include_router(suivi.router, prefix="/api")
app.include_router(notifications.router, prefix="/api")


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "biat-billing-api"}
