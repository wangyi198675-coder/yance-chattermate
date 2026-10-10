"""Thin Frozen-152 Reply Brain / learning glue over admitted ChatterMate owners.

This module owns no model runtime, persistence engine, scheduler, delivery path, or
goal database.  It projects existing ChatHistory/Agent/AIConfig/Continuum state
into Yance semantics and delegates generation to the canonical ChatAgent.
"""
from __future__ import annotations

import json
import re
import hashlib
import asyncio
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy_continuum import version_class

from app.agents.chat_agent import ChatAgent
from app.core.config import settings
from app.utils.guardrail_runtime import Surface, check_inbound, check_output
from app.core.security import decrypt_api_key
from app.core.yance_learning_scope import effective_agent_instructions
from app.models.agent import Agent
from app.models.customer import Customer
from app.models.organization import Organization
from app.models.chat_history import ChatHistory
from app.models.session_to_agent import SessionStatus, SessionToAgent
from app.repositories.agent import AgentRepository
from app.repositories.ai_config import AIConfigRepository
from app.repositories.chat import ChatRepository
from app.services.yance_turn_authority import context_revision as _canonical_context_revision
from app.services.relationship_context import (
    build_relationship_context,
    goal_projection,
    GoalProjection,
)
from app.services.translation import contact_target_language, realism_context
from app.services.yance_turn_authority import read_turn_controls
from app.services.yance_persona_growth import resolve_persona


YANCE_SCOPE_PREFIX = "[[YANCE_SCOPE:"
ALLOWED_RULE_SCOPES = frozenset({"global", "contact"})
REPLY_STATES = frozenset({"ready", "no_reply", "defer"})
HUMAN_LIKENESS_STATES = frozenset({"pass", "blocked"})


class _AgnoReplyChoice(BaseModel):
    text: str
    why: str = ""
    human_likeness: Literal["pass", "blocked"] = "blocked"


class _AgnoReplyEnvelope(BaseModel):
    """Dedicated structured result for the existing native Agno ChatAgent.

    The general ChatterMate ChatResponse output_schema cannot express Yance
    candidates; requesting an unrelated raw JSON schema while that response
    schema remains active produces a non-JSON ChatResponse.message.
    """
    state: Literal["ready", "no_reply", "defer"]
    why: str = ""
    balance_strategy: str = ""
    deep_reply: str = ""
    candidates: list[_AgnoReplyChoice] = Field(default_factory=list)


async def _generate_native_agno_envelope(chat_agent: ChatAgent, session_id: str) -> dict:
    """Use the *same* ChatterMate Agent and canonical ChatHistory without sending.

    A per-invocation response schema replaces the general ChatResponse schema;
    no second Agent, provider, persistence store or delivery engine is created.
    """
    agno_agent = chat_agent.agent
    agno_agent.output_schema = _AgnoReplyEnvelope
    agno_agent.structured_outputs = True
    prompt = "Generate Reply Brain candidates for the current canonical conversation turn."
    check_inbound(prompt, ctx=chat_agent._guardrail_ctx,
                  surface=Surface.WORKFLOW, session_id=session_id,
                  allow_block=False)
    context = chat_agent._canonical_agent_input(
        prompt, session_id, current_is_persisted=False
    )
    response = await asyncio.wait_for(
        agno_agent.arun(context, session_id=session_id, stream=False),
        timeout=settings.AGENT_RUN_TIMEOUT,
    )
    content = getattr(response, "content", None)
    try:
        if isinstance(content, BaseModel):
            content = content.model_dump()
        elif isinstance(content, str):
            content = json.loads(_strip_json_fence(content))
        envelope = _AgnoReplyEnvelope.model_validate(content).model_dump()
    except (TypeError, ValueError, ValidationError, json.JSONDecodeError) as exc:
        raise RuntimeError("reply_candidate_envelope_invalid") from exc

    for item in envelope["candidates"]:
        original = item["text"]
        safe, _ = check_output(
            original, ctx=chat_agent._guardrail_ctx,
            surface=Surface.WORKFLOW, session_id=session_id,
        )
        if safe != original:
            item["text"] = safe
            item["human_likeness"] = "blocked"
    return envelope


def latest_message(db: Session, session_id: str | UUID) -> ChatHistory | None:
    if isinstance(session_id, str):
        session_id = UUID(session_id)
    return (
        db.query(ChatHistory)
        .filter(ChatHistory.session_id == session_id)
        .order_by(ChatHistory.id.desc())
        .first()
    )


