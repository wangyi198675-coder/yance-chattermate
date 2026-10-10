"""Frozen-152 Yance Reply Brain / learning thin API.

Every endpoint delegates to existing ChatterMate owners.  No endpoint sends a
message; final delivery remains the canonical Conversation/Socket.IO path.
"""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.session_to_agent import _load_manageable_session
from app.core.auth import get_current_user, require_permissions
from app.database import get_db
from app.models.user import User
from app.models.customer import Customer
from app.repositories.agent import AgentRepository
from app.services.relationship_context import RelationshipContextError, set_long_term_goal
from app.services.yance_turn_authority import write_turn_controls, TurnAuthorityConflict
from app.services.yance_reply_runtime import (
    generate_reply_candidates,
    persona_history,
    promote_rule,
    record_candidate_evidence,
    rollback_persona,
    runtime_projection,
)

router = APIRouter()


class ReplyCandidateRequest(BaseModel):
    limit: Literal[3, 5] = 3
    expected_revision: str | None = None
    current_goal: str | None = Field(default=None, max_length=600)
    current_turn_correction: str | None = Field(default=None, max_length=800)
    current_turn_persona: str | None = Field(default=None, max_length=1600)
    allow_sensitive_context: bool = False
    strategy: str | None = Field(default="balanced", max_length=80)
    deep_reply: bool = False


class CurrentTurnControlsRequest(BaseModel):
    source_message_id: int = Field(ge=1)
    expected_version: int = Field(ge=0)
    current_goal: str | None = Field(default=None, max_length=600)
    allow_sensitive_context: bool = False


class LongTermGoalRequest(BaseModel):
    goal: str | None = Field(default=None, max_length=1000)


class ReplyEvidenceRequest(BaseModel):
    source_message_id: int
    context_revision: str = Field(min_length=1, max_length=240)
    candidate_id: str = Field(min_length=1, max_length=160)
    decision: Literal["adopt", "reject"]
    draft: str = Field(max_length=4000)
    do_not_learn: bool = False


class PromoteRuleRequest(BaseModel):
    scope: Literal["global", "contact"]
    rule: str = Field(min_length=1, max_length=1200)
    customer_id: str | None = None


@router.get("/sessions/{session_id}/reply-runtime")
async def get_reply_runtime(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = await _load_manageable_session(db, session_id, current_user)
    return runtime_projection(db, session)


@router.put("/sessions/{session_id}/reply-turn-controls")
async def put_reply_turn_controls(
    session_id: str,
    request: CurrentTurnControlsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    await _load_manageable_session(db, session_id, current_user)
    try:
        return write_turn_controls(
            db, session_id,
            source_message_id=request.source_message_id,
            expected_version=request.expected_version,
            current_goal=request.current_goal,
            allow_sensitive_context=request.allow_sensitive_context,
        )
    except TurnAuthorityConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.put("/sessions/{session_id}/long-term-goal")
async def put_long_term_goal(
    session_id: str,
    request: LongTermGoalRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = await _load_manageable_session(db, session_id, current_user)
    customer = db.query(Customer).filter(
        Customer.id == session.customer_id,
        Customer.organization_id == session.organization_id,
    ).first()
    if customer is None:
        raise HTTPException(status_code=404, detail="customer_missing")
    try:
        return set_long_term_goal(
            db, customer, request.goal, operator_ref=f"user:{current_user.id}"
        ).model_dump()
    except RelationshipContextError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/sessions/{session_id}/reply-candidates")
async def create_reply_candidates(
    session_id: str,
    request: ReplyCandidateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = await _load_manageable_session(db, session_id, current_user)
    try:
        return await generate_reply_candidates(
            db,
            session,
            limit=request.limit,
            expected_revision=request.expected_revision,
            current_goal=request.current_goal,
            current_turn_correction=request.current_turn_correction,
            current_turn_persona=request.current_turn_persona,
            allow_sensitive_context=request.allow_sensitive_context,
            strategy=request.strategy,
            deep_reply=request.deep_reply,
        )
    except ValueError as exc:
        # Explicit per-turn consent is a native owner-backed permission check,
        # not a caller-provided Boolean or implied Persona privilege.
        detail = str(exc)
        if detail == "sensitive_context_permission_required":
            raise HTTPException(status_code=403, detail=detail) from exc
        if detail == "current_turn_persona_invalid":
            raise HTTPException(status_code=422, detail=detail) from exc
        raise HTTPException(status_code=400, detail="reply_candidate_scope_invalid") from exc
    except RuntimeError as exc:
        code = str(exc)
        safe_codes = {
            "reply_agent_unavailable",
            "active_ai_config_unavailable",
            "reply_candidate_envelope_invalid",
            "reply_candidate_state_invalid",
            "reply_candidate_list_invalid",
        }
        detail = code if code in safe_codes else "reply_generation_unavailable"
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail) from exc


@router.post("/sessions/{session_id}/reply-evidence")
async def create_reply_evidence(
    session_id: str,
    request: ReplyEvidenceRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = await _load_manageable_session(db, session_id, current_user)
    try:
        result = record_candidate_evidence(
            db,
            session,
            source_message_id=request.source_message_id,
            context_revision_at_generation=request.context_revision,
            candidate_id=request.candidate_id,
            decision=request.decision,
            draft=request.draft,
            do_not_learn=request.do_not_learn,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result.get("stale"):
        raise HTTPException(status_code=409, detail={"code": "reply_context_stale", **result})
    return result


@router.post("/agents/{agent_id}/learning/rules")
async def create_durable_rule(
    agent_id: UUID,
    request: PromoteRuleRequest,
    current_user: User = Depends(require_permissions("manage_agents")),
    db: Session = Depends(get_db),
):
    agent = AgentRepository(db).get_agent_in_org(agent_id, current_user.organization_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    try:
        return promote_rule(
            db,
            agent,
            scope=request.scope,
            rule=request.rule,
            customer_id=request.customer_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/agents/{agent_id}/learning/history")
async def get_learning_history(
    agent_id: UUID,
    current_user: User = Depends(require_permissions("manage_agents")),
    db: Session = Depends(get_db),
):
    agent = AgentRepository(db).get_agent_in_org(agent_id, current_user.organization_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"versions": persona_history(agent)}


@router.post("/agents/{agent_id}/learning/history/{transaction_id}/rollback")
async def rollback_learning_history(
    agent_id: UUID,
    transaction_id: int,
    current_user: User = Depends(require_permissions("manage_agents")),
    db: Session = Depends(get_db),
):
    agent = AgentRepository(db).get_agent_in_org(agent_id, current_user.organization_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    try:
        return rollback_persona(db, agent, transaction_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/goal-owner")
async def get_goal_owner_status(
    current_user: User = Depends(get_current_user),
):
    # Goal is explicit confirmed metadata in the admitted Customer relationship owner.
    return {
        "current_turn_goal": "available",
        "long_term_goal": "available",
        "long_term_goal_owner": "Customer.meta_data.relationship_memory",
    }
