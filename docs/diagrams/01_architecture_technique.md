# Diagram 1 — Technical Architecture

**Updated 2026-07-15** — the previous version didn't mention MongoDB at all
(it predated the SQLite → MongoDB migration) and listed PostgreSQL as the
production database even though nothing in the code implements it. This
version reflects the actual current architecture.

Rendered: [`01_architecture_technique.png`](01_architecture_technique.png) ·
Live editable source: https://app.eraser.io/workspace/NAh6JeIRqqIfV1Fef6wg?diagram=IdIWER6z9OUfcT9ix9WH

Paste into Eraser → New Diagram → Cloud Architecture

```
title: "01 - Technical Architecture"
direction: right

Frontend [icon: monitor, color: "#1A3A5C"] {
  React19 [label: "React 19 + TypeScript", icon: react, color: "#2E86C1"]
  Vite [label: "Vite (bundler)", icon: zap, color: "#2E86C1"]
  TailwindCSS [label: "Tailwind CSS", icon: wind, color: "#2E86C1"]
}

Backend [icon: server, color: "#1A3A5C"] {
  FastAPI [label: "FastAPI (Python 3.14)", icon: zap, color: "#2E86C1"]
  SQLAlchemy [label: "SQLAlchemy + Alembic", icon: database, color: "#2E86C1"]
  APScheduler [label: "APScheduler (5 nightly jobs)", icon: clock, color: "#2E86C1"]
  JWT [label: "JWT + argon2id (auth)", icon: lock, color: "#2E86C1"]
}

AIAgents [label: "AI Agents (local only - Ollama)", icon: cpu, color: "#F0A500"] {
  Orchestrator [label: "InvoiceProcessingOrchestrator", icon: layers, color: "#F0A500"]
  ExtractionAgent [label: "ExtractionAgent", icon: file-text, color: "#F0A500"]
  ClassificationAgent [label: "ClassificationAgent", icon: tag, color: "#F0A500"]
  AnomalyAgent [label: "AnomalyAgent", icon: alert-triangle, color: "#F0A500"]
  AccountingAgent [label: "AccountingAgent", icon: book-open, color: "#F0A500"]
  RiskAgent [label: "RiskAgent", icon: shield-alert, color: "#F0A500"]
  InsightAgent [label: "InsightAgent", icon: sparkles, color: "#F0A500"]
  AuditAgent [label: "AuditAgent (DAILY/WEEKLY/MONTHLY)", icon: shield-check, color: "#F0A500"]
  Ollama [label: "Ollama qwen2.5:3b (HOST ONLY)", icon: cpu, color: "#804CD7"]
}

DataLayer [icon: database, color: "#1A3A5C"] {
  MongoDB [label: "MongoDB (PRIMARY)\ninvoices, journal, users,\nbudget, roadmap, risks,\naudit logs + snapshots, CAPEX", icon: database, color: "#1D9E76"]
  SQLite [label: "SQLite (SECONDARY, shrinking)\nHMAC audit chain,\nreview-queue fallback,\njournal-completeness fallback", icon: database, color: "#5D6D7E"]
  ChromaDB [label: "ChromaDB (embedded, local)\npce_catalog, invoice_embeddings,\naudit_incidents", icon: layers, color: "#2E86C1"]
}

DockerCompose [label: "Docker Compose", icon: box, color: "#1A3A5C"] {
  AppContainer [label: "app (backend + compiled SPA)", icon: package, color: "#2E86C1"]
  MongoContainer [label: "mongo (MongoDB 7, --auth)", icon: database, color: "#2E86C1"]
}

React19 -> FastAPI: "HTTP/JSON :8000"
FastAPI -> Orchestrator: "process_invoice()"
FastAPI -> APScheduler
FastAPI -> SQLAlchemy
Orchestrator -> ExtractionAgent
Orchestrator -> ClassificationAgent
Orchestrator -> AnomalyAgent
Orchestrator -> AccountingAgent
ExtractionAgent -> Ollama
ClassificationAgent -> Ollama
ClassificationAgent -> ChromaDB
AnomalyAgent -> ChromaDB
AccountingAgent -> Ollama
RiskAgent -> Ollama
InsightAgent -> Ollama
AuditAgent -> Ollama
AuditAgent -> ChromaDB
Orchestrator -> MongoDB: "sync pymongo"
RiskAgent -> MongoDB: "sync pymongo"
InsightAgent -> MongoDB: "sync pymongo"
AuditAgent -> MongoDB: "sync pymongo"
SQLAlchemy -> SQLite
AppContainer -> MongoContainer: "mongodb://mongo:27017"
AppContainer -> Ollama: "host.docker.internal:11434"
DockerCompose -> AIAgents
DockerCompose -> DataLayer
```

> **Note: no cloud services. All AI inference is 100% local via Ollama.**
> Data residency constraint: invoice data never leaves the machine.