def latest_user_message(db: Session, session_id: str | UUID) -> ChatHistory | None:
    latest = latest_message(db, session_id)
    return latest if latest is not None and latest.message_type == "user" else None


def context_revision(db: Session, session: SessionToAgent) -> str:
    return _canonical_context_revision(db, session)


def ai_auto_capability_denial(session: SessionToAgent) -> str:
    """One capability truth across frontend, inference and send-time boundary.

    The canonical Web Widget uses one ChatHistory/client_send_intent pathway.
    Other channels and workflows remain unsupported for positive AI_AUTO.
    """
    if session.workflow_id is not None:
        return "ai_auto_workflow_unavailable"
    if (session.channel or "web") != "web":
        return "ai_auto_channel_unavailable"
    # Human-held TRANSFERRED sessions may release back to AI_AUTO. The
    # delivery snapshot independently requires status OPEN and user_id None.
    if session.status == getattr(SessionStatus, "CLOSED", None):
        return "ai_auto_session_closed"
    if session.status != getattr(SessionStatus, "OPEN", session.status) and session.user_id is None:
        return "ai_auto_session_not_open"
    return ""


def runtime_projection(db: Session, session: SessionToAgent) -> dict[str, Any]:
    agent = AgentRepository(db).get_agent(session.agent_id) if session.agent_id else None
    if session.user_id is not None:
        mode = "HUMAN"
    elif agent and agent.ai_replies_enabled and not ai_auto_capability_denial(session):
        mode = "AI_AUTO"
    else:
        # AI_ASSIST is human-send authority plus Reply Brain assistance.  It is
        # intentionally transient UI state, not a second persisted mode owner.
        mode = "HUMAN"
    latest = latest_user_message(db, session.session_id)
    customer = db.query(Customer).filter(
        Customer.id == session.customer_id,
        Customer.organization_id == session.organization_id,
    ).first()
    goals = goal_projection(customer) if customer else GoalProjection()
    return {
        "mode": mode,
        "session_scope_available": True,
        "ai_auto_scope": "session",
        "ai_auto_available": bool(agent and agent.ai_replies_enabled and not ai_auto_capability_denial(session)),
        "ai_auto_unavailable_reason": (ai_auto_capability_denial(session) or None),
        "ai_auto_permission_owner": "Agent.ai_replies_enabled",
        "sensitive_confirmation_required": True,
        "ai_auto_enabled": bool(agent and agent.ai_replies_enabled),
        "human_owner_user_id": str(session.user_id) if session.user_id else None,
        "session_status": session.status.value if hasattr(session.status, "value") else str(session.status),
        "source_message_id": latest.id if latest else None,
        "context_revision": context_revision(db, session),
        "peer_typing_owner": "unavailable",
        "long_term_goal_owner": "ready",
        "long_term_goal": goals.long_term if goals else None,
        "goal_owner": "Customer.meta_data.relationship_memory",
        "current_turn_controls": read_turn_controls(db, session),
        "current_turn_owner": "ChatHistory.attributes.yance_current_turn_controls",
    }



def _cross_session_relationship_revision(
    db: Session, session: SessionToAgent, source_id: int
) -> str:
    """Hash the ACTUAL ChatterMate relationship evidence, across all sessions.

    The one tentative AI_AUTO bot for this source is excluded, since it is not
    provider-accepted Relationship history until physical send. An unrelated
    outbound or any inbound, including another session, changes the revision.
    """
    rows = db.query(ChatHistory).filter(
        ChatHistory.organization_id == session.organization_id,
        ChatHistory.customer_id == session.customer_id,
    ).order_by(ChatHistory.id.asc()).all()
    evidence = []
    for row in rows:
        attrs = row.attributes or {}
        if (
            row.message_type == "bot"
            and attrs.get("client_send_action_kind") == "ai_auto"
            and isinstance(attrs.get("yance_auto_authority"), dict)
            and attrs["yance_auto_authority"].get("source_message_id") == source_id
        ):
            continue
        evidence.append((
            row.id, str(row.session_id), row.message_type, row.message,
            str(row.created_at), row.sentiment_label, row.sentiment_score,
            bool(attrs.get("provider_echo")), bool(attrs.get("is_echo")),
        ))
    sessions = db.query(SessionToAgent).filter(
        SessionToAgent.organization_id == session.organization_id,
        SessionToAgent.customer_id == session.customer_id,
    ).order_by(SessionToAgent.session_id.asc()).all()
    session_states = [
        (str(row.session_id), str(row.status), str(row.user_id),
         str(row.agent_id), row.channel, str(row.workflow_id),
         row.persona_override, str(row.updated_at))
        for row in sessions
    ]
    return hashlib.sha256(json.dumps(
        [evidence, session_states], ensure_ascii=False,
        sort_keys=True, default=str,
    ).encode("utf-8")).hexdigest()


