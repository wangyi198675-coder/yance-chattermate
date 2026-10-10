"""Bounded AI_AUTO commitment-time check; no new delivery or persistence owner.

The PostgreSQL FOR UPDATE locks on SessionToAgent and Agent stay held across
the physical send. Inbound ChatHistory FK inserts also require a KEY SHARE
lock on the session row, so they cannot overtake this emission transaction.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.chat_history import ChatHistory
from app.models.session_to_agent import SessionStatus, SessionToAgent


def context_revision(db: Session, session: SessionToAgent, *,
                     ignore_bot_message_id: int | None = None) -> str:
    query = db.query(ChatHistory).filter(ChatHistory.session_id == session.session_id)
    if ignore_bot_message_id is not None:
        query = query.filter(ChatHistory.id != ignore_bot_message_id)
    latest = query.order_by(ChatHistory.id.desc()).first()
    updated = getattr(session, "updated_at", None)
    token = updated.isoformat() if updated is not None else ""
    from app.models.customer import Customer
    import hashlib
    import json
    customer = db.query(Customer).filter(
        Customer.id == session.customer_id,
        Customer.organization_id == session.organization_id,
    ).first()
    agent = db.query(Agent).filter(
        Agent.id == session.agent_id,
        Agent.organization_id == session.organization_id,
    ).first() if session.agent_id else None
    owner = {
        "customer_meta": customer.meta_data if customer else None,
        "agent_instructions": agent.instructions if agent else None,
        "persona_override": getattr(session, "persona_override", None),
        "current_turn": read_turn_controls(db, session),
    }
    digest = hashlib.sha256(json.dumps(
        owner, sort_keys=True, default=str, ensure_ascii=False,
    ).encode("utf-8")).hexdigest()[:20]
    return f"{latest.id if latest else 0}:{latest.message_type if latest else 'empty'}:{token}:{digest}"


def reconcile_workflow_own_revision(db: Session, session: SessionToAgent,
                                    revision_before_workflow: str) -> str:
    """Allow only workflow progression timestamp, not a different chat turn.

    WorkflowExecutionService.update_workflow_state updates session.updated_at.
    The ID/type part of the original full generation revision must stay exact.
    Final commitment independently revalidates OPEN, takeover, agent permission,
    the last inbound and the resulting full revision.
    """
    if not revision_before_workflow:
        return revision_before_workflow
    db.refresh(session)
    current = context_revision(db, session)
    old_parts = revision_before_workflow.split(":", 2)
    current_parts = current.split(":", 2)
    if len(old_parts) != 3 or old_parts[:2] != current_parts[:2]:
        return revision_before_workflow  # fail closed on an intervening row
    return current


def build_auto_send_authority(db: Session, session: SessionToAgent, *,
                              organization_id, agent_id, source_message_id,
                              bot_message_id: int | None = None,
                              context_revision_at_generation: str | None = None,
                              sensitive_action: bool = False,
                              sensitive_authorized: bool = False,
                              reply_state: str | None = None,
                              confirmed_boundary_denies_send: bool = False) -> dict:
    """One canonical snapshot format for ChatAgent and workflow emission."""
    return {
        "organization_id": str(organization_id),
        "agent_id": str(agent_id),
        "session_id": str(session.session_id),
        "source_message_id": source_message_id,
        "context_revision": (context_revision_at_generation or context_revision(
            db, session, ignore_bot_message_id=bot_message_id)),
        "bot_message_id": bot_message_id,
        "mode": "AI_AUTO",
        "send_allowed": True,
        "sensitive_action": sensitive_action,
        "sensitive_authorized": sensitive_authorized,
        "reply_state": reply_state,
        "confirmed_boundary_denies_send": confirmed_boundary_denies_send,
    }


def revalidate_auto_send(db: Session, authority: dict, payload: dict, *,
                         terminal_control: bool = False,
                         allow_owned_sending: bool = False) -> str | None:
    """Lock canonical authority at the final reversible point.

    Return a fail-closed reason or None; caller holds this transaction through
    the emit/send. Never consult stale ORM identity-map objects.
    """
    if not isinstance(authority, dict):
        return "auto_send_snapshot_missing"
    required = ("organization_id", "agent_id", "session_id",
                "source_message_id", "context_revision", "bot_message_id")
    if any(not authority.get(k) for k in required):
        return "auto_send_snapshot_incomplete"
    try:
        from uuid import UUID
        org_id, agent_id, session_id = (UUID(str(authority[k])) for k in
                                        ("organization_id", "agent_id", "session_id"))
        source_id = int(authority["source_message_id"])
        bot_id = int(authority["bot_message_id"])
    except (TypeError, ValueError, KeyError):
        return "auto_send_snapshot_invalid"
    if payload.get("message_id") != bot_id:
        return "auto_send_bot_mismatch"
    session = (db.query(SessionToAgent)
               .filter(SessionToAgent.session_id == session_id)
               .with_for_update().first())
    if session is None or session.organization_id != org_id or session.agent_id != agent_id:
        return "auto_send_session_scope_changed"
    if session.status != SessionStatus.OPEN:
        return "auto_send_session_not_open"
    if session.user_id is not None:
        return "auto_send_human_takeover"
    # Agent.groups is an eager *nullable* outer join: locking the full ORM
    # Agent with FOR UPDATE fails in real PostgreSQL 16.15. Lock only the
    # canonical Agent row and permission columns in the same transaction.
    permission = (db.query(Agent.id, Agent.ai_replies_enabled)
                  .filter(Agent.id == agent_id,
                          Agent.organization_id == org_id)
                  .with_for_update().first())
    if permission is None or permission.ai_replies_enabled is not True:
        return "auto_send_permission_revoked"
    # The W173 AI_AUTO authority is precisely unclaimed OPEN session plus
    # Agent.ai_replies_enabled. A separate mode or sensitive policy is NOT made up.
    if authority.get("mode") != "AI_AUTO" or authority.get("send_allowed") is not True:
        return "auto_send_mode_or_boundary_denied"
    if authority.get("sensitive_action") and authority.get("sensitive_authorized") is not True:
        return "auto_send_sensitive_permission_missing"
    if (authority.get("reply_state") in {"no_reply", "defer"}
            or payload.get("reply_state") in {"no_reply", "defer"}
            or authority.get("confirmed_boundary_denies_send") is True):
        return "auto_send_no_reply_or_boundary"
    last_inbound = (db.query(ChatHistory.id)
                    .filter(ChatHistory.session_id == session_id,
                            ChatHistory.message_type == "user")
                    .order_by(ChatHistory.id.desc()).limit(1).scalar())
    if last_inbound != source_id:
        return "auto_send_latest_inbound_changed"
    if context_revision(db, session, ignore_bot_message_id=bot_id) != authority["context_revision"]:
        return "auto_send_context_revision_changed"
    # Same bot row is the one and only outbound commitment for this turn.
    bot = db.query(ChatHistory).filter(
        ChatHistory.id == bot_id, ChatHistory.session_id == session_id,
        ChatHistory.organization_id == org_id, ChatHistory.agent_id == agent_id,
        ChatHistory.message_type == "bot").first()
    if bot is None:
        return "auto_send_bot_intent_missing"
    if bot.message != payload.get("message"):
        return "auto_send_bot_payload_mismatch"
    state = (bot.attributes or {}).get("provider_delivery", {}).get("state")
    # Web sending is replayable under the SAME canonical identity; external
    # provider ambiguity remains fail-closed.
    web_replay = (
        state == "sending"
        and (bot.attributes or {}).get("provider_delivery", {}).get("channel") == "web"
        and payload.get("_ai_auto_authority") is not None
    )
    # After a successful canonical Web ACK, a terminal workflow control may
    # commit its own existing SessionToAgent transition. This exemption cannot
    # be used by the message sender (terminal_control defaults to False).
    terminal_after_ack = (
        terminal_control and state == "succeeded"
        and (bot.attributes or {}).get("provider_delivery", {}).get("channel") == "web"
        and isinstance((bot.attributes or {}).get("workflow_terminal_control"), dict)
        and (bot.attributes or {})["workflow_terminal_control"].get("state") == "pending"
    )
    if state in {"sending", "succeeded", "ambiguous", "failed"} and not (
            (state == "sending" and allow_owned_sending) or web_replay or terminal_after_ack):
        return "auto_send_already_committed"
    if (bot.attributes or {}).get("delivery_status"):
        return "auto_send_intent_failed"
    return None

from uuid import UUID
from typing import Any

TURN_KEY = "yance_current_turn_controls"


class TurnAuthorityConflict(ValueError):
    """Current inbound or optimistic revision changed before the update."""


def _read_state(source: ChatHistory) -> dict[str, Any]:
    raw = (source.attributes or {}).get(TURN_KEY)
    if not isinstance(raw, dict) or raw.get("source_message_id") != source.id:
        raw = {}
    return {
        "source_message_id": source.id,
        "version": max(0, int(raw.get("version", 0))) if isinstance(raw.get("version", 0), int) else 0,
        "current_goal": str(raw["current_goal"]) if isinstance(raw.get("current_goal"), str) else None,
        "allow_sensitive_context": raw.get("allow_sensitive_context") is True,
    }


def read_turn_controls(db: Session, session: SessionToAgent) -> dict[str, Any] | None:
    """Project the latest inbound's version. Absent grant is ALWAYS false."""
    source = db.query(ChatHistory).filter(
        ChatHistory.session_id == session.session_id,
        ChatHistory.organization_id == session.organization_id,
        ChatHistory.customer_id == session.customer_id,
        ChatHistory.message_type == "user",
    ).order_by(ChatHistory.id.desc()).first()
    return _read_state(source) if source else None


