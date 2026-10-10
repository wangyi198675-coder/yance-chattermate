"""Evidence-governed relationship/memory/temporal projection.

This service deliberately composes existing ChatterMate owners:
- Customer / People is the person authority.
- ChatHistory is the conversation-evidence authority.
- Customer.meta_data carries bounded, explicitly confirmed relationship notes.
- Relationship metrics and actions are derived projections and are never written
  back as facts.

Graphiti/Neo4j may later accelerate derived recall after independent admission,
but this module neither imports nor requires a graph runtime.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from app.models.chat_history import ChatHistory
from app.models.customer import Customer
from app.models.organization import Organization
from app.models.session_to_agent import SessionToAgent
from app.models.schemas.people import project_person_profile
from app.models.schemas.relationship import (
    GoalProjection,
    RelationshipContextProjection,
    RelationshipDecision,
    RelationshipEvidence,
    RelationshipMemoryEntry,
    RelationshipMemoryUpsertRequest,
    RelationshipMetrics,
    RelationshipTemporalSettingsRequest,
    TemporalProjection,
)
from app.repositories.people import PeopleRepository


RELATIONSHIP_MEMORY_KEY = "relationship_memory"
RELATIONSHIP_MEMORY_VERSION = 1
MAX_RELATIONSHIP_MEMORY_ENTRIES = 200


class RelationshipContextError(ValueError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _zone(name: Optional[str], fallback: str = "UTC") -> tuple[ZoneInfo, str]:
    candidate = name or fallback
    try:
        return ZoneInfo(candidate), candidate
    except ZoneInfoNotFoundError:
        try:
            return ZoneInfo(fallback), fallback
        except ZoneInfoNotFoundError:
            return ZoneInfo("UTC"), "UTC"


def _daypart(hour: int) -> str:
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 18:
        return "afternoon"
    if 18 <= hour < 23:
        return "evening"
    return "night"


def _minutes(value: str) -> int:
    hour, minute = (int(part) for part in value.split(":"))
    return hour * 60 + minute


def _inside_window(current: int, start: int, end: int) -> bool:
    if start == end:
        return True
    if start < end:
        return start <= current < end
    return current >= start or current < end


def _next_window_start(local_now: datetime, hhmm: str) -> datetime:
    hour, minute = (int(part) for part in hhmm.split(":"))
    candidate = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= local_now:
        candidate += timedelta(days=1)
    return candidate


def _container(customer: Customer) -> dict:
    meta = customer.meta_data if isinstance(customer.meta_data, dict) else {}
    raw = meta.get(RELATIONSHIP_MEMORY_KEY)
    if not isinstance(raw, dict):
        raw = {}
    entries = raw.get("entries")
    temporal = raw.get("temporal")
    return {
        "version": RELATIONSHIP_MEMORY_VERSION,
        "entries": list(entries) if isinstance(entries, list) else [],
        "temporal": dict(temporal) if isinstance(temporal, dict) else {},
        "goals": dict(raw.get("goals")) if isinstance(raw.get("goals"), dict) else {},
    }


def _save_container(db: Session, customer: Customer, payload: dict) -> None:
    meta = deepcopy(customer.meta_data) if isinstance(customer.meta_data, dict) else {}
    meta[RELATIONSHIP_MEMORY_KEY] = payload
    customer.meta_data = meta
    db.add(customer)
    db.commit()
    db.refresh(customer)


def _profile_fact_entries(customer: Customer, now: datetime) -> list[RelationshipMemoryEntry]:
    profile = project_person_profile(customer.meta_data)
    if not profile:
        return []
    rows: list[tuple[str, object]] = []
    for field in ("birth_date", "birth_year", "country", "region", "city", "raw_location", "occupation"):
        value = getattr(profile, field, None)
        if value is not None:
            rows.append((field, value))
    if profile.age is not None:
        rows.append(("age", profile.age))

    result: list[RelationshipMemoryEntry] = []
    for field, value in rows:
        source_ref = (
            "person_profile:age_observation"
            if field == "age" and profile.age_precision == "observed"
            else f"person_profile:{field}"
        )
        result.append(RelationshipMemoryEntry(
            id=f"profile-{field}",
            kind="fact",
            text=f"{field}: {value}",
            confirmed=True,
            active=True,
            created_at=_aware(customer.updated_at) or _aware(customer.created_at) or now,
            updated_at=_aware(customer.updated_at) or now,
            evidence=[RelationshipEvidence(
                source_type="person_profile",
                source_ref=source_ref,
                label=str(value),
            )],
        ))
    return result


def _captured_fact_entries(db: Session, customer: Customer, now: datetime) -> list[RelationshipMemoryEntry]:
    detail = PeopleRepository(db).get_detail(customer.organization_id, customer.id) or {}
    attrs = detail.get("captured_attributes") or {}
    result: list[RelationshipMemoryEntry] = []
    for key, value in sorted(attrs.items()):
        if value in (None, "", [], {}):
            continue
        result.append(RelationshipMemoryEntry(
            id=f"captured-{key}",
            kind="fact",
            text=f"{key}: {value}",
            confirmed=True,
            active=True,
            created_at=_aware(customer.created_at) or now,
            updated_at=_aware(customer.updated_at) or now,
            evidence=[RelationshipEvidence(
                source_type="captured_attribute",
                source_ref=f"captured_attribute:{key}",
                label=str(value),
            )],
        ))
    return result


def _stored_entries(customer: Customer) -> list[RelationshipMemoryEntry]:
    result: list[RelationshipMemoryEntry] = []
    for raw in _container(customer)["entries"]:
        if not isinstance(raw, dict):
            continue
        try:
            result.append(RelationshipMemoryEntry.model_validate(raw))
        except Exception:
            # Invalid JSON must never become relationship truth.
            continue
    return result


def _validate_source_refs(
    db: Session,
    customer: Customer,
    source_refs: Iterable[str],
) -> list[RelationshipEvidence]:
    detail = PeopleRepository(db).get_detail(customer.organization_id, customer.id) or {}
    attrs = detail.get("captured_attributes") or {}
    profile_raw = (
        customer.meta_data.get("person_profile", {})
        if isinstance(customer.meta_data, dict)
        else {}
    )
    evidence: list[RelationshipEvidence] = []
    seen: set[str] = set()
    for raw_ref in source_refs:
        ref = raw_ref.strip()
        if not ref or ref in seen:
            continue
        seen.add(ref)
        if ref.startswith("chat_history:"):
            raw_id = ref.split(":", 1)[1]
            if not raw_id.isdigit():
                raise RelationshipContextError(f"invalid source reference: {ref}")
            row = (
                db.query(ChatHistory)
                .filter(
                    ChatHistory.id == int(raw_id),
                    ChatHistory.organization_id == customer.organization_id,
                    ChatHistory.customer_id == customer.id,
                )
                .first()
            )
            if row is None:
                raise RelationshipContextError(f"source does not belong to this person: {ref}")
            evidence.append(RelationshipEvidence(
                source_type="chat_history",
                source_ref=ref,
                observed_at=_aware(row.created_at),
                label=row.message_type,
                session_id=str(row.session_id) if row.session_id else None,
            ))
            continue
        if ref.startswith("person_profile:"):
            key = ref.split(":", 1)[1]
            if not isinstance(profile_raw, dict) or key not in profile_raw:
                raise RelationshipContextError(f"unknown profile source: {ref}")
            evidence.append(RelationshipEvidence(
                source_type="person_profile",
                source_ref=ref,
                label=key,
            ))
            continue
        if ref.startswith("captured_attribute:"):
            key = ref.split(":", 1)[1]
            if key not in attrs:
                raise RelationshipContextError(f"unknown captured source: {ref}")
            evidence.append(RelationshipEvidence(
                source_type="captured_attribute",
                source_ref=ref,
                label=key,
            ))
            continue
        raise RelationshipContextError(f"unsupported source reference: {ref}")
    return evidence


def upsert_confirmed_memory(
    db: Session,
    customer: Customer,
    request: RelationshipMemoryUpsertRequest,
    *,
    operator_ref: str,
    now: Optional[datetime] = None,
) -> RelationshipMemoryEntry:
    now = _aware(now) or _utc_now()
    payload = _container(customer)
    entries = _stored_entries(customer)
    existing = next((entry for entry in entries if entry.id == request.id), None) if request.id else None
    evidence = _validate_source_refs(db, customer, request.source_refs)
    evidence.append(RelationshipEvidence(
        source_type="operator_confirmation",
        source_ref=operator_ref,
        observed_at=now,
        label="explicit confirmation",
    ))
    entry = RelationshipMemoryEntry(
        id=existing.id if existing else str(uuid4()),
        kind=request.kind,
        text=request.text,
        confirmed=True,
        active=request.active,
        effect=request.effect,
        occurred_at=request.occurred_at,
        created_at=existing.created_at if existing else now,
        updated_at=now,
        evidence=evidence,
    )
    remaining = [item for item in entries if item.id != entry.id]
    remaining.append(entry)
    if len(remaining) > MAX_RELATIONSHIP_MEMORY_ENTRIES:
        raise RelationshipContextError(
            f"relationship memory is capped at {MAX_RELATIONSHIP_MEMORY_ENTRIES} confirmed entries"
        )
    payload["entries"] = [item.model_dump(mode="json") for item in remaining]
    _save_container(db, customer, payload)
    return entry


def set_temporal_settings(
    db: Session,
    customer: Customer,
    request: RelationshipTemporalSettingsRequest,
) -> dict:
    if request.contact_timezone:
        try:
            ZoneInfo(request.contact_timezone)
        except ZoneInfoNotFoundError as exc:
            raise RelationshipContextError("contact_timezone must be a valid IANA timezone") from exc
    payload = _container(customer)
    payload["temporal"] = {
        "contact_timezone": request.contact_timezone,
        "preferred_contact_start": request.preferred_contact_start,
        "preferred_contact_end": request.preferred_contact_end,
    }
    _save_container(db, customer, payload)
    return payload["temporal"]


def goal_projection(customer: Customer, *, current: Optional[str] = None) -> GoalProjection:
    """Projection from the admitted Customer.meta_data relationship owner."""
    refs = ["goal_input:current"] if (current or "").strip() else []
    raw = _container(customer).get("goals") or {}
    long_term = None
    if raw.get("confirmed") is True and raw.get("active") is True and isinstance(raw.get("long_term"), str):
        long_term = raw["long_term"].strip() or None
        if long_term:
            refs.append("relationship_memory:goal:long_term")
    return GoalProjection(current=(current or "").strip() or None,
                          long_term=long_term, source_refs=refs)


def set_long_term_goal(db: Session, customer: Customer, goal: Optional[str], *,
                       operator_ref: str, now: Optional[datetime] = None) -> GoalProjection:
    """Explicit confirmed Goal carried by the EXISTING bounded Relationship JSON."""
    now = _aware(now) or _utc_now()
    clean = (goal or "").strip()
    if len(clean) > 1000:
        raise RelationshipContextError("long_term_goal_too_long")
    payload = _container(customer)
    payload["goals"] = {
        "long_term": clean or None, "confirmed": True, "active": bool(clean),
        "operator_ref": operator_ref, "updated_at": now.isoformat(),
    }
    _save_container(db, customer, payload)
    return goal_projection(customer)


def _temporal_projection(
    customer: Customer,
    organization: Organization,
    *,
    now: datetime,
) -> TemporalProjection:
    settings = _container(customer)["temporal"]
    operator_zone, operator_name = _zone(getattr(organization, "timezone", None), "UTC")
    contact_name = settings.get("contact_timezone")
    if contact_name:
        contact_zone, contact_name = _zone(contact_name, operator_name)
        precision = "contact"
        known = True
        effective_name = contact_name
        effective_zone = contact_zone
    else:
        precision = "operator_fallback"
        known = False
        effective_name = operator_name
        effective_zone = operator_zone

    local_now = now.astimezone(effective_zone)
    start = settings.get("preferred_contact_start")
    end = settings.get("preferred_contact_end")
    defer = False
    defer_until = None
    defer_reason = None
    # Never enforce a fabricated contact-local schedule.
    if known and start and end:
        current = local_now.hour * 60 + local_now.minute
        if not _inside_window(current, _minutes(start), _minutes(end)):
            defer = True
            defer_until = _next_window_start(local_now, start).astimezone(timezone.utc)
            defer_reason = "outside_confirmed_contact_window"

    return TemporalProjection(
        operator_timezone=operator_name,
        contact_timezone=contact_name if known else None,
        contact_timezone_known=known,
        effective_timezone=effective_name,
        precision=precision,
        local_time=local_now,
        daypart=_daypart(local_now.hour),
        preferred_contact_start=start,
        preferred_contact_end=end,
        defer_recommended=defer,
        defer_until=defer_until,
        defer_reason=defer_reason,
    )


def _metrics(
    messages: list[ChatHistory],
    sessions: list[SessionToAgent],
    entries: list[RelationshipMemoryEntry],
    now: datetime,
) -> RelationshipMetrics:
    timestamps = [_aware(row.created_at) for row in messages if row.created_at]
    timestamps = [stamp for stamp in timestamps if stamp is not None]
    active_days = len({stamp.date() for stamp in timestamps})
    last_interaction = max(timestamps) if timestamps else None
    inbound = [_aware(row.created_at) for row in messages if row.message_type == "user" and row.created_at]
    outbound = [
        _aware(row.created_at)
        for row in messages
        if row.message_type in {"agent", "bot"} and row.created_at
    ]
    last_inbound = max(inbound) if inbound else None
    last_outbound = max(outbound) if outbound else None

    if not messages:
        stage = "unknown"
    elif len(messages) >= 20 and active_days >= 7:
        stage = "established"
    elif len(messages) >= 6 or len(sessions) >= 2 or active_days >= 2:
        stage = "developing"
    else:
        stage = "new"

    if last_interaction is None:
        momentum = "unknown"
    else:
        age = now - last_interaction
        recent = sum(1 for stamp in timestamps if now - stamp <= timedelta(days=7))
        if age <= timedelta(days=2):
            momentum = "rising" if recent >= 4 else "steady"
        elif age <= timedelta(days=7):
            momentum = "steady"
        elif age <= timedelta(days=30):
            momentum = "quiet"
        else:
            momentum = "cooling"

    scores = [
        float(row.sentiment_score)
        for row in messages
        if row.sentiment_score is not None
    ]
    if not scores:
        temperature = "unknown"
    else:
        average = sum(scores) / len(scores)
        temperature = "warm" if average > 0.2 else "cool" if average < -0.2 else "neutral"

    active_boundaries = [
        entry for entry in entries
        if entry.active and entry.kind in {"boundary", "sensitive_topic"}
    ]
    if any(entry.effect == "no_reply" for entry in active_boundaries):
        risk = "elevated"
    elif active_boundaries:
        risk = "watch"
    elif scores:
        risk = "elevated" if min(scores) < -0.7 else "low"
    elif messages:
        risk = "low"
    else:
        risk = "unknown"

    basis = [
        f"chat_history_messages:{len(messages)}",
        f"sessions:{len(sessions)}",
        f"active_days:{active_days}",
    ]
    if scores:
        basis.append(f"sentiment_rows:{len(scores)}")
    if active_boundaries:
        basis.append(f"confirmed_boundary_rows:{len(active_boundaries)}")
    return RelationshipMetrics(
        stage=stage,
        momentum=momentum,
        temperature=temperature,
        risk=risk,
        message_count=len(messages),
        session_count=len(sessions),
        active_days=active_days,
        last_interaction_at=last_interaction,
        last_inbound_at=last_inbound,
        last_outbound_at=last_outbound,
        basis=basis,
    )


def _decision(
    metrics: RelationshipMetrics,
    temporal: TemporalProjection,
    entries: list[RelationshipMemoryEntry],
    goals: GoalProjection,
) -> RelationshipDecision:
    active = [entry for entry in entries if entry.active]
    blocking = [
        entry for entry in active
        if entry.kind in {"boundary", "sensitive_topic"} and entry.effect == "no_reply"
    ]
    if blocking:
        return RelationshipDecision(
            action="no_reply",
            next_best_action="Respect the confirmed boundary; do not send now.",
            why_now=[f"confirmed_boundary:{entry.id}" for entry in blocking[:3]],
        )
    deferred = [
        entry for entry in active
        if entry.kind in {"boundary", "sensitive_topic"} and entry.effect == "defer"
    ]
    if deferred:
        return RelationshipDecision(
            action="defer",
            next_best_action="Defer until the confirmed interaction condition is satisfied.",
            why_now=[f"confirmed_defer_condition:{entry.id}" for entry in deferred[:3]],
        )
    if temporal.defer_recommended:
        return RelationshipDecision(
            action="defer",
            next_best_action="Wait for the confirmed contact-time window.",
            why_now=[temporal.defer_reason or "confirmed_contact_window"],
            defer_until=temporal.defer_until,
        )
    if (
        metrics.last_inbound_at
        and (
            metrics.last_outbound_at is None
            or metrics.last_inbound_at > metrics.last_outbound_at
        )
    ):
        return RelationshipDecision(
            action="reply",
            next_best_action="Reply to the latest inbound message.",
            why_now=["latest_canonical_message_is_inbound"],
        )
    open_items = [
        entry for entry in active
        if entry.kind in {"open_loop", "promise"}
    ]
    if open_items:
        return RelationshipDecision(
            action="next_action",
            next_best_action=f"Continue: {open_items[0].text}",
            why_now=[f"confirmed_{open_items[0].kind}:{open_items[0].id}"],
        )
    if goals.current:
        return RelationshipDecision(
            action="next_action",
            next_best_action=f"Advance the current goal: {goals.current}",
            why_now=["current_goal_input"],
        )
    if goals.long_term:
        return RelationshipDecision(
            action="next_action",
            next_best_action=f"Keep continuity with the long-term goal: {goals.long_term}",
            why_now=["long_term_goal_input"],
        )
    return RelationshipDecision(
        action="no_reply",
        next_best_action="No evidence-based action is currently required.",
        why_now=["no_unresolved_canonical_signal"],
    )


def build_relationship_context(
    db: Session,
    customer: Customer,
    organization: Organization,
    *,
    goals: Optional[GoalProjection] = None,
    now: Optional[datetime] = None,
) -> RelationshipContextProjection:
    now = _aware(now) or _utc_now()
    goals = goals if goals is not None else goal_projection(customer)
    messages = (
        db.query(ChatHistory)
        .filter(
            ChatHistory.organization_id == customer.organization_id,
            ChatHistory.customer_id == customer.id,
        )
        .order_by(ChatHistory.created_at.asc(), ChatHistory.id.asc())
        .all()
    )
    sessions = (
        db.query(SessionToAgent)
        .filter(
            SessionToAgent.organization_id == customer.organization_id,
            SessionToAgent.customer_id == customer.id,
        )
        .order_by(SessionToAgent.assigned_at.asc())
        .all()
    )
    stored = _stored_entries(customer)
    active = [entry for entry in stored if entry.confirmed and entry.active]
    facts = _profile_fact_entries(customer, now) + _captured_fact_entries(db, customer, now)
    facts.extend(entry for entry in active if entry.kind == "fact")

    buckets = {
        "notes": [entry for entry in active if entry.kind == "note"],
        "dated_events": [entry for entry in active if entry.kind == "event"],
        "interests": [entry for entry in active if entry.kind == "interest"],
        "shared_moments": [entry for entry in active if entry.kind == "shared_moment"],
        "open_loops": [entry for entry in active if entry.kind == "open_loop"],
        "promises": [entry for entry in active if entry.kind == "promise"],
        "boundaries": [entry for entry in active if entry.kind == "boundary"],
        "sensitive_topics": [entry for entry in active if entry.kind == "sensitive_topic"],
    }
    temporal = _temporal_projection(customer, organization, now=now)
    metrics = _metrics(messages, sessions, stored, now)
    decision = _decision(metrics, temporal, stored, goals)

    evidence: list[RelationshipEvidence] = []
    seen: set[str] = set()
    for entry in facts + active:
        for item in entry.evidence:
            key = f"{item.source_type}:{item.source_ref}"
            if key not in seen:
                seen.add(key)
                evidence.append(item)

    # Conversation history remains canonical evidence. Add compact receipts so
    # Relationship World can drill into a source without copying message text.
    for row in messages[-20:]:
        item = RelationshipEvidence(
            source_type="chat_history",
            source_ref=f"chat_history:{row.id}",
            observed_at=_aware(row.created_at),
            label=row.message_type,
            session_id=str(row.session_id) if row.session_id else None,
        )
        key = f"{item.source_type}:{item.source_ref}"
        if key not in seen:
            seen.add(key)
            evidence.append(item)

    journey = [
        {
            "kind": "conversation",
            "session_id": str(session.session_id),
            "channel": session.channel,
            "status": session.status.value if session.status else None,
            "at": _aware(session.assigned_at).isoformat() if session.assigned_at else None,
        }
        for session in sessions
    ]
    journey.extend({
        "kind": "shared_moment",
        "memory_id": entry.id,
        "label": entry.text,
        "at": (entry.occurred_at or entry.created_at).isoformat(),
    } for entry in buckets["shared_moments"])
    journey.sort(key=lambda item: item.get("at") or "")

    return RelationshipContextProjection(
        customer_id=str(customer.id),
        generated_at=now,
        confirmed_facts=facts,
        relationship=metrics,
        temporal=temporal,
        goals=goals,
        decision=decision,
        evidence_review=evidence,
        journey=journey,
        **buckets,
    )