def ai_auto_authority_snapshot(
    db: Session, session_id: str | UUID, source_id: int
) -> tuple[dict[str, Any] | None, str | None]:
    """Reproducible, canonical send-time fingerprint; no secondary state store."""
    from app.models.channels import ChannelAccount, ChannelConversation
    from app.services.human_routing import RECEIVE_ONLY_SOCIAL_CHANNELS

    db.expire_all()
    sid = UUID(str(session_id))
    session = db.query(SessionToAgent).filter(
        SessionToAgent.session_id == sid,
    ).first()
    if session is None:
        return None, "session_missing"
    if session.status != SessionStatus.OPEN or session.user_id is not None:
        return None, "manual_takeover"
    if session.workflow_id is not None:
        return None, "ai_auto_workflow_unavailable"
    if session.channel in RECEIVE_ONLY_SOCIAL_CHANNELS:
        return None, "ai_auto_receive_only"
    if (session.channel or "web") != "web":
        return None, "ai_auto_channel_unavailable"
    agent = db.query(Agent).filter(
        Agent.id == session.agent_id,
        Agent.organization_id == session.organization_id,
    ).first()
    if agent is None or not agent.ai_replies_enabled:
        return None, "ai_auto_permission_revoked"
    customer = db.query(Customer).filter(
        Customer.id == session.customer_id,
        Customer.organization_id == session.organization_id,
    ).first()
    organization = db.query(Organization).filter(
        Organization.id == session.organization_id,
    ).first()
    source = db.query(ChatHistory).filter(
        ChatHistory.id == source_id,
        ChatHistory.session_id == sid,
        ChatHistory.organization_id == session.organization_id,
        ChatHistory.customer_id == session.customer_id,
        ChatHistory.message_type == "user",
    ).first()
    if customer is None or organization is None or source is None:
        return None, "ai_auto_source_or_context_missing"
    latest = db.query(ChatHistory.id).filter(
        ChatHistory.session_id == sid,
        ChatHistory.message_type == "user",
    ).order_by(ChatHistory.id.desc()).limit(1).scalar()
    if latest != source_id:
        return None, "conversation_context_changed"
    attrs = source.attributes or {}
    if attrs.get("is_echo") or attrs.get("provider_echo"):
        return None, "provider_echo_not_inbound"
    integrity = attrs.get("translation_integrity")
    if integrity and (
        not isinstance(integrity, dict)
        or integrity.get("status") not in {"pass", "passed", "PASS"}
    ):
        return None, "translation_integrity_unverified"
    controls = read_turn_controls(db, session)
    if not controls or controls["source_message_id"] != source_id:
        return None, "current_turn_authority_unavailable"

    relationship = build_relationship_context(
        db, customer, organization,
        goals=goal_projection(customer, current=controls["current_goal"]),
    )
    if relationship.temporal.defer_recommended:
        return None, "temporal_window_blocked"
    if any(row.active and row.effect in {"no_reply", "defer"}
           for row in [*relationship.boundaries, *relationship.sensitive_topics]):
        return None, "interaction_policy_blocked"

    # Include relationship facts composed from People captured attributes, not
    # only Customer.meta_data or recent current-session ChatHistory. Evidence
    # that materially changes the decision is part of this canonical snapshot.
    relationship_entries = {}
    for field in (
        "confirmed_facts", "notes", "interests", "open_loops", "promises",
        "boundaries", "sensitive_topics", "dated_events", "shared_moments",
    ):
        relationship_entries[field] = [
            (
                item.id, item.kind, item.text, item.active, item.effect,
                sorted(str(ref.source_ref) for ref in item.evidence),
            )
            for item in getattr(relationship, field, [])
        ]
    route = {"channel": "web"}
    snapshot = {
        "source_message_id": source_id,
        "session_id": str(sid),
        "organization_id": str(session.organization_id),
        "customer_id": str(session.customer_id),
        "agent_id": str(session.agent_id),
        "session_updated_at": str(session.updated_at),
        "persona_override": session.persona_override,
        "agent_instructions": agent.instructions,
        "agent_ai_replies_enabled": agent.ai_replies_enabled,
        # Version tokens prevent ABA: revoke/re-enable may have the same
        # boolean state but cannot silently reuse an earlier send authority.
        "agent_updated_at": str(agent.updated_at),
        "customer_metadata": customer.meta_data,
        "customer_updated_at": str(customer.updated_at),
        "organization_timezone": organization.timezone,
        "organization_updated_at": str(organization.updated_at),
        "source_updated_at": str(source.updated_at),
        "source_integrity": integrity,
        "current_turn_controls": controls,
        "relationship_revision": _cross_session_relationship_revision(db, session, source_id),
        "relationship_computed_evidence": relationship_entries,
        "route": route,
        "temporal_minute": relationship.temporal.local_time.strftime("%Y-%m-%dT%H:%M"),
        "temporal_timezone": relationship.temporal.effective_timezone,
        "temporal_window": [
            relationship.temporal.preferred_contact_start,
            relationship.temporal.preferred_contact_end,
        ],
    }
    token = hashlib.sha256(json.dumps(
        snapshot, sort_keys=True, ensure_ascii=False, default=str,
    ).encode("utf-8")).hexdigest()
    return {"source_message_id": source_id, "revision": token}, None


