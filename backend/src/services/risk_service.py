"""Risk management service — criticality matrix.

The SQLAlchemy-backed query functions that used to live here
(get_risks_for_roadmap_item, get_risks_for_project, get_risk_summary) had
zero callers — only their docstrings were referenced, by
service_bridge.py's Mongo-native equivalents. See CLAUDE.md "MongoDB
Migration Status".
"""
from __future__ import annotations

# Risk matrix: (probabilite, impact) → niveau_criticite
_MATRIX: dict[tuple[str, str], str] = {
    ("FAIBLE",  "FAIBLE"):   "FAIBLE",
    ("FAIBLE",  "MOYEN"):    "FAIBLE",
    ("FAIBLE",  "ELEVE"):    "MOYENNE",
    ("FAIBLE",  "CRITIQUE"): "MOYENNE",
    ("MOYENNE", "FAIBLE"):   "FAIBLE",
    ("MOYENNE", "MOYEN"):    "MOYENNE",
    ("MOYENNE", "ELEVE"):    "ELEVEE",
    ("MOYENNE", "CRITIQUE"): "ELEVEE",
    ("ELEVEE",  "FAIBLE"):   "MOYENNE",
    ("ELEVEE",  "MOYEN"):    "ELEVEE",
    ("ELEVEE",  "ELEVE"):    "ELEVEE",
    ("ELEVEE",  "CRITIQUE"): "CRITIQUE",
}

_CRITICITE_ORDER = {"FAIBLE": 0, "MOYENNE": 1, "ELEVEE": 2, "CRITIQUE": 3}


def calculate_criticite(probabilite: str, impact: str) -> str:
    return _MATRIX.get((probabilite, impact), "MOYENNE")