def write_turn_controls(
    db: Session,
    session_id: UUID | str,
    *,
    source_message_id: int,
    expected_version: int,
    current_goal: str | None,
    allow_sensitive_context: bool,
) -> dict[str, Any]:
    """Atomic compare-and-swap anchored to the EXACT last inbound turn.

    Lock ordering is SessionToAgent then inbound ChatHistory. A source on a
    different session/organization cannot be amended. A new outbound, inbound,
    transfer or close makes this operator edit stale rather than silently
    retargeting it to another person's conversation.
    """
    if expected_version < 0:
        raise TurnAuthorityConflict("invalid_turn_revision")
    goal = (current_goal or "").strip() or None
    if goal and len(goal) > 600:
        raise TurnAuthorityConflict("current_turn_goal_too_long")
    sid = UUID(str(session_id))
    try:
        session = db.query(SessionToAgent).filter(
            SessionToAgent.session_id == sid,
        ).with_for_update().first()
        if session is None:
            raise TurnAuthorityConflict("session_missing")
        # Human-held conversations remain eligible for Reply Brain controls.
        # CLOSED conversations never accept new current-turn edits.
        if session.status == SessionStatus.CLOSED:
            raise TurnAuthorityConflict("session_closed")
        latest = db.query(ChatHistory).filter(
            ChatHistory.session_id == sid,
            ChatHistory.organization_id == session.organization_id,
            ChatHistory.customer_id == session.customer_id,
        ).order_by(ChatHistory.id.desc()).first()
        if latest is None:
            raise TurnAuthorityConflict("current_turn_changed")
        # A not-yet-accepted AI_AUTO candidate must never prevent revocation.
        # Its canonical ChatHistory row exists before external emission, but
        # the operator is still editing the same *inbound* current turn.
        attrs = latest.attributes or {}
        is_unaccepted_auto = (
            latest.message_type == "bot"
            and attrs.get("client_send_action_kind") == "ai_auto"
            and isinstance(attrs.get("yance_auto_authority"), dict)
            and attrs["yance_auto_authority"].get("source_message_id") == source_message_id
            and (attrs.get("provider_delivery") or {}).get("state") != "succeeded"
        )
        if not (
            (latest.id == source_message_id and latest.message_type == "user")
            or is_unaccepted_auto
        ):
            raise TurnAuthorityConflict("current_turn_changed")
        source = db.query(ChatHistory).filter(
            ChatHistory.id == source_message_id,
        ).with_for_update().first()
        state = _read_state(source)
        if state["version"] != expected_version:
            raise TurnAuthorityConflict("current_turn_revision_conflict")
        updated = {
            **state,
            "version": expected_version + 1,
            "current_goal": goal,
            "allow_sensitive_context": allow_sensitive_context is True,
        }
        source.attributes = {**(source.attributes or {}), TURN_KEY: updated}
        db.add(source)
        db.commit()
        return updated
    except Exception:
        db.rollback()
        raise