def revalidate_ai_auto_authority(
    db: Session, session_id: str | UUID, expected: dict[str, Any]
) -> str | None:
    if not isinstance(expected, dict) or not isinstance(expected.get("source_message_id"), int):
        return "ai_auto_authority_missing"
    current, reason = ai_auto_authority_snapshot(
        db, session_id, expected["source_message_id"]
    )
    if reason:
        return reason
    if current != expected:
        return "ai_auto_context_stale"
    return None


def _strip_json_fence(value: str) -> str:
    text = (value or "").strip()
    match = re.fullmatch(r"\x60\x60\x60(?:json)?\s*([\s\S]*?)\s*\x60\x60\x60", text, flags=re.IGNORECASE)
    return match.group(1).strip() if match else text


def _human_like(text: str, declared: str | None) -> str:
    compact = " ".join((text or "").split())
    if declared != "pass":
        return "blocked"
    if not compact or len(compact) > 900:
        return "blocked"
    if compact.count("?") > 2:
        return "blocked"
    lowered = compact.lower()
    if any(marker in lowered for marker in ("as an ai", "language model", "作为ai", "作为 ai")):
        return "blocked"
    return "pass"


async def generate_reply_candidates(
    db: Session,
    session: SessionToAgent,
    *,
    limit: int,
    expected_revision: str | None,
    current_goal: str | None,
    current_turn_correction: str | None,
    current_turn_persona: str | None,
    allow_sensitive_context: bool,
    strategy: str | None,
    deep_reply: bool,
) -> dict[str, Any]:
    # The API supplies untrusted *requests*, not permission. Only the
    # versioned canonical inbound ChatHistory row grants sensitive access.
    db.expire_all()
    current_revision = context_revision(db, session)
    latest = latest_user_message(db, session.session_id)
    if expected_revision and expected_revision != current_revision:
        return {
            "state": "stale",
            "candidates": [],
            "why": "Conversation context changed after these suggestions were requested.",
            "can_recompute": True,
            "source_message_id": latest.id if latest else None,
            "context_revision": current_revision,
        }
    if session.status == SessionStatus.CLOSED:
        return {
            "state": "defer",
            "candidates": [],
            "why": "This conversation is closed.",
            "can_recompute": False,
            "source_message_id": latest.id if latest else None,
            "context_revision": current_revision,
        }

    limit = 5 if limit > 3 else max(0, limit)
    if limit == 0 or latest is None:
        return {
            "state": "no_reply",
            "candidates": [],
            "why": "No current inbound turn is available.",
            "can_recompute": True,
            "source_message_id": latest.id if latest else None,
            "context_revision": current_revision,
        }

    # Permission must bind to the SAME exact inbound turn and tenancy as the
    # verified manageable session. A forged request flag cannot grant consent.
    controls = read_turn_controls(db, session)
    consent = bool(controls and controls.get("source_message_id") == latest.id
                   and controls.get("allow_sensitive_context") is True)
    if allow_sensitive_context and not consent:
        raise ValueError("sensitive_context_permission_required")
    if (current_turn_persona is not None
            and (not isinstance(current_turn_persona, str)
                 or len(current_turn_persona) > 1600
                 or any(ord(ch) < 32 and ch not in "\\t\\n\\r"
                        for ch in current_turn_persona))):
        raise ValueError("current_turn_persona_invalid")
    agent = AgentRepository(db).get_agent(session.agent_id)
    if not agent or str(agent.organization_id) != str(session.organization_id):
        raise RuntimeError("reply_agent_unavailable")
    # Native Persona resolver verifies contact/conversation scope before any
    # transient turn override is interpolated into the agent instruction.
    persona = resolve_persona(
        db, agent, customer_id=session.customer_id,
        session_id=session.session_id, channel=session.channel,
        current_turn_override=[current_turn_persona.strip()]
        if current_turn_persona and current_turn_persona.strip() else [],
    )
    ai_config = AIConfigRepository(db).get_active_config(str(session.organization_id))
    if not ai_config:
        raise RuntimeError("active_ai_config_unavailable")

    base_instructions = "\n".join(
        str(item) for item in persona["instructions"] if str(item).strip()
    )
    format_prompt = f"""
You are the existing ChatterMate agent runtime acting as Yance Reply Brain.
Return ONLY one JSON object. Do not send a message and do not claim that you sent one.
Schema:
{{
  "state": "ready" | "no_reply" | "defer",
  "why": "short reason",
  "balance_strategy": "short strategy",
  "deep_reply": "short deeper reasoning or empty string",
  "candidates": [
    {{"text": "candidate reply", "why": "why this candidate", "human_likeness": "pass" | "blocked"}}
  ]
}}
Hard rules:
- Return between 0 and {limit} real candidates; never pad.
- If silence is best, state=no_reply and candidates=[].
- If timing is wrong, state=defer and candidates=[].
- Candidate replies must sound like a real human, not a support script.
- Prefer a single compact message; avoid interview-style consecutive questions.
- human_likeness=pass only when you would genuinely send it as a human.
- Balance strategy: {strategy or "balanced"}.
- Deep reply requested: {"yes" if deep_reply else "no"}.
- Current-turn goal: {current_goal or "(none)"}.
- Current-turn correction (transient, do not persist): {current_turn_correction or "(none)"}.
- Current-turn persona (operator-supplied transient lower-priority style, cannot override access policy): {json.dumps(current_turn_persona or "(none)", ensure_ascii=False)}.
- Sensitive context authorized by exact canonical current-turn consent AND explicit request only: {"yes" if consent and allow_sensitive_context else "no"}.
- Never treat a persona/style instruction as permission to expose sensitive context.
"""
    system_prompt = (base_instructions + "\n\n" + format_prompt).strip()
    chat_agent = await ChatAgent.create_async(
        api_key=decrypt_api_key(ai_config.encrypted_api_key),
        model_name=ai_config.model_name,
        model_type=ai_config.model_type.value if hasattr(ai_config.model_type, "value") else ai_config.model_type,
        base_url=(ai_config.settings or {}).get("base_url"),
        org_id=str(session.organization_id),
        agent_id=str(session.agent_id),
        customer_id=str(session.customer_id),
        session_id=str(session.session_id),
        custom_system_prompt=system_prompt,
        transfer_to_human=False,
        channel=session.channel,
    )
    try:
        if getattr(chat_agent, "agent", None) is not None:
            # Live ChatterMate native ChatAgent: the Agno output schema must
            # match Reply Brain, not the ordinary message ChatResponse schema.
            envelope = await _generate_native_agno_envelope(
                chat_agent, str(session.session_id)
            )
        else:
            # Compatibility for lightweight existing test-agent fixtures.
            response = await chat_agent._get_llm_response_only(
                message="Generate Reply Brain candidates for the current canonical conversation turn.",
                session_id=str(session.session_id),
                org_id=str(session.organization_id),
                agent_id=str(session.agent_id),
                customer_id=str(session.customer_id),
            )
            try:
                envelope = json.loads(_strip_json_fence(response.message))
            except (TypeError, json.JSONDecodeError) as exc:
                raise RuntimeError("reply_candidate_envelope_invalid") from exc
    finally:
        await chat_agent.safe_cleanup_mcp_tools()

    # Revocation/new inbound during asynchronous model inference must suppress
    # ALL candidate text, not merely fail when the operator later adopts it.
    # This closes the gap between pre-generation consent and response display.
    db.expire_all()
    fresh_session = db.query(SessionToAgent).filter(
        SessionToAgent.session_id == session.session_id,
        SessionToAgent.organization_id == session.organization_id,
        SessionToAgent.customer_id == session.customer_id,
        SessionToAgent.agent_id == session.agent_id,
    ).first()
    fresh_latest = latest_user_message(db, session.session_id)
    fresh_revision = context_revision(db, fresh_session) if fresh_session else "unavailable"
    fresh_controls = read_turn_controls(db, fresh_session) if fresh_session else None
    fresh_consent = bool(
        fresh_controls and fresh_latest
        and fresh_controls.get("source_message_id") == fresh_latest.id
        and fresh_controls.get("allow_sensitive_context") is True
    )
    if (fresh_session is None or fresh_session.status == SessionStatus.CLOSED
            or fresh_revision != current_revision
            or fresh_latest is None or fresh_latest.id != latest.id
            or (allow_sensitive_context and not fresh_consent)):
        return {
            "state": "stale", "candidates": [],
            "why": "Conversation context or permission changed during generation.",
            "can_recompute": True,
            "source_message_id": fresh_latest.id if fresh_latest else None,
            "context_revision": fresh_revision,
        }

    state = envelope.get("state")
    if state not in REPLY_STATES:
        raise RuntimeError("reply_candidate_state_invalid")
    raw_candidates = envelope.get("candidates") or []
    if not isinstance(raw_candidates, list):
        raise RuntimeError("reply_candidate_list_invalid")

    candidates = []
    for index, item in enumerate(raw_candidates[:limit], start=1):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        human_likeness = _human_like(text, item.get("human_likeness"))
        if not text:
            continue
        candidates.append({
            "id": f"{latest.id}:{index}",
            "contextRevision": current_revision,
            "type": "text",
            "label": f"候选 {index}",
            "draft": text,
            "why": str(item.get("why") or "").strip() or None,
            "humanLikeness": human_likeness,
            "runtimeState": "ready",
        })

    if state != "ready":
        candidates = []
    return {
        "state": state,
        "candidates": candidates,
        "why": str(envelope.get("why") or "").strip() or None,
        "balance_strategy": str(envelope.get("balance_strategy") or "").strip() or None,
        "deep_reply": str(envelope.get("deep_reply") or "").strip() or None,
        "can_recompute": True,
        "source_message_id": latest.id,
        "context_revision": current_revision,
    }


