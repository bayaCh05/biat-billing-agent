"""Chargement des templates de prompts depuis config/prompts.yaml.

Usage:
    loader = PromptLoader()
    prompt = loader.format("classification_explain",
                           issuer="SARL ABC", top_item="Licences", ...)
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

_DEFAULT_PATH = Path(__file__).parent.parent.parent / "config" / "prompts.yaml"


class PromptLoader:
    _instance: "PromptLoader | None" = None

    def __init__(self, path: str | Path | None = None) -> None:
        import yaml
        p = Path(path) if path else _DEFAULT_PATH
        with open(p, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        self._prompts: dict[str, dict] = data.get("prompts", {})
        self.tested_with_model: str = data.get("tested_with_model", "")

    @classmethod
    def get(cls) -> "PromptLoader":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def template(self, key: str) -> str:
        """Return the raw template string for a prompt key."""
        entry = self._prompts.get(key)
        if not entry:
            raise KeyError(f"Prompt '{key}' not found in prompts.yaml")
        return entry["template"]

    def format(self, key: str, **kwargs: Any) -> str:
        """Return a formatted prompt with the given variables."""
        return self.template(key).format(**kwargs)

    def temperature(self, key: str) -> float:
        return float(self._prompts.get(key, {}).get("temperature", 0.0))

    def max_tokens(self, key: str) -> int:
        return int(self._prompts.get(key, {}).get("max_tokens", 200))
