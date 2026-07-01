# Diagram 1 — Technical Architecture
# Paste into Eraser → New Diagram → Cloud Architecture

```
direction: right

// ── FRONTEND ──────────────────────────────────────────
Frontend [icon: monitor, color: "#1A3A5C"] {
  React18 [label: "React 18 + TypeScript", icon: react, color: "#2E86C1"]
  Vite [label: "Vite (bundler)", icon: zap, color: "#2E86C1"]
  TailwindCSS [label: "Tailwind CSS", icon: wind, color: "#2E86C1"]
  Recharts [label: "Recharts (charts)", icon: bar-chart, color: "#2E86C1"]
  ReactRouter [label: "React Router v6", icon: navigation, color: "#2E86C1"]
  Axios [label: "Axios (HTTP)", icon: arrow-right, color: "#2E86C1"]
}

// ── BACKEND ──────────────────────────────────────────
Backend [icon: server, color: "#1A3A5C"] {
  FastAPI [label: "FastAPI (Python 3.14)", icon: zap, color: "#2E86C1"]
  SQLAlchemy [label: "SQLAlchemy ORM", icon: database, color: "#2E86C1"]
  Alembic [label: "Alembic (migrations)", icon: git-branch, color: "#2E86C1"]
  APScheduler [label: "APScheduler (nightly jobs)", icon: clock, color: "#F0A500"]
  SlowAPI [label: "SlowAPI (rate limiting)", icon: shield, color: "#2E86C1"]
  JWT [label: "JWT + bcrypt (auth)", icon: lock, color: "#2E86C1"]
}

// ── AI LAYER ──────────────────────────────────────────
AI [icon: cpu, color: "#F0A500"] {
  Orchestrator [label: "AI Orchestrator", icon: layers, color: "#F0A500"]
  ExtractionAgent [label: "ExtractionAgent", icon: file-text, color: "#F0A500"]
  ClassificationAgent [label: "ClassificationAgent", icon: tag, color: "#F0A500"]
  AnomalyAgent [label: "AnomalyAgent", icon: alert-triangle, color: "#F0A500"]
  AccountingAgent [label: "AccountingAgent", icon: book-open, color: "#F0A500"]
  RiskAgent [label: "RiskAgent", icon: shield-alert, color: "#F0A500"]
  InsightAgent [label: "InsightAgent", icon: sparkles, color: "#F0A500"]
  Ollama [label: "Ollama\nqwen2.5:3b (LOCAL)", icon: cpu, color: "#F0A500"]
  TFIDF [label: "TF-IDF + LogisticRegression", icon: trending-up, color: "#F0A500"]
  ChromaDB [label: "ChromaDB (vector store)", icon: database, color: "#F0A500"]
  PyMuPDF [label: "PyMuPDF + Tesseract OCR", icon: scan, color: "#F0A500"]
  SentenceTransformers [label: "sentence-transformers", icon: layers, color: "#F0A500"]
}

// ── DATA ──────────────────────────────────────────────
Data [icon: database, color: "#1A3A5C"] {
  SQLite [label: "SQLite WAL (dev)", icon: database, color: "#2E86C1"]
  PostgreSQL [label: "PostgreSQL (prod)", icon: database, color: "#2E86C1"]
  CostCatalog [label: "cost_catalog.yaml\n33 PCE entries", icon: file-text, color: "#2E86C1"]
  MLModel [label: "ml_model.joblib", icon: trending-up, color: "#2E86C1"]
  BudgetYAML [label: "budget_plan.yaml", icon: file-text, color: "#2E86C1"]
}

// ── INFRASTRUCTURE ────────────────────────────────────
Infra [icon: cloud, color: "#1A3A5C"] {
  Docker [label: "Docker + docker-compose", icon: box, color: "#2E86C1"]
  GithubActions [label: "GitHub Actions CI/CD", icon: git-branch, color: "#2E86C1"]
  Mailhog [label: "Mailhog (local email dev)", icon: mail, color: "#2E86C1"]
}

// ── CONNECTIONS ───────────────────────────────────────
React18 -> FastAPI: "HTTP/JSON REST API\nport 8000"
FastAPI -> SQLAlchemy: ORM
FastAPI -> Orchestrator: "process_invoice()"
FastAPI -> APScheduler: "nightly jobs"
Orchestrator -> ExtractionAgent
Orchestrator -> ClassificationAgent
Orchestrator -> AnomalyAgent
Orchestrator -> AccountingAgent
Orchestrator -> RiskAgent
Orchestrator -> InsightAgent
ExtractionAgent -> PyMuPDF
ExtractionAgent -> Ollama
ClassificationAgent -> TFIDF
ClassificationAgent -> ChromaDB
ClassificationAgent -> Ollama
AnomalyAgent -> ChromaDB
AccountingAgent -> Ollama
RiskAgent -> Ollama
InsightAgent -> Ollama
SQLAlchemy -> SQLite
SQLAlchemy -> PostgreSQL
SentenceTransformers -> ChromaDB
Docker -> Backend
Docker -> Frontend
GithubActions -> Docker
```

> **Note: NO cloud services. All AI inference is 100% local via Ollama.**
> Data residency constraint: invoice data never leaves the machine.