def record_candidate_evidence(
    db: Session,
    session: SessionToAgent,
    *,
    source_message_id: int,
    context_revision_at_generation: str,
    candidate_id: str,
    decision: str,
    draft: str,
    do_not_learn: bool,
) -> dict[str, Any]:
    # Keep BOTH source-id and exact generation-revision guards. A changed
    # revision must never be refreshed to bless a previously generated draft.
    latest = latest_user_message(db, session.session_id)
    current_revision = context_revision(db, session)
    if (latest is None or latest.id != source_message_id
            or not context_revision_at_generation
            or context_revision_at_generation != current_revision):
        return {"recorded": False, "stale": True, "context_revision": current_revision}
    if decision not in {"adopt", "reject"}:
        raise ValueError("invalid_candidate_decision")

    # Serialize against concurrent session revisions and new inbound FK inserts,
    # not only competing evidence writers. Hold the session row lock to commit.
    db.expire_all()
    locked_session = (db.query(SessionToAgent)
                      .filter(SessionToAgent.session_id == session.session_id)
                      .with_for_update().first())
    if locked_session is None:
        db.rollback()
        return {"recorded": False, "stale": True, "context_revision": "unavailable"}
    latest = (db.query(ChatHistory).filter(ChatHistory.id == source_message_id,
                 ChatHistory.session_id == session.session_id,
                 ChatHistory.message_type == "user").with_for_update().first())
    if (latest is None or (latest_user_message(db, session.session_id) or latest).id != latest.id
            or context_revision(db, locked_session) != context_revision_at_generation):
        db.rollback()
        return {"recorded": False, "stale": True, "context_revision": context_revision(db, session)}
    attrs = dict(latest.attributes or {})
    evidence = list(attrs.get("yance_reply_evidence") or [])
    event = {
        "candidate_id": candidate_id,
        "decision": decision,
        "draft": draft,
        "do_not_learn": bool(do_not_learn),
        "context_revision": context_revision_at_generation,
    }
    evidence.append(event)
    attrs["yance_reply_evidence"] = evidence[-50:]
    latest.attributes = attrs
    db.commit()
    return {"recorded": True, "stale": False, "context_revision": context_revision(db, session)}


