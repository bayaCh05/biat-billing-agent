"""Shared Ollama client — singleton with rate limiting and stats tracking."""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import TYPE_CHECKING

import requests

logger = logging.getLogger(__name__)

_OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
_OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "30"))
_MAX_CONCURRENT = int(os.getenv("OLLAMA_MAX_CONCURRENT", "3"))


class OllamaClient:
    """Thread-safe singleton Ollama client.

    Usage: OllamaClient.get().complete(prompt)
    """

    _instance: "OllamaClient | None" = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._semaphore = threading.Semaphore(_MAX_CONCURRENT)
        self._stats = {"calls": 0, "success": 0, "total_ms": 0.0}
        self._stats_lock = threading.Lock()
        # availability cache
        self._available: bool | None = None
        self._available_checked_at: float = 0.0

    @classmethod
    def get(cls) -> "OllamaClient":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def complete(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.0,
        max_tokens: int = 200,
    ) -> str | None:
        """Call Ollama and return the response text.

        Returns None on failure — never raises.
        2 retries with exponential backoff on timeout.
        """
        with self._semaphore:
            for attempt in range(3):
                start = time.monotonic()
                try:
                    messages = []
                    if system:
                        messages.append({"role": "system", "content": system})
                    messages.append({"role": "user", "content": prompt})

                    resp = requests.post(
                        f"{_OLLAMA_URL}/api/chat",
                        json={
                            "model": _OLLAMA_MODEL,
                            "messages": messages,
                            "stream": False,
                            "options": {
                                "temperature": temperature,
                                "num_predict": max_tokens,
                            },
                        },
                        timeout=_TIMEOUT,
                    )
                    resp.raise_for_status()
                    text = resp.json()["message"]["content"]
                    duration_ms = (time.monotonic() - start) * 1000

                    with self._stats_lock:
                        self._stats["calls"] += 1
                        self._stats["success"] += 1
                        self._stats["total_ms"] += duration_ms

                    logger.debug(
                        "ollama_call_ok",
                        extra={"attempt": attempt + 1, "duration_ms": round(duration_ms)},
                    )
                    return text

                except requests.exceptions.Timeout:
                    wait = 2 ** attempt
                    logger.warning("ollama_timeout attempt=%d — retrying in %ds", attempt + 1, wait)
                    if attempt < 2:
                        time.sleep(wait)
                    else:
                        with self._stats_lock:
                            self._stats["calls"] += 1
                        return None

                except Exception as exc:
                    duration_ms = (time.monotonic() - start) * 1000
                    logger.warning("ollama_error attempt=%d: %s", attempt + 1, exc)
                    with self._stats_lock:
                        self._stats["calls"] += 1
                    return None
        return None

    def is_available(self) -> bool:
        """Check Ollama availability; result cached for 30 seconds."""
        now = time.monotonic()
        if self._available is not None and (now - self._available_checked_at) < 30:
            return self._available
        try:
            resp = requests.get(f"{_OLLAMA_URL}/api/tags", timeout=5)
            self._available = resp.status_code == 200
        except Exception:
            self._available = False
        self._available_checked_at = now
        return self._available

    def get_stats(self) -> dict:
        with self._stats_lock:
            calls = self._stats["calls"]
            success = self._stats["success"]
            total_ms = self._stats["total_ms"]
        return {
            "total_calls": calls,
            "success_rate": round(success / calls, 3) if calls > 0 else 1.0,
            "avg_duration_ms": round(total_ms / success) if success > 0 else 0,
        }
