"""Abstract base class for all AI agents."""
from __future__ import annotations

import json
import logging
import re
import time
from abc import ABC, abstractmethod

from src.ai_agents.agent_schemas import AgentResult
from src.ai_agents.ollama_client import OllamaClient

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    name: str = "BaseAgent"

    def __init__(self) -> None:
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
        # Resolve OllamaClient.get() fresh on every call (not cached at
        # __init__) — matches how every agent's ad-hoc Ollama call site
        # already did it, and lets tests patch OllamaClient.get() per-test
        # after the agent fixture is constructed.
        self._call_count += 1
        return OllamaClient.get().complete(
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

    def _run_safely(self, fn) -> AgentResult:
        """Standard run()/sub-capability wrapper: times execution and converts
        any exception into a uniform success=False AgentResult instead of
        letting it propagate to the orchestrator.

        `fn` is a zero-arg callable doing the agent's actual work; it returns
        a dict of AgentResult kwargs for the success case (output=...,
        confidence=..., explanation=...) — agent_name, success, duration_ms,
        and ollama_calls_made are filled in here so each agent only writes
        its own logic once.
        """
        start = time.monotonic()
        try:
            kwargs = fn()
            return AgentResult(
                agent_name=self.name,
                success=True,
                duration_ms=(time.monotonic() - start) * 1000,
                ollama_calls_made=self._call_count,
                **kwargs,
            )
        except Exception as exc:
            logger.error("%s_error: %s", self.name, exc)
            return AgentResult(
                agent_name=self.name,
                success=False,
                duration_ms=(time.monotonic() - start) * 1000,
                error=str(exc),
                ollama_calls_made=self._call_count,
            )