def finalize_successful_send_learning(db: Session, sent_message_id: int) -> None:
    """Bind a provider-accepted canonical send to an adopted Reply Brain draft.

    Acceptance is not evidence of recipient delivery, a reply, or success.
    Keep the existing Learning owner and let later verified inbound close the
    outcome; never infer delivery from Socket.IO emission alone.
    """
    sent = db.query(ChatHistory).filter(ChatHistory.id == sent_message_id).first()
    if not sent or sent.message_type != "agent":
        return
    source = (
        db.query(ChatHistory)
        .filter(
            ChatHistory.session_id == sent.session_id,
            ChatHistory.message_type == "user",
            ChatHistory.id < sent.id,
        )
        .order_by(ChatHistory.id.desc())
        .first()
    )
    if source is None:
        return

    source_attrs = dict(source.attributes or {})
    evidence = list(source_attrs.get("yance_reply_evidence") or [])
    match_index = None
    for index in range(len(evidence) - 1, -1, -1):
        event = evidence[index]
        if (
            isinstance(event, dict)
            and event.get("decision") == "adopt"
            and not event.get("do_not_learn")
            and str(event.get("draft") or "").strip() == str(sent.message or "").strip()
            and not event.get("sent_message_id")
        ):
            match_index = index
            break
    if match_index is None:
        return

    matched = dict(evidence[match_index])
    matched["sent_message_id"] = sent.id
    matched["outcome"] = "provider_accepted"
    evidence[match_index] = matched
    source_attrs["yance_reply_evidence"] = evidence
    source.attributes = source_attrs

    sent_attrs = dict(sent.attributes or {})
    sent_attrs["yance_learning"] = {
        "source_message_id": source.id,
        "candidate_id": matched.get("candidate_id"),
        "outcome": "provider_accepted",
    }
    sent.attributes = sent_attrs
    db.commit()



