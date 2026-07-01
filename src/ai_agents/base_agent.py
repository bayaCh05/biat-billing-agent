"""Abstract base class for all AI agents."""
from __future__ import annotations

import json
import logging
import re
import time
from abc import ABC, abstractmethod

from src.ai_agents.models import AgentResult
from src.ai_agents.ollama_client import OllamaClient

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    name: str = "BaseAgent"

    def __init__(self) -> None:
        self._ollama = OllamaClient.get()
        self._call_count = 0

    @abstractmethod
    def run(self, context: dict) -> AgentResult:
        ...

    def _call_ollama(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.0,
        max_tokens: int = 200,
    ) -> str | None:
        self._call_count += 1
        return self._ollama.complete(
            prompt=prompt,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def _parse_json_response(self, text: str | None) -> dict | None:
        if not text:
            return None
        # Strip markdown fences
        m = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
        if m:
            text = m.group(1)
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            text = text[start:end]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    def _safe_float(self, value) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _timed_run(self, fn) -> tuple[AgentResult, float]:
        start = time.monotonic()
        result = fn()
        duration = (time.monotonic() - start) * 1000
        result.duration_ms = duration
        result.ollama_calls_made = self._call_count
        return result, duration
