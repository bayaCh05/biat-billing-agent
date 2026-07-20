# Diagram 3 — AI Agent Architecture

**Updated 2026-07-16/20** — translated to English, added AuditAgent (7th
agent) and separated it from InsightAgent/NLQueryEngine (an earlier version
conflated the two). RiskAgent's and AuditAgent's "Output" labels no longer
name Beanie Document classes (`RisqueDocument`, `AuditSnapshotDocument`) —
both actually write via sync pymongo (`sync_mongo_repository.py`), never
Beanie's async ODM; RiskAgent was migrated off a Beanie/asyncio.run() bridge
that crashed intermittently (see `risk_agent.py`).

# Paste into Eraser → New Diagram → Cloud Architecture

```
direction: down

// ── INPUTS ────────────────────────────────────────────
PDFFile [label: "PDF / Image\nSupplier invoice", icon: file-text, color: "#1A3A5C"]
NLQuestion [label: "NL question\n(French)", icon: message-square, color: "#1A3A5C"]
RoadmapItems [label: "Roadmap milestones\n(overdue)", icon: map, color: "#1A3A5C"]
RiskForm [label: "Risk form\n(title, type, impact)", icon: alert-triangle, color: "#1A3A5C"]

// ── ORCHESTRATOR ──────────────────────────────────────
Orchestrator [label: "Invoice Processing Orchestrator\n(synchronous, 4 steps)", icon: layers, color: "#F0A500", shape: hexagon]

// ── 7 AGENTS ──────────────────────────────────────────
Agents [color: "#F0A500"] {
  A1 [label: "① ExtractionAgent\nPyMuPDF → Tesseract → Ollama\nOutput: ConfidenceField[]", icon: scan, color: "#F0A500"]
  A2 [label: "② ClassificationAgent\nPass A: Fuzzy CostCatalog\nPass B: TF-IDF / LogReg ML\nPass C: RAG + Ollama\nOutput: PCE account + reason", icon: tag, color: "#F0A500"]
  A3 [label: "③ AnomalyAgent\nMath validation (TVA, TTC)\nDuplicate detection\nEmbedding similarity\nOutput: ValidationFlag[]", icon: alert-triangle, color: "#F0A500"]
  A4 [label: "④ AccountingAgent\nPCE journal (double entry)\nCAPEX asset creation\nPayment schedule\nOllama: explanation + amort.\nOutput: JournalEntry + Asset", icon: book-open, color: "#F0A500"]
  A5 [label: "⑤ RiskAgent\nScan overdue roadmap items\nDraft mitigation plan\nOutput: risque record (Mongo, sync pymongo) + plan", icon: shield-alert, color: "#F0A500"]
  A6 [label: "⑥ InsightAgent\nKPI snapshot → 3-sentence summary\n(not NL Query — see NLQueryEngine below)", icon: sparkles, color: "#F0A500"]
  A7 [label: "⑦ AuditAgent\nDAILY/WEEKLY/MONTHLY cross-entity\nreconciliation + RAG narrative\nOutput: audit snapshot (Mongo, sync pymongo)", icon: shield-check, color: "#F0A500"]
}

// ── NL QUERY (separate module, not an agent) ──────────
NLQueryEngine [label: "NLQueryEngine\n(src/query/, not ai_agents/)\nNL → MongoDB aggregation pipeline", icon: search, color: "#2E86C1"]

// ── RAG SYSTEM ────────────────────────────────────────
RAG [label: "RAG System (shared)", color: "#2E86C1"] {
  Embedder [label: "PCEEmbedder\nsentence-transformers", icon: layers, color: "#2E86C1"]
  ChromaDB [label: "ChromaDB\n(local vector store)", icon: database, color: "#2E86C1"]
  RAGClassifier [label: "RAGClassifier\nTop-K similarity", icon: search, color: "#2E86C1"]
}

// ── LOCAL LLM ─────────────────────────────────────────
Ollama [label: "Ollama\nqwen2.5:3b\n100% LOCAL — no cloud", icon: cpu, color: "#F0A500", shape: rounded-rectangle]

// ── OUTPUTS ───────────────────────────────────────────
DB [label: "MongoDB\n(SQLite legacy, audit/review only)", icon: database, color: "#1A3A5C"]
InvoiceResult [label: "InvoiceRecord\nstatus JOURNALED", icon: check-circle, color: "#1D9E76"]

// ── CONNECTIONS ───────────────────────────────────────
PDFFile -> Orchestrator
Orchestrator -> A1 -> A2 -> A3 -> A4 -> InvoiceResult
A4 -> DB
NLQuestion -> NLQueryEngine
RoadmapItems -> A5
RiskForm -> A5
Embedder -> ChromaDB
ChromaDB -> RAGClassifier
RAGClassifier -> A2
A3 -> ChromaDB: "embedding check"
A7 -> ChromaDB: "audit_incidents narrative RAG"
A1 -> Ollama: "LLM extraction"
A2 -> Ollama: "Pass C classify"
A4 -> Ollama: "explanation + amort."
A5 -> Ollama: "draft risk + mitigation"
A6 -> Ollama: "KPI → summary"
A7 -> Ollama: "narrative synthesis"
NLQueryEngine -> Ollama: "NL → Mongo pipeline"
NLQueryEngine -> DB
```

> All Ollama calls use local model `qwen2.5:3b`. Temperature 0.0–0.3 depending on agent.
> Degraded mode: every agent has a rule-based fallback when Ollama is unavailable.
> **NL Query is not an agent** — `NLQueryEngine` (`src/query/nl_query_engine.py`)
> is a separate module the LLM never calls through `ai_agents/`; it's shown
> here because it shares the same Ollama backend, not because it's a 7th
> agent. `InsightAgent` (A6) only serves `/ai/health-summary` (a KPI
> executive summary) — an earlier version of this diagram conflated the two.
