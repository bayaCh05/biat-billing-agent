# Copilot Instructions — BIAT Billing Agent

## Repository purpose
- Intelligent invoice automation for BIAT IT (bank subsidiary): extraction → classification → validation → accounting export + budget/CAPEX follow-up.
- Main stack: Python, Streamlit, SQLAlchemy, Pydantic, SQLite.

## Critical compliance rule (must-follow)
- **Data residency is local-only.**
- Do **not** send invoice data to cloud LLM APIs (OpenAI/Anthropic/Groq/etc.).
- Production LLM backend must remain **Ollama** (`qwen2.5:3b`, local endpoint).

## Fast orientation
- Core pipeline logic: `src/agent/pipeline.py` (pure stage functions).
- Dependency wiring: `src/agent/config_loader.py`.
- Streamlit entrypoint: `app/Home.py`.
- Main config: `config/settings.yaml`.

## Expected workflow for agents
1. Read `README.md`, `CLAUDE.md`, and `config/settings.yaml`.
2. Run baseline checks before edits.
3. Make minimal, targeted changes.
4. Re-run relevant checks after edits.
5. Keep all AI inference local (Ollama only).

## Validation commands
Use these from repository root:

```bash
# If .venv exists
source .venv/bin/activate
.venv/bin/ruff check src/ app/ tests/
.venv/bin/pytest --tb=short -q

# If .venv does NOT exist (common in fresh cloud runners)
python3 -m pip install -e ".[dev]"
python3 -m ruff check src/ app/ tests/
python3 -m pytest --tb=short -q
```

## Known architecture conventions
- Use `PipelineComponents` + stage functions from `src/agent/pipeline.py`, not an orchestration class.
- `build_pipeline_components()` returns `(components, engine)`; close sessions with `components.close()` when appropriate.
- Use `CostCatalog.from_yaml(...)` (not deprecated loaders).
- `AccountingCoder` should be initialized with `catalog=...`.
- Streamlit convention: prefer `width="stretch"` over deprecated `use_container_width`.

## CI/database gotcha
- SQLite path defaults to `sqlite:///./data/invoices.db`.
- In clean environments, create `./data` before DB initialization to avoid:
  - `sqlite3.OperationalError: unable to open database file`

## Errors encountered during onboarding (2026-06-18)
1. **Error:** `.venv/bin/ruff: No such file or directory`  
   **Work-around used:** installed dependencies with `python3 -m pip install -e ".[dev]"` and used module-invocation commands (`python3 -m ruff`, `python3 -m pytest`).
2. **Error (baseline tests):** `ModuleNotFoundError: No module named 'skimage'` in OCR preprocessor tests  
   **Work-around used for onboarding task:** documented as a pre-existing test-environment issue; did not change production code.
3. **Error (baseline tests):** `TestTesseractEngine.test_language_mapping` assertion failure  
   **Work-around used for onboarding task:** documented as pre-existing baseline failure; no functional code changes made for this onboarding-only task.

## Scope reminder for future agents
- For this repository onboarding task, only `.github/copilot-instructions.md` should be added.
- Avoid unrelated refactors/fixes unless explicitly requested.
