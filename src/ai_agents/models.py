"""Pydantic models shared across all AI agents."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AgentResult(BaseModel):
    agent_name: str
    success: bool
    duration_ms: float
    output: dict = Field(default_factory=dict)
    confidence: float | None = None
    explanation: str | None = None
    error: str | None = None
    ollama_calls_made: int = 0


class PipelineStep(BaseModel):
    step_number: int
    agent_name: str
    status: str = "waiting"  # waiting | running | done | failed | skipped
    duration_ms: float | None = None
    summary: str | None = None


class OrchestratorResult(BaseModel):
    invoice_id: str
    final_status: str
    pipeline_steps: list[PipelineStep] = Field(default_factory=list)
    total_duration_ms: float = 0.0
    ollama_total_calls: int = 0
    degraded_mode: bool = False
    human_review_required: bool = False
    error: str | None = None
