# Diagram 3 — AI Agent Architecture
# Paste into Eraser → New Diagram → Cloud Architecture

```
direction: down

// ── INPUTS ────────────────────────────────────────────
PDFFile [label: "PDF / Image\nFacture fournisseur", icon: file-text, color: "#1A3A5C"]
NLQuestion [label: "Question NL\n(français)", icon: message-square, color: "#1A3A5C"]
RoadmapItems [label: "Jalons Roadmap\n(overdue)", icon: map, color: "#1A3A5C"]
RiskForm [label: "Formulaire Risque\n(titre, type, impact)", icon: alert-triangle, color: "#1A3A5C"]

// ── ORCHESTRATOR ──────────────────────────────────────
Orchestrator [label: "AI Orchestrator\n(synchronous, 4 steps)", icon: layers, color: "#F0A500", shape: hexagon]

// ── 6 AGENTS ──────────────────────────────────────────
Agents [color: "#F0A500"] {
  A1 [label: "① ExtractionAgent\nPyMuPDF → Tesseract → Ollama\nOutput: ConfidenceField[]", icon: scan, color: "#F0A500"]
  A2 [label: "② ClassificationAgent\nPass A: Fuzzy CostCatalog\nPass B: TF-IDF / LogReg ML\nPass C: RAG + Ollama\nOutput: PCE compte + reason", icon: tag, color: "#F0A500"]
  A3 [label: "③ AnomalyAgent\nMath validation (TVA, TTC)\nDuplicate detection\nEmbbedding similarity\nOutput: ValidationFlag[]", icon: alert-triangle, color: "#F0A500"]
  A4 [label: "④ AccountingAgent\nJournal PCE (double entrée)\nCAPEX asset creation\nPayment schedule\nOllama: explanation + amort.\nOutput: JournalEntry + Asset", icon: book-open, color: "#F0A500"]
  A5 [label: "⑤ RiskAgent\nScan roadmap overdue items\nDraft mitigation plan\nOutput: RisqueDocument (Mongo) + plan", icon: shield-alert, color: "#F0A500"]
  A6 [label: "⑥ InsightAgent\nNL → pipeline Mongo → résultats\nKPI → résumé 3 phrases\nOutput: answer + table", icon: sparkles, color: "#F0A500"]
}

// ── RAG SYSTEM ────────────────────────────────────────
RAG [label: "RAG System (shared)", color: "#2E86C1"] {
  Embedder [label: "PCEEmbedder\nsentence-transformers", icon: layers, color: "#2E86C1"]
  ChromaDB [label: "ChromaDB\n(vector store locale)", icon: database, color: "#2E86C1"]
  RAGClassifier [label: "RAGClassifier\nTop-K similarity", icon: search, color: "#2E86C1"]
}

// ── LOCAL LLM ─────────────────────────────────────────
Ollama [label: "Ollama\nqwen2.5:3b\n100% LOCAL — no cloud", icon: cpu, color: "#F0A500", shape: rounded-rectangle]

// ── OUTPUTS ───────────────────────────────────────────
DB [label: "MongoDB\n(SQLite legacy, audit/review only)", icon: database, color: "#1A3A5C"]
InvoiceResult [label: "InvoiceRecord\nstatut JOURNALED", icon: check-circle, color: "#1D9E76"]

// ── CONNECTIONS ───────────────────────────────────────
PDFFile -> Orchestrator
Orchestrator -> A1 -> A2 -> A3 -> A4 -> InvoiceResult
A4 -> DB
NLQuestion -> A6
RoadmapItems -> A5
RiskForm -> A5
Embedder -> ChromaDB
ChromaDB -> RAGClassifier
RAGClassifier -> A2
A3 -> ChromaDB: "embedding check"
A1 -> Ollama: "LLM extraction"
A2 -> Ollama: "Pass C classify"
A4 -> Ollama: "explanation + amort."
A5 -> Ollama: "draft risk + mitigation"
A6 -> Ollama: "NL → Mongo pipeline + answer"
```

> All Ollama calls use local model `qwen2.5:3b`. Temperature 0.0–0.3 depending on agent.
> Degraded mode: every agent has a rule-based fallback when Ollama is unavailable.