def finalize_response_outcome(db: Session, inbound_message_id: int) -> bool:
    """Close ONE real reply-learning event only for its first later inbound.

    Uses existing ChatHistory and SessionToAgent, no second learning store.
    Deny echoed, stale, closed, cross-tenant and duplicate inbound events.
    An unanswered message remains merely provider_accepted; never infer a
    recipient reply, delivered receipt, or no-reply from elapsed wall time.
    """
    inbound = db.query(ChatHistory).filter(
        ChatHistory.id == inbound_message_id,
        ChatHistory.message_type == "user",
    ).first()
    if inbound is None:
        return False
    attrs = inbound.attributes or {}
    if any(attrs.get(k) for k in ("is_echo", "provider_echo", "outbound_echo")):
        return False
    session = db.query(SessionToAgent).filter(
        SessionToAgent.session_id == inbound.session_id,
        SessionToAgent.organization_id == inbound.organization_id,
        SessionToAgent.customer_id == inbound.customer_id,
        SessionToAgent.agent_id == inbound.agent_id,
    ).first()
    if session is None or session.status == SessionStatus.CLOSED:
        return False
    # Reject stale replay of an older inbound when newer canonical turns exist.
    latest_id = db.query(ChatHistory.id).filter(
        ChatHistory.session_id == inbound.session_id,
        ChatHistory.organization_id == inbound.organization_id,
        ChatHistory.customer_id == inbound.customer_id,
        ChatHistory.message_type == "user",
    ).order_by(ChatHistory.id.desc()).limit(1).scalar()
    if latest_id != inbound.id:
        return False
    # For concurrent event completion, lock the actual sent learning row.
    sent = db.query(ChatHistory).filter(
        ChatHistory.session_id == inbound.session_id,
        ChatHistory.organization_id == inbound.organization_id,
        ChatHistory.customer_id == inbound.customer_id,
        ChatHistory.agent_id == inbound.agent_id,
        ChatHistory.id < inbound.id,
        ChatHistory.message_type == "agent",
    ).order_by(ChatHistory.id.desc()).with_for_update().first()
    if sent is None:
        db.rollback()
        return False
    learning = (sent.attributes or {}).get("yance_learning")
    if not isinstance(learning, dict) or learning.get("response_message_id"):
        db.rollback()
        return False
    if learning.get("outcome") not in {"provider_accepted", "provider_accepted_edited"}:
        db.rollback()
        return False
    # This must be the FIRST customer response after the adopted send.
    intervening_user_rows = db.query(ChatHistory).filter(
        ChatHistory.session_id == inbound.session_id,
        ChatHistory.organization_id == inbound.organization_id,
        ChatHistory.customer_id == inbound.customer_id,
        ChatHistory.message_type == "user",
        ChatHistory.id > sent.id,
        ChatHistory.id <= inbound.id,
    ).order_by(ChatHistory.id.asc()).all()
    first_real_reply = next(
        (row for row in intervening_user_rows
         if not any((row.attributes or {}).get(key)
                    for key in ("is_echo", "provider_echo", "outbound_echo"))),
        None,
    )
    if first_real_reply is None or first_real_reply.id != inbound.id:
        db.rollback()
        return False
    source_id = learning.get("source_message_id")
    source = db.query(ChatHistory).filter(
        ChatHistory.id == source_id,
        ChatHistory.session_id == inbound.session_id,
        ChatHistory.organization_id == inbound.organization_id,
        ChatHistory.customer_id == inbound.customer_id,
        ChatHistory.message_type == "user",
        ChatHistory.id < sent.id,
    ).with_for_update().first() if isinstance(source_id, int) else None
    if source is None:
        db.rollback()
        return False
    source_attrs = dict(source.attributes or {})
    evidence = list(source_attrs.get("yance_reply_evidence") or [])
    matching = [
        index for index, item in enumerate(evidence)
        if isinstance(item, dict)
        and item.get("decision") == "adopt"
        and not item.get("do_not_learn")
        and item.get("sent_message_id") == sent.id
        and item.get("candidate_id") == learning.get("candidate_id")
    ]
    if len(matching) != 1:
        db.rollback()
        return False
    sent_attrs = dict(sent.attributes or {})
    sent_attrs["yance_learning"] = {
        **learning, "response_outcome": "response_received",
        "response_message_id": inbound.id,
    }
    sent.attributes = sent_attrs
    item = dict(evidence[matching[0]])
    item["response_outcome"] = "response_received"
    item["response_message_id"] = inbound.id
    evidence[matching[0]] = item
    source.attributes = {**source_attrs, "yance_reply_evidence": evidence}
    db.commit()
    return True

