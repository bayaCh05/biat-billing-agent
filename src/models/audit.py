"""Audit trail Pydantic models — BCT compliance (Circulaire 2025-13)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AuditLogCreate(BaseModel):
    """Input model for audit_service.log_action()."""
    user_id: str | None = None
    user_email: str | None = None
    user_role: str | None = None
    action: str                         # LOGIN, LOGOUT, CREATE, UPDATE, DELETE, APPROVE, REJECT, EXPORT
    resource_type: str | None = None    # InvoiceRecord, JournalEntry, Asset, ClientInvoice, User
    resource_id: str | None = None
    before_value: dict[str, Any] | None = None
    after_value: dict[str, Any] | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    status: str = "SUCCESS"             # SUCCESS | FAILURE
    detail: str | None = None


class AuditLogOut(BaseModel):
    id: str
    created_at: str
    user_id: str | None
    user_email: str | None
    user_role: str | None
    action: str
    resource_type: str | None
    resource_id: str | None
    before_value: dict[str, Any] | None
    after_value: dict[str, Any] | None
    ip_address: str | None
    user_agent: str | None
    status: str
    detail: str | None
