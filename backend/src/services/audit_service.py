"""Audit trail request helpers — IP/User-Agent extraction shared by the Mongo-native
audit writers (log_audit_event_native() / log_ai_audit_event_sync()).

The append-only writer that used to live here (log_action(), SQLAlchemy-based)
has zero callers — see CLAUDE.md "MongoDB Migration Status".
"""
from __future__ import annotations

import os

# IPs des proxies de confiance depuis lesquels X-Forwarded-For est accepté.
# Format : liste d'IPs séparées par des virgules (ex: "10.0.0.1,10.0.0.2").
# Si vide (défaut), X-Forwarded-For est ignoré et l'IP directe est utilisée.
_TRUSTED_PROXIES: frozenset[str] = frozenset(
    ip.strip()
    for ip in os.getenv("TRUSTED_PROXY_IPS", "").split(",")
    if ip.strip()
)


def _ip(request) -> str | None:
    """Extrait l'IP client — n'accepte X-Forwarded-For que depuis des proxies de confiance."""
    if request is None:
        return None
    client = getattr(request, "client", None)
    direct_ip = client.host if client else None
    # N'utiliser X-Forwarded-For que si la requête arrive d'un proxy connu
    if _TRUSTED_PROXIES and direct_ip in _TRUSTED_PROXIES:
        forwarded = (request.headers or {}).get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return direct_ip


def _ua(request) -> str | None:
    """Extract User-Agent header from a FastAPI Request."""
    if request is None:
        return None
    return (request.headers or {}).get("user-agent")
