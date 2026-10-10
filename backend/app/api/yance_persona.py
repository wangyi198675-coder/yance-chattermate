"""Window176 Persona Seed / Style Corpus / Growth API.

All writes delegate to existing ChatterMate persistence owners. Nothing here
sends messages or creates an independent Persona/learning runtime.
"""
from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import require_permissions
from app.database import get_db
from app.models.user import User
from app.repositories.agent import AgentRepository
from app.services.yance_persona_growth import (
    _compose_global_base_instructions,
    add_style_text_source,
    clear_scope,
    compare_seeds,
    current_projection,
    extract_style_features,
    get_seed,
    import_seed,
    list_guidelines,
    list_seeds,
    mark_style_source,
    persona_history,
    review_guideline,
    rollback_persona,
    set_seed_scope,
)


router = APIRouter()


class BasePersonaRequest(BaseModel):
    instructions: list[str] = Field(min_length=1, max_length=100)


class SeedImportRequest(BaseModel):
    card: dict[str, Any]
    provenance: str = Field(min_length=1, max_length=1200)
    consent: bool = False


class SeedCompareRequest(BaseModel):
    seed_ids: list[str] = Field(min_length=2, max_length=3)


class SeedSelectRequest(BaseModel):
    seed_id: str = Field(min_length=1, max_length=120)
    scope: Literal["global", "contact", "conversation", "turn"]
    customer_id: UUID | None = None
    session_id: UUID | None = None


class ClearScopeRequest(BaseModel):
    scope: Literal["contact", "conversation"]
    customer_id: UUID | None = None
    session_id: UUID | None = None


class StyleSourceRequest(BaseModel):
    provenance: str = Field(min_length=1, max_length=1200)
    consent: bool = False
    source_kind: str = Field(default="authorized-web-or-chat", max_length=80)


class StyleTextRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1, max_length=200_000)
    provenance: str = Field(min_length=1, max_length=1200)
    consent: bool = False
    source_kind: str = Field(default="authorized-chat", max_length=80)


class GuidelineReviewRequest(BaseModel):
    decision: Literal["adopt", "edit", "reject"]
    condition: str = Field(default="MATCH_ALWAYS", max_length=1200)
    action: str = Field(default="", max_length=1600)
    description: str | None = Field(default=None, max_length=2400)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    evidence_ids: list[str] = Field(default_factory=list, max_length=80)
    provenance: str = Field(default="", max_length=1200)


