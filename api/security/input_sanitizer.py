"""Input length and content validation for free-text API fields."""
from __future__ import annotations

from fastapi import HTTPException

MAX_LENGTHS: dict[str, int] = {
    "titre": 200,
    "description": 2000,
    "plan_mitigation": 3000,
    "issuer_name": 200,
    "invoice_number": 100,
    "libelle": 500,
    "email": 254,
    "nom": 100,
    "prenom": 100,
    "departement": 100,
    "nl_query": 500,
    "detail": 1000,
    "notes": 2000,
}

_FORBIDDEN = [
    "<script", "javascript:", "data:text/html",
    "DROP TABLE", "DELETE FROM", "--", "/*",
]


def sanitize(value: str | None, field_name: str) -> str | None:
    """
    Validate and strip a free-text field.
    Raises HTTPException 422 on violation.
    Returns stripped value or None.
    """
    if not value:
        return value

    max_len = MAX_LENGTHS.get(field_name, 1000)
    if len(value) > max_len:
        raise HTTPException(
            status_code=422,
            detail=f"Champ '{field_name}' trop long. Maximum: {max_len} caractères.",
        )

    lower = value.lower()
    for pattern in _FORBIDDEN:
        if pattern.lower() in lower:
            raise HTTPException(
                status_code=422,
                detail=f"Contenu non autorisé dans le champ '{field_name}'.",
            )

    return value.strip()
