"""RAG-based Pass C classification for PCE accounting codes."""
from __future__ import annotations

import logging

from src.ai_agents.ollama_client import OllamaClient
from src.ai_agents.rag.pce_vectorstore import PCEVectorStore

logger = logging.getLogger(__name__)


class RAGClassifier:
    """Pass C: embed query → ChromaDB → Ollama picks from candidates."""

    def classify(self, invoice_text: str, line_items: list) -> dict | None:
        """Return chosen catalog entry dict or None if unavailable/failed."""
        store = PCEVectorStore.get()
        if not store.available:
            return None

        query = invoice_text[:300]
        if line_items:
            descs = " ".join(
                item.description for item in line_items if getattr(item, "description", None)
            )
            if descs:
                query = f"{query} {descs}"

        candidates = store.search_pce(query, n_results=3)
        if not candidates:
            return None

        choices_text = "\n".join(
            f"{i+1}. {c['label']} (compte {c['compte']})"
            for i, c in enumerate(candidates)
        )

        prompt = (
            f'Tu es un expert-comptable tunisien.\n'
            f'Une facture contient: "{query[:300]}"\n\n'
            f"Voici {len(candidates)} catégories comptables PCE possibles:\n"
            f"{choices_text}\n\n"
            f"Réponds UNIQUEMENT en JSON sans markdown:\n"
            f'{{"choice": 1, "reason": "une phrase en français"}}'
        )

        raw = OllamaClient.get().complete(prompt, temperature=0.0, max_tokens=80)
        if not raw:
            return candidates[0] if candidates else None

        import json, re
        try:
            m = re.search(r"\{[^}]+\}", raw)
            parsed = json.loads(m.group(0)) if m else {}
            choice_idx = int(parsed.get("choice", 1)) - 1
            choice_idx = max(0, min(choice_idx, len(candidates) - 1))
            result = dict(candidates[choice_idx])
            result["reason"] = parsed.get("reason", "")
            result["pass_used"] = "RAG_LLM"
            return result
        except Exception as exc:
            logger.warning("rag_classifier_parse_error: %s", exc)
            return candidates[0] if candidates else None
