"""Catalogue des coûts et produits de BIAT IT.

Le catalogue est chargé depuis config/cost_catalog.yaml au démarrage.
C'est la seule source de vérité pour la classification comptable — ni le code,
ni la base de données ne contiennent de logique de catégorisation en dur.

Algorithme de correspondance :
  1. Filtrer les entrées par flux (fournisseur / client / interne) si précisé.
  2. Pour chaque entrée, calculer un score 0-100 :
       - keyword présent comme mot entier (\b...\b) → 100 pts
       - keyword multi-mots : partial_ratio si ≥ 4 chars (compte uniquement si ≥ 80)
       - keyword mono-mot : pas de fallback fuzzy (évite "formation" dans "information")
     Score de l'entrée = score maximum parmi ses keywords.
  3. Retourner l'entrée au score le plus élevé si ce score ≥ min_score.
     Si égalité : préférer l'entrée avec le plus de keywords correspondants.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import re

import yaml
from rapidfuzz import fuzz

from src.classification.matcher import normalise
from src.models.enums import ChargeFlux, ChargeNature, ChargeType, Recurrence


@dataclass
class CostCatalogEntry:
    id: str
    label: str
    compte: str
    nature: ChargeNature
    type_charge: ChargeType
    tva_rate: float
    recurrence: Recurrence
    flux: ChargeFlux
    keywords: list[str] = field(default_factory=list)
    notes: str = ""
    max_plausible_amount: float | None = None

    @property
    def normalised_keywords(self) -> list[str]:
        return [normalise(k) for k in self.keywords]


class CostCatalog:
    def __init__(self, entries: list[CostCatalogEntry]) -> None:
        self._entries = entries
        self._by_id: dict[str, CostCatalogEntry] = {e.id: e for e in entries}

    # ── Loading ───────────────────────────────────────────────────────────────

    @classmethod
    def from_yaml(cls, path: str | Path) -> "CostCatalog":
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        entries = [cls._parse_entry(item) for item in raw.get("entries", [])]
        return cls(entries)

    @staticmethod
    def _parse_entry(data: dict) -> CostCatalogEntry:
        raw_max = data.get("max_plausible_amount")
        return CostCatalogEntry(
            id=data["id"],
            label=data["label"],
            compte=str(data["compte"]),
            nature=ChargeNature(data["nature"]),
            type_charge=ChargeType(data["type_charge"]),
            tva_rate=float(data.get("tva_rate", 19)),
            recurrence=Recurrence(data["recurrence"]),
            flux=ChargeFlux(data["flux"]),
            keywords=data.get("keywords", []),
            notes=data.get("notes", ""),
            max_plausible_amount=float(raw_max) if raw_max is not None else None,
        )

    # ── Matching ──────────────────────────────────────────────────────────────

    def match(
        self,
        text: str,
        flux: Optional[ChargeFlux] = None,
        min_score: int = 70,
    ) -> Optional[CostCatalogEntry]:
        """Return the best-matching catalog entry for the given invoice text.

        Args:
            text:      concatenated invoice text (description, issuer name, line items…)
            flux:      restrict candidates to this flux direction
            min_score: minimum score (0-100) to accept a match; below this → None
        """
        if not text.strip():
            return None

        norm_text = normalise(text)
        candidates = [
            e for e in self._entries
            if flux is None or e.flux == flux
        ]

        best_entry: Optional[CostCatalogEntry] = None
        best_score = -1
        best_match_count = 0

        for entry in candidates:
            score, match_count = self._score(norm_text, entry)
            if score > best_score or (score == best_score and match_count > best_match_count):
                best_score = score
                best_match_count = match_count
                best_entry = entry

        return best_entry if best_score >= min_score else None

    @staticmethod
    def _score(norm_text: str, entry: CostCatalogEntry) -> tuple[int, int]:
        """Return (max_keyword_score, keywords_matched_count) for the entry.

        Exact matches use a word-boundary regex so that e.g. "formation" does
        not match inside "information" or "informatique".

        Single-word keywords do NOT fall back to partial-string fuzzy matching —
        partial_ratio would match "formation" inside "information" (score 100),
        producing wrong accounting codes.

        Multi-word keywords (phrases) use partial_ratio on the full text with a
        count threshold of 80 to prevent loose matches from winning tiebreaks.

        Keywords shorter than 4 characters skip fuzzy matching entirely.
        """
        if not entry.keywords:
            return 0, 0

        scores = []
        match_count = 0

        for kw in entry.normalised_keywords:
            if not kw:
                continue

            is_phrase = " " in kw

            # Word-boundary exact match works for both single words and phrases
            if re.search(r"\b" + re.escape(kw) + r"\b", norm_text):
                scores.append(100)
                match_count += 1
            elif is_phrase and len(kw) >= 4:
                # Phrases: allow fuzzy partial match, but only count at ≥80
                s = fuzz.partial_ratio(kw, norm_text)
                scores.append(s)
                if s >= 80:
                    match_count += 1
            # Single-word keywords: no fuzzy fallback (avoids substring false positives)

        return (max(scores) if scores else 0), match_count

    # ── Lookup ────────────────────────────────────────────────────────────────

    def get(self, entry_id: str) -> Optional[CostCatalogEntry]:
        return self._by_id.get(entry_id)

    def all_entries(self) -> list[CostCatalogEntry]:
        return list(self._entries)

    def entries_by_flux(self, flux: ChargeFlux) -> list[CostCatalogEntry]:
        return [e for e in self._entries if e.flux == flux]

    def __len__(self) -> int:
        return len(self._entries)