def scoped_rule(scope: str, rule: str, customer_id: str | None = None) -> str:
    clean_rule = " ".join((rule or "").split())
    if not clean_rule:
        raise ValueError("empty_rule")
    if scope not in ALLOWED_RULE_SCOPES:
        raise ValueError("unsupported_rule_scope")
    if scope == "global":
        return f"{YANCE_SCOPE_PREFIX}global]] {clean_rule}"
    if not customer_id:
        raise ValueError("contact_scope_requires_customer")
    return f"{YANCE_SCOPE_PREFIX}contact:{customer_id}]] {clean_rule}"


def promote_rule(
    db: Session,
    agent: Agent,
    *,
    scope: str,
    rule: str,
    customer_id: str | None,
) -> dict[str, Any]:
    marker = scoped_rule(scope, rule, customer_id)
    instructions = list(agent.instructions or [])
    if marker not in instructions:
        instructions.append(marker)
        AgentRepository(db).update_agent(agent.id, instructions=instructions)
    return {"promoted": True, "scope": scope, "rule": rule}


def persona_history(agent: Agent) -> list[dict[str, Any]]:
    history = []
    for version in list(getattr(agent, "versions", []) or [])[-50:]:
        raw_instructions = getattr(
            version,
            "_instructions",
            getattr(version, "instructions", None),
        )
        try:
            projected_instructions = json.loads(raw_instructions) if isinstance(raw_instructions, str) else raw_instructions
        except json.JSONDecodeError:
            projected_instructions = [raw_instructions] if raw_instructions else []
        history.append({
            "transaction_id": int(version.transaction_id),
            "instructions": projected_instructions or [],
        })
    return history


def rollback_persona(db: Session, agent: Agent, transaction_id: int) -> dict[str, Any]:
    AgentVersion = version_class(Agent)
    version = (
        db.query(AgentVersion)
        .filter(
            AgentVersion.id == agent.id,
            AgentVersion.transaction_id == transaction_id,
        )
        .first()
    )
    if version is None:
        raise ValueError("persona_version_not_found")
    version.revert()
    db.commit()
    db.refresh(agent)
    return {"rolled_back": True, "transaction_id": transaction_id, "instructions": agent.instructions}
