"""Shared Pydantic v2 schemas for inter-agent communication in Gauri (English-only internal layer)."""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class RouteType(str, Enum):
    """Supported orchestrator routes in priority order."""

    EMERGENCY = "EMERGENCY"
    TRIAGE = "TRIAGE"
    HEALTH_CHECK = "HEALTH_CHECK"
    RECORD = "RECORD"
    GENERAL_QUERY = "GENERAL_QUERY"
    CLARIFY = "CLARIFY"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


class SourceType(str, Enum):
    """Provenance tag required for every stored animal fact."""

    OWNER_REPORTED = "OWNER_REPORTED"
    MODEL_PREDICTED = "MODEL_PREDICTED"
    VET_VERIFIED = "VET_VERIFIED"
    SYSTEM_CALCULATED = "SYSTEM_CALCULATED"


class AgentStatus(str, Enum):
    """Execution status returned by any specialized subagent."""

    SUCCESS = "SUCCESS"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    ESCALATED = "ESCALATED"
    REJECTED = "REJECTED"


class InputPayload(BaseModel):
    """English structured input passed into the Orchestrator."""

    english_description: str = Field(
        ..., min_length=1, description="Concise structured English description of what the owner said."
    )
    transcription_confidence: float = Field(
        default=1.0, ge=0.0, le=1.0, description="Upstream ASR/translation confidence score between 0 and 1."
    )
    flagged_issues: list[str] = Field(
        default_factory=list, description="Missing or contradictory details flagged upstream."
    )
    image_path: Optional[str] = Field(
        default=None, description="Local path to an uploaded animal photo, if any."
    )


class RoutingDecision(BaseModel):
    """Structured JSON output required from the Orchestrator router LLM."""

    routes: list[RouteType] = Field(..., min_length=1)
    animal_ref: Optional[str] = Field(
        default=None, description="Animal name, ear tag, or physical description mentioned."
    )
    medication_requested: bool = Field(
        default=False, description="True if owner asked for any drug, injection, or dosage."
    )
    missing_info: list[str] = Field(
        default_factory=list, description="Specific missing details when CLARIFY is selected."
    )
    reason: str = Field(..., min_length=1, description="One-sentence routing justification.")


class TaskPayload(BaseModel):
    """Standardized payload passed from the Orchestrator to any subagent."""

    task_id: str = Field(default_factory=lambda: f"task_{uuid4().hex[:8]}")
    english_description: str
    intent: RouteType
    animal_id: Optional[str] = None
    animal_ref: Optional[str] = None
    animal_context: Optional[str] = None
    previous_context: Optional[str] = None
    medication_requested: bool = False
    image_path: Optional[str] = None
    extra_data: dict[str, Any] = Field(default_factory=dict)


class ProposedFieldUpdate(BaseModel):
    """Field-level evidence submitted by the Record Agent."""

    field: str
    value: Any
    source_text: str = Field(..., description="Exact quote from owner description supporting this.")
    source_type: SourceType
    confidence: float = Field(..., ge=0.0, le=1.0)
    requires_owner_confirmation: bool = False


class AgentResponse(BaseModel):
    """Standardized response returned by a subagent to the Orchestrator."""

    task_id: str
    agent_name: str
    status: AgentStatus
    summary: str
    proposed_updates: list[ProposedFieldUpdate] = Field(default_factory=list)
    clarification_questions: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)
