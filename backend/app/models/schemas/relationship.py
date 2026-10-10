"""Relationship/memory/temporal DTOs for the Yance evidence projection.

Storage stays with ChatterMate's existing Customer/ChatHistory owners. These
models are API contracts only; they do not introduce a relationship database.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


MemoryKind = Literal[
    "fact", "note", "event", "interest", "shared_moment",
    "open_loop", "promise", "boundary", "sensitive_topic",
]
MemoryEffect = Literal["context", "no_reply", "defer"]


class RelationshipEvidence(BaseModel):
    source_type: Literal[
        "chat_history", "person_profile", "captured_attribute",
        "operator_confirmation",
    ]
    source_ref: str
    observed_at: Optional[datetime] = None
    label: Optional[str] = None
    session_id: Optional[str] = None


class RelationshipMemoryEntry(BaseModel):
    id: str
    kind: MemoryKind
    text: str
    confirmed: bool = True
    active: bool = True
    effect: MemoryEffect = "context"
    occurred_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    evidence: List[RelationshipEvidence] = Field(default_factory=list)


class RelationshipMemoryUpsertRequest(BaseModel):
    id: Optional[str] = None
    kind: MemoryKind
    text: str = Field(min_length=1, max_length=2000)
    active: bool = True
    effect: MemoryEffect = "context"
    occurred_at: Optional[datetime] = None
    source_refs: List[str] = Field(default_factory=list, max_length=20)

    @field_validator("text")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("text must not be blank")
        return value


class RelationshipTemporalSettingsRequest(BaseModel):
    contact_timezone: Optional[str] = None
    preferred_contact_start: Optional[str] = None
    preferred_contact_end: Optional[str] = None

    @field_validator("contact_timezone")
    @classmethod
    def normalize_timezone(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("preferred_contact_start", "preferred_contact_end")
    @classmethod
    def validate_hhmm(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        parts = value.split(":")
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            raise ValueError("time must be HH:MM")
        hour, minute = map(int, parts)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("time must be HH:MM")
        return f"{hour:02d}:{minute:02d}"


class TemporalProjection(BaseModel):
    operator_timezone: str
    contact_timezone: Optional[str] = None
    contact_timezone_known: bool = False
    effective_timezone: str
    precision: Literal["contact", "operator_fallback"]
    local_time: datetime
    daypart: Literal["morning", "afternoon", "evening", "night"]
    preferred_contact_start: Optional[str] = None
    preferred_contact_end: Optional[str] = None
    defer_recommended: bool = False
    defer_until: Optional[datetime] = None
    defer_reason: Optional[str] = None


class RelationshipMetrics(BaseModel):
    stage: Literal["unknown", "new", "developing", "established"]
    momentum: Literal["unknown", "rising", "steady", "quiet", "cooling"]
    temperature: Literal["unknown", "warm", "neutral", "cool"]
    risk: Literal["unknown", "low", "watch", "elevated"]
    message_count: int
    session_count: int
    active_days: int
    last_interaction_at: Optional[datetime] = None
    last_inbound_at: Optional[datetime] = None
    last_outbound_at: Optional[datetime] = None
    basis: List[str] = Field(default_factory=list)


class GoalProjection(BaseModel):
    current: Optional[str] = None
    long_term: Optional[str] = None
    source_refs: List[str] = Field(default_factory=list)


class RelationshipDecision(BaseModel):
    action: Literal["reply", "defer", "no_reply", "next_action"]
    next_best_action: str
    why_now: List[str] = Field(default_factory=list)
    defer_until: Optional[datetime] = None


class RelationshipContextProjection(BaseModel):
    customer_id: str
    generated_at: datetime
    confirmed_facts: List[RelationshipMemoryEntry] = Field(default_factory=list)
    notes: List[RelationshipMemoryEntry] = Field(default_factory=list)
    dated_events: List[RelationshipMemoryEntry] = Field(default_factory=list)
    interests: List[RelationshipMemoryEntry] = Field(default_factory=list)
    shared_moments: List[RelationshipMemoryEntry] = Field(default_factory=list)
    open_loops: List[RelationshipMemoryEntry] = Field(default_factory=list)
    promises: List[RelationshipMemoryEntry] = Field(default_factory=list)
    boundaries: List[RelationshipMemoryEntry] = Field(default_factory=list)
    sensitive_topics: List[RelationshipMemoryEntry] = Field(default_factory=list)
    relationship: RelationshipMetrics
    temporal: TemporalProjection
    goals: GoalProjection = Field(default_factory=GoalProjection)
    decision: RelationshipDecision
    evidence_review: List[RelationshipEvidence] = Field(default_factory=list)
    journey: List[Dict[str, Any]] = Field(default_factory=list)
    graph_owner_status: Literal["not_required", "optional_held"] = "optional_held"
    graph_owner_reason: str = (
        "Graph memory is optional; canonical facts remain Customer/ChatHistory evidence."
    )