def _agent_or_404(db: Session, user: User, agent_id: UUID):
    agent = AgentRepository(db).get_agent_in_org(agent_id, user.organization_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


def _bad_request(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@router.get("/agents/{agent_id}")
async def get_persona_projection(
    agent_id: UUID,
    customer_id: UUID | None = Query(default=None),
    session_id: UUID | None = Query(default=None),
    current_user: User = Depends(require_permissions("manage_agents")),
    db: Session = Depends(get_db),
):
    agent = _agent_or_404(db, current_user, agent_id)
    return current_projection(
        db,
        agent,
        customer_id=customer_id,
        session_id=session_id,
    )


@router.put("/agents/{agent_id}/base")
async def update_base_persona(
    agent_id: UUID,
    request: BasePersonaRequest,
    current_user: User = Depends(require_permissions("manage_agents")),
    db: Session = Depends(get_db),
):
    agent = _agent_or_404(db, current_user, agent_id)
    instructions = [" ".join(item.split()).strip() for item in request.instructions]
    instructions = [item for item in instructions if item]
    if not instructions:
        raise HTTPException(status_code=400, detail="base_persona_instructions_required")
    try:
        instructions = _compose_global_base_instructions(agent.instructions, instructions)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    AgentRepository(db).update_agent(agent.id, instructions=instructions)
    return {
        "updated": True,
        "owner": "Agent.instructions",
        "instructions": instructions,
    }


@router.post("/agents/{agent_id}/seeds/import")
async def import_persona_seed(
    agent_id: UUID,
    request: SeedImportRequest,
    current_user: User = Depends(require_permissions("manage_agents")),
    db: Session = Depends(get_db),
):
    agent = _agent_or_404(db, current_user, agent_id)
    try:
        return import_seed(
            db,
            agent,
            request.card,
            provenance=request.provenance,
            consent=request.consent,
        )
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.get("/agents/{agent_id}/seeds")
async def get_persona_seeds(
    agent_id: UUID,
    current_user: User = Depends(require_permissions("manage_agents")),
    db: Session = Depends(get_db),
):
    agent = _agent_or_404(db, current_user, agent_id)
    return {"seeds": list_seeds(db, agent)}


@router.post("/agents/{agent_id}/seeds/compare")
async def compare_persona_seeds(
    agent_id: UUID,
    request: SeedCompareRequest,
    current_user: User = Depends(require_permissions("manage_agents")),
    db: Session = Depends(get_db),
):
    agent = _agent_or_404(db, current_user, agent_id)
    try:
        return compare_seeds(db, agent, request.seed_ids)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/agents/{agent_id}/seeds/select")
async def select_persona_seed(
    agent_id: UUID,
    request: SeedSelectRequest,
    current_user: User = Depends(require_permissions("manage_agents")),
    db: Session = Depends(get_db),
):
    agent = _agent_or_404(db, current_user, agent_id)
    try:
        seed = get_seed(db, agent, request.seed_id)
        result = set_seed_scope(
            db,
            agent,
            seed,
            scope=request.scope,
            customer_id=request.customer_id,
            session_id=request.session_id,
        )
        # Keep the UI's three semantic sections explicit instead of forcing it
        # to reverse-engineer free-text instructions.
        result["identity_facts"] = seed.get("identity_facts", {})
        result["style_traits"] = seed.get("style_traits", {})
        result["relationship_rules"] = seed.get("relationship_rules", {})
        return result
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/agents/{agent_id}/scope/clear")
async def clear_persona_scope(
    agent_id: UUID,
    request: ClearScopeRequest,
    current_user: User = Depends(require_permissions("manage_agents")),
    db: Session = Depends(get_db),
):
    agent = _agent_or_404(db, current_user, agent_id)
    try:
        clear_scope(
            db,
            agent,
            scope=request.scope,
            customer_id=request.customer_id,
            session_id=request.session_id,
        )
        return {"cleared": True, "scope": request.scope}
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/agents/{agent_id}/style-sources/{knowledge_id}")
async def enable_style_learning_for_source(
    agent_id: UUID,
    knowledge_id: int,
    request: StyleSourceRequest,
    current_user: User = Depends(require_permissions("manage_agents")),
    db: Session = Depends(get_db),
):
    agent = _agent_or_404(db, current_user, agent_id)
    try:
        return mark_style_source(
            db,
            agent,
            knowledge_id,
            provenance=request.provenance,
            consent=request.consent,
            source_kind=request.source_kind,
        )
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/agents/{agent_id}/style-text")
async def add_authorized_style_text(
    agent_id: UUID,
    request: StyleTextRequest,
    current_user: User = Depends(require_permissions("manage_agents")),
    db: Session = Depends(get_db),
):
    agent = _agent_or_404(db, current_user, agent_id)
    try:
        knowledge = add_style_text_source(
            db,
            agent,
            title=request.title,
            content=request.content,
            provenance=request.provenance,
            consent=request.consent,
            source_kind=request.source_kind,
        )
        return {
            "knowledge_id": knowledge.id,
            "source": knowledge.source,
            "style_learning": True,
            "persona_mutation": False,
        }
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/agents/{agent_id}/style-extract")
async def propose_style_features(
    agent_id: UUID,
    current_user: User = Depends(require_permissions("manage_agents")),
    db: Session = Depends(get_db),
):
    agent = _agent_or_404(db, current_user, agent_id)
    try:
        return await extract_style_features(db, agent)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except RuntimeError as exc:
        safe = {
            "active_ai_config_unavailable",
            "style_feature_envelope_invalid",
        }
        code = str(exc)
        raise HTTPException(status_code=503, detail=code if code in safe else "style_extraction_unavailable") from exc


@router.get("/agents/{agent_id}/guidelines")
async def get_reviewed_guidelines(
    agent_id: UUID,
    current_user: User = Depends(require_permissions("manage_agents")),
    db: Session = Depends(get_db),
):
    agent = _agent_or_404(db, current_user, agent_id)
    return {"guidelines": list_guidelines(db, agent)}


@router.post("/agents/{agent_id}/guidelines/review")
async def review_behavioral_guideline(
    agent_id: UUID,
    request: GuidelineReviewRequest,
    current_user: User = Depends(require_permissions("manage_agents")),
    db: Session = Depends(get_db),
):
    agent = _agent_or_404(db, current_user, agent_id)
    try:
        return review_guideline(
            db,
            agent,
            decision=request.decision,
            condition=request.condition,
            action=request.action,
            description=request.description,
            confidence=request.confidence,
            evidence_ids=request.evidence_ids,
            provenance=request.provenance,
        )
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.get("/agents/{agent_id}/history")
async def get_persona_history(
    agent_id: UUID,
    current_user: User = Depends(require_permissions("manage_agents")),
    db: Session = Depends(get_db),
):
    agent = _agent_or_404(db, current_user, agent_id)
    return {"versions": persona_history(agent)}


@router.post("/agents/{agent_id}/history/{transaction_id}/rollback")
async def rollback_persona_version(
    agent_id: UUID,
    transaction_id: int,
    current_user: User = Depends(require_permissions("manage_agents")),
    db: Session = Depends(get_db),
):
    agent = _agent_or_404(db, current_user, agent_id)
    try:
        return rollback_persona(db, agent, transaction_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
