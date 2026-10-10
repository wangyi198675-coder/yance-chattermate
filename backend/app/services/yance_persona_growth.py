"""Window176 Persona Seed / Style Corpus / Growth thin orchestration.

Canonical owners stay unchanged:
- Agent.instructions: current base Persona truth
- SQLAlchemy-Continuum: Persona/instruction history
- Knowledge + Agno/PgVector: seed/style/guideline corpus
- rule-engine: deterministic condition matching for reviewed guidelines
- Customer / SessionToAgent: contact/conversation selection context

This module owns no Persona DB, vector DB, LLM runtime, scheduler, delivery path,
or learning store. Ordinary Knowledge is inert for Persona unless explicitly
marked with yance_style_learning metadata by an authorized user.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable
from uuid import UUID

import rule_engine
from agno.agent import Agent as AgnoAgent
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy_continuum import version_class

from app.core.security import decrypt_api_key
from app.knowledge.page_editor import (
    create_text_source,
    insert_subpage,
)
from app.models.agent import Agent
from app.models.customer import Customer
from app.models.knowledge import Knowledge
from app.models.knowledge_to_agent import KnowledgeToAgent
from app.models.session_to_agent import SessionToAgent
from app.repositories.agent import AgentRepository
from app.repositories.ai_config import AIConfigRepository
from app.repositories.knowledge import KnowledgeRepository
from app.repositories.knowledge_to_agent import KnowledgeToAgentRepository
from app.utils.agno_utils import create_model


PERSONA_META_NAMESPACE = "yance_persona_overrides"
STYLE_FEATURES = frozenset(
    {
        "length",
        "question_density",
        "directness",
        "emoji_placement",
        "teasing_threshold",
        "register",
        "language_switching",
        "bubble_rhythm",
        "boundary_patterns",
    }
)
CHARACTER_CARD_V2 = "chara_card_v2"
CHARACTER_CARD_V3 = "chara_card_v3"
MATCH_ALWAYS = "MATCH_ALWAYS"

# Optional W173 public seam. C3 does not contain Window173 yet; once merged, its
# scoped durable learning rules are consumed rather than reimplemented here.
try:
    from app.core.yance_learning_scope import effective_agent_instructions as _learning_scope
except ImportError:  # pragma: no cover - exercised only before W173 integration
    def _learning_scope(instructions: Iterable[str] | None, customer_id: str | None) -> list[str]:
        return [str(item) for item in instructions or [] if str(item).strip()]


@dataclass(frozen=True)
class PersonaContext:
    agent_id: str
    customer_id: str | None = None
    session_id: str | None = None
    channel: str | None = None
    language: str | None = None
    relationship_stage: str | None = None

    def as_rule_data(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "customer_id": self.customer_id or "",
            "session_id": self.session_id or "",
            "channel": self.channel or "",
            "language": self.language or "",
            "relationship_stage": self.relationship_stage or "",
        }


def _clean_text(value: Any, max_length: int = 4000) -> str:
    return " ".join(str(value or "").split())[:max_length].strip()


def _string_list(value: Any, *, max_items: int = 100, max_length: int = 1600) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        rows = [value]
    elif isinstance(value, list):
        rows = value
    else:
        return []
    result: list[str] = []
    for row in rows[:max_items]:
        clean = _clean_text(row, max_length)
        if clean:
            result.append(clean)
    return result


def _provenance(provenance: str, consent: bool) -> dict[str, Any]:
    source = _clean_text(provenance, 1200)
    if not source:
        raise ValueError("provenance_required")
    if consent is not True:
        raise ValueError("explicit_style_or_seed_consent_required")
    return {"provenance": source, "consent": True}


def normalize_character_card(
    payload: dict[str, Any],
    *,
    provenance: str,
    consent: bool,
) -> dict[str, Any]:
    """Map stable Character Card semantics into explicit Persona sections.

    V2 is the default admitted format. V3 is accepted conservatively as a
    compatible superset: only V2-stable fields are imported, and experimental
    V3-only fields remain in source payload provenance rather than becoming
    behavior automatically.
    """
    if not isinstance(payload, dict):
        raise ValueError("character_card_object_required")
    prov = _provenance(provenance, consent)
    spec = _clean_text(payload.get("spec"), 80).lower()
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload

    if spec == CHARACTER_CARD_V2:
        format_name = "character-card-v2"
        compatibility = "stable-v2"
    elif spec == CHARACTER_CARD_V3:
        format_name = "character-card-v3"
        compatibility = "v3-conservative-v2-field-map"
    else:
        raise ValueError("unsupported_character_card_format")

    name = _clean_text(data.get("name"), 240)
    if not name:
        raise ValueError("character_card_name_required")

    identity_facts = {
        "name": name,
        "description": _clean_text(data.get("description"), 4000),
    }
    style_traits = {
        "personality": _clean_text(data.get("personality"), 3000),
        "system_prompt": _clean_text(data.get("system_prompt"), 4000),
        "post_history_instructions": _clean_text(
            data.get("post_history_instructions"), 4000
        ),
    }
    relationship_rules = {
        "scenario": _clean_text(data.get("scenario"), 3000),
    }
    examples = _string_list(
        data.get("mes_example") or data.get("message_examples"),
        max_items=40,
        max_length=2000,
    )
    first_message = _clean_text(data.get("first_mes"), 2400)
    if first_message:
        examples.insert(0, first_message)

    normalized = {
        "name": name,
        "format": format_name,
        "compatibility": compatibility,
        "identity_facts": {k: v for k, v in identity_facts.items() if v},
        "style_traits": {k: v for k, v in style_traits.items() if v},
        "relationship_rules": {k: v for k, v in relationship_rules.items() if v},
        "examples": examples,
        **prov,
    }
    seed_material = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
    normalized["seed_id"] = "seed-" + hashlib.sha256(seed_material.encode("utf-8")).hexdigest()[:20]
    return normalized


def render_seed_instructions(seed: dict[str, Any]) -> list[str]:
    """Render reviewed seed sections into the canonical Agent.instructions shape."""
    result: list[str] = []
    identity = seed.get("identity_facts") or {}
    style = seed.get("style_traits") or {}
    relationship = seed.get("relationship_rules") or {}

    if identity.get("name"):
        result.append(f"Identity: your persona name is {identity['name']}.")
    if identity.get("description"):
        result.append(f"Identity facts: {identity['description']}")
    if style.get("personality"):
        result.append(f"Style/personality: {style['personality']}")
    if style.get("system_prompt"):
        result.append(f"Style guidance: {style['system_prompt']}")
    if style.get("post_history_instructions"):
        result.append(f"Conversation style guidance: {style['post_history_instructions']}")
    if relationship.get("scenario"):
        result.append(f"Relationship/context rule: {relationship['scenario']}")
    return [item for item in result if item.strip()]


def _seed_library_source(agent_id: UUID | str) -> str:
    return f"__yance_persona_seed_library__:{agent_id}"


def _guideline_library_source(agent_id: UUID | str) -> str:
    return f"__yance_persona_guidelines__:{agent_id}"


def _ensure_library(
    db: Session,
    agent: Agent,
    *,
    source: str,
    kind: str,
) -> Knowledge:
    repo = KnowledgeRepository(db)
    found = repo.get_by_sources(agent.organization_id, [source])
    if found:
        knowledge = found[0]
        KnowledgeToAgentRepository(db).create(
            KnowledgeToAgent(knowledge_id=knowledge.id, agent_id=agent.id)
        )
        return knowledge
    return create_text_source(
        db,
        agent.organization_id,
        source,
        f"{kind} library for Agent {agent.id}. Managed by existing ChatterMate Knowledge.",
        agent.id,
        meta_data={
            "yance_kind": kind,
            "yance_managed": True,
            "persona_mutation": False,
        },
    )


def _library_rows(db: Session, knowledge: Knowledge, kind: str) -> list[dict[str, Any]]:
    # Seed/guideline subpages have different page ids, so scan the source and
    # filter by explicit metadata rather than treating ordinary Knowledge as Persona.
    query = text(
        f'SELECT id, content, meta_data FROM {knowledge.schema}."{knowledge.table_name}" '
        "WHERE name = :source ORDER BY id ASC"
    )
    rows = db.execute(query, {"source": knowledge.source}).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        meta = dict(row.meta_data or {})
        if meta.get("yance_kind") != kind:
            continue
        result.append({"id": str(row.id), "content": row.content, "meta_data": meta})
    return result


def import_seed(
    db: Session,
    agent: Agent,
    payload: dict[str, Any],
    *,
    provenance: str,
    consent: bool,
) -> dict[str, Any]:
    seed = normalize_character_card(payload, provenance=provenance, consent=consent)
    library = _ensure_library(
        db, agent, source=_seed_library_source(agent.id), kind="persona_seed_library"
    )
    existing = {
        row["meta_data"].get("seed_id"): row
        for row in _library_rows(db, library, "persona_seed")
    }
    if seed["seed_id"] not in existing:
        insert_subpage(
            library,
            seed["seed_id"],
            json.dumps(seed, ensure_ascii=False, sort_keys=True),
            meta_data={
                "yance_kind": "persona_seed",
                "seed_id": seed["seed_id"],
                "seed_name": seed["name"],
                "format": seed["format"],
                "compatibility": seed["compatibility"],
                "provenance": seed["provenance"],
                "consent": True,
                "confidence": 1.0,
                "review_status": "imported-not-selected",
                "persona_mutation": False,
            },
        )
    return seed


def list_seeds(db: Session, agent: Agent) -> list[dict[str, Any]]:
    found = KnowledgeRepository(db).get_by_sources(
        agent.organization_id, [_seed_library_source(agent.id)]
    )
    if not found:
        return []
    result: list[dict[str, Any]] = []
    for row in _library_rows(db, found[0], "persona_seed"):
        try:
            seed = json.loads(row["content"])
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(seed, dict):
            result.append(seed)
    return result


def get_seed(db: Session, agent: Agent, seed_id: str) -> dict[str, Any]:
    for seed in list_seeds(db, agent):
        if seed.get("seed_id") == seed_id:
            return seed
    raise ValueError("persona_seed_not_found")


def compare_seeds(db: Session, agent: Agent, seed_ids: list[str]) -> dict[str, Any]:
    selected = [get_seed(db, agent, seed_id) for seed_id in seed_ids[:3]]
    return {
        "seeds": selected,
        "dimensions": ["identity_facts", "style_traits", "relationship_rules", "examples"],
    }



def _verified_scope_linkage(
    db: Session,
    agent: Agent,
    *,
    customer_id: UUID | str | None = None,
    session_id: UUID | str | None = None,
) -> tuple[Customer | None, SessionToAgent | None]:
    """Resolve explicit identities, enforcing the exact org/agent/contact link.

    Never use a missing or foreign explicit ID as an implicit global fallback.
    """
    customer: Customer | None = None
    session: SessionToAgent | None = None
    if customer_id is not None:
        try:
            key = UUID(str(customer_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("invalid_customer_id") from exc
        customer = db.query(Customer).filter(
            Customer.id == key,
            Customer.organization_id == agent.organization_id,
        ).first()
        if customer is None:
            raise ValueError("customer_not_found")
    if session_id is not None:
        try:
            key = UUID(str(session_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("invalid_session_id") from exc
        session = db.query(SessionToAgent).filter(
            SessionToAgent.session_id == key,
            SessionToAgent.organization_id == agent.organization_id,
            SessionToAgent.agent_id == agent.id,
        ).first()
        if session is None:
            raise ValueError("session_not_found")
        if customer is not None and session.customer_id != customer.id:
            raise ValueError("customer_session_mismatch")
        if customer is None:
            # A verified session is the only permitted customer inference.
            customer = db.query(Customer).filter(
                Customer.id == session.customer_id,
                Customer.organization_id == agent.organization_id,
            ).first()
            if customer is None:
                raise ValueError("session_customer_not_found")
    return customer, session


def _compose_global_base_instructions(
    existing: Iterable[str] | None, replacement_base: Iterable[str]
) -> list[str]:
    """Replace base while preserving W173-owned durable scoped rows exactly once.

    The base mutation cannot mint or edit scoped learning entries: those belong
    exclusively to the existing W173 review/promotion workflow.
    """
    marker = "[[YANCE_SCOPE:"
    result = [str(item) for item in replacement_base if not str(item).startswith(marker)]
    if not result:
        raise ValueError("base_persona_instructions_required")
    seen: set[str] = set()
    for item in existing or []:
        row = str(item)
        if row.startswith(marker) and row not in seen:
            result.append(row)
            seen.add(row)
    return result


def _contact_override(customer: Customer | None, agent_id: UUID | str) -> dict[str, Any] | None:
    if not customer or not isinstance(customer.meta_data, dict):
        return None
    mapping = customer.meta_data.get(PERSONA_META_NAMESPACE)
    if not isinstance(mapping, dict):
        return None
    value = mapping.get(str(agent_id))
    return value if isinstance(value, dict) else None


def set_seed_scope(
    db: Session,
    agent: Agent,
    seed: dict[str, Any],
    *,
    scope: str,
    customer_id: UUID | None = None,
    session_id: UUID | None = None,
) -> dict[str, Any]:
    instructions = render_seed_instructions(seed)
    if not instructions:
        raise ValueError("persona_seed_has_no_usable_instructions")
    projection = {
        "seed_id": seed["seed_id"],
        "seed_name": seed["name"],
        "instructions": instructions,
        "identity_facts": seed.get("identity_facts", {}),
        "style_traits": seed.get("style_traits", {}),
        "relationship_rules": seed.get("relationship_rules", {}),
        "provenance": seed["provenance"],
        "format": seed["format"],
        "mode": "replace",
    }
    # Validate explicitly supplied identifiers before any persisted mutation.
    customer, session = _verified_scope_linkage(
        db, agent, customer_id=customer_id, session_id=session_id
    )
    if scope == "global":
        AgentRepository(db).update_agent(
            agent.id,
            instructions=_compose_global_base_instructions(agent.instructions, instructions),
        )
        return {"scope": scope, "persisted": True, **projection}

    if scope == "contact":
        if customer_id is None:
            raise ValueError("contact_scope_requires_customer")
        if customer is None:
            raise ValueError("customer_not_found")
        meta = dict(customer.meta_data or {})
        mapping = dict(meta.get(PERSONA_META_NAMESPACE) or {})
        mapping[str(agent.id)] = projection
        meta[PERSONA_META_NAMESPACE] = mapping
        customer.meta_data = meta
        db.commit()
        return {"scope": scope, "persisted": True, **projection}

    if scope == "conversation":
        if session_id is None:
            raise ValueError("conversation_scope_requires_session")
        if session is None:
            raise ValueError("session_not_found")
        session.persona_override = projection
        db.commit()
        return {"scope": scope, "persisted": True, **projection}

    if scope == "turn":
        # P09: pure projection. The caller passes these instructions into the
        # existing Reply Brain/ChatAgent call for this turn; no persistence.
        return {"scope": scope, "persisted": False, **projection}

    raise ValueError("unsupported_persona_scope")


def clear_scope(
    db: Session,
    agent: Agent,
    *,
    scope: str,
    customer_id: UUID | None = None,
    session_id: UUID | None = None,
) -> None:
    customer, session = _verified_scope_linkage(
        db, agent, customer_id=customer_id, session_id=session_id
    )
    if scope == "contact":
        if customer_id is None:
            raise ValueError("contact_scope_requires_customer")
        if customer is None:
            raise ValueError("customer_not_found")
        meta = dict(customer.meta_data or {})
        mapping = dict(meta.get(PERSONA_META_NAMESPACE) or {})
        mapping.pop(str(agent.id), None)
        meta[PERSONA_META_NAMESPACE] = mapping
        customer.meta_data = meta
        db.commit()
        return
    if scope == "conversation":
        if session_id is None:
            raise ValueError("conversation_scope_requires_session")
        if session is None:
            raise ValueError("session_not_found")
        session.persona_override = None
        db.commit()
        return
    raise ValueError("unsupported_clear_scope")


def mark_style_source(
    db: Session,
    agent: Agent,
    knowledge_id: int,
    *,
    provenance: str,
    consent: bool,
    source_kind: str,
) -> dict[str, Any]:
    prov = _provenance(provenance, consent)
    knowledge = (
        db.query(Knowledge)
        .join(KnowledgeToAgent, KnowledgeToAgent.knowledge_id == Knowledge.id)
        .filter(
            Knowledge.id == knowledge_id,
            Knowledge.organization_id == agent.organization_id,
            KnowledgeToAgent.agent_id == agent.id,
        )
        .first()
    )
    if not knowledge:
        raise ValueError("knowledge_source_not_found")
    source_kind = _clean_text(source_kind, 80) or "authorized"
    metadata_patch = {
        "yance_style_learning": True,
        "style_source_kind": source_kind,
        **prov,
        "persona_mutation": False,
    }
    query = text(
        f'SELECT id, meta_data FROM {knowledge.schema}."{knowledge.table_name}" '
        "WHERE name = :source"
    )
    rows = db.execute(query, {"source": knowledge.source}).fetchall()
    update = text(
        f'UPDATE {knowledge.schema}."{knowledge.table_name}" '
        "SET meta_data = CAST(:meta_data AS jsonb) WHERE id = :chunk_id AND name = :source"
    )
    for row in rows:
        meta = dict(row.meta_data or {})
        meta.update(metadata_patch)
        db.execute(
            update,
            {
                "meta_data": json.dumps(meta, ensure_ascii=False),
                "chunk_id": row.id,
                "source": knowledge.source,
            },
        )
    db.commit()
    return {
        "knowledge_id": knowledge.id,
        "style_learning": True,
        "provenance": prov["provenance"],
        "consent": True,
        "chunks_marked": len(rows),
    }


def add_style_text_source(
    db: Session,
    agent: Agent,
    *,
    title: str,
    content: str,
    provenance: str,
    consent: bool,
    source_kind: str,
) -> Knowledge:
    prov = _provenance(provenance, consent)
    clean_title = _clean_text(title, 300)
    clean_content = str(content or "").strip()
    if not clean_title or not clean_content:
        raise ValueError("style_text_title_and_content_required")
    source_name = f"Style Corpus · {clean_title}"
    return create_text_source(
        db,
        agent.organization_id,
        source_name,
        clean_content,
        agent.id,
        meta_data={
            "yance_kind": "style_evidence",
            "yance_style_learning": True,
            "style_source_kind": _clean_text(source_kind, 80) or "authorized-chat",
            **prov,
            "persona_mutation": False,
        },
    )


def style_evidence(db: Session, agent: Agent, *, limit: int = 80) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for knowledge in KnowledgeRepository(db).get_by_agent(agent.id, 0, 500):
        query = text(
            f'SELECT id, content, meta_data FROM {knowledge.schema}."{knowledge.table_name}" '
            "WHERE name = :source ORDER BY id ASC"
        )
        for row in db.execute(query, {"source": knowledge.source}).fetchall():
            meta = dict(row.meta_data or {})
            if meta.get("yance_style_learning") is not True:
                continue
            result.append(
                {
                    "evidence_id": f"{knowledge.id}:{row.id}",
                    "knowledge_id": knowledge.id,
                    "content": str(row.content or ""),
                    "provenance": meta.get("provenance"),
                    "source_kind": meta.get("style_source_kind"),
                    "consent": meta.get("consent") is True,
                }
            )
            if len(result) >= limit:
                return result
    return result


def _strip_json_fence(value: str) -> str:
    text_value = (value or "").strip()
    match = re.fullmatch(
        r"\x60\x60\x60(?:json)?\s*([\s\S]*?)\s*\x60\x60\x60",
        text_value,
        flags=re.IGNORECASE,
    )
    return match.group(1).strip() if match else text_value


async def extract_style_features(db: Session, agent: Agent) -> dict[str, Any]:
    evidence = [row for row in style_evidence(db, agent) if row.get("consent")]
    if not evidence:
        raise ValueError("no_explicit_style_evidence")
    ai_config = AIConfigRepository(db).get_active_config(str(agent.organization_id))
    if not ai_config:
        raise RuntimeError("active_ai_config_unavailable")

    samples = [
        {
            "evidence_id": item["evidence_id"],
            "text": item["content"][:2400],
            "provenance": item["provenance"],
        }
        for item in evidence[:30]
    ]
    model = create_model(
        model_type=ai_config.model_type.value
        if hasattr(ai_config.model_type, "value")
        else ai_config.model_type,
        api_key=decrypt_api_key(ai_config.encrypted_api_key),
        model_name=ai_config.model_name,
        max_tokens=1800,
        base_url=(ai_config.settings or {}).get("base_url"),
    )
    extractor = AgnoAgent(
        name="Yance Style Evidence Extractor",
        model=model,
        instructions=(
            "Analyze only the explicitly-authorized style evidence supplied by the operator. "
            "Do not infer identity facts. Return JSON only with a features array. Each item must "
            "contain feature, value, confidence (0..1), evidence_ids. Allowed feature names: "
            + ", ".join(sorted(STYLE_FEATURES))
            + ". Evidence IDs must come from the supplied samples. Do not promote or persist anything."
        ),
    )
    response = await extractor.arun(json.dumps(samples, ensure_ascii=False))
    raw = response.content if hasattr(response, "content") else str(response)
    try:
        payload = json.loads(_strip_json_fence(str(raw)))
    except json.JSONDecodeError as exc:
        raise RuntimeError("style_feature_envelope_invalid") from exc

    features: list[dict[str, Any]] = []
    allowed_ids = {item["evidence_id"] for item in samples}
    provenance_by_id = {item["evidence_id"]: item.get("provenance") for item in samples}
    for item in payload.get("features", []) if isinstance(payload, dict) else []:
        if not isinstance(item, dict) or item.get("feature") not in STYLE_FEATURES:
            continue
        ids = [str(value) for value in item.get("evidence_ids", []) if str(value) in allowed_ids]
        try:
            confidence = max(0.0, min(1.0, float(item.get("confidence", 0))))
        except (TypeError, ValueError):
            confidence = 0.0
        if not ids or confidence <= 0:
            continue
        features.append(
            {
                "feature": item["feature"],
                "value": _clean_text(item.get("value"), 1200),
                "confidence": confidence,
                "evidence_ids": ids,
                "provenance": sorted({
                    str(provenance_by_id[eid]) for eid in ids if provenance_by_id.get(eid)
                }),
                "review_status": "proposed",
            }
        )
    return {"features": features, "evidence_count": len(samples), "persisted": False}


def review_guideline(
    db: Session,
    agent: Agent,
    *,
    decision: str,
    condition: str,
    action: str,
    description: str | None,
    confidence: float,
    evidence_ids: list[str],
    provenance: str,
) -> dict[str, Any]:
    if decision == "reject":
        return {"stored": False, "decision": "reject"}
    if decision not in {"adopt", "edit"}:
        raise ValueError("unsupported_guideline_review_decision")
    clean_condition = _clean_text(condition, 1200) or MATCH_ALWAYS
    clean_action = _clean_text(action, 1600)
    clean_description = _clean_text(description, 2400)
    clean_provenance = _clean_text(provenance, 1200)
    if not clean_action or not clean_provenance or not evidence_ids:
        raise ValueError("guideline_action_provenance_evidence_required")
    confidence = max(0.0, min(1.0, float(confidence)))

    # Validate non-always conditions with the mature rule-engine parser now, so
    # a bad expression can never be promoted into a runtime rule.
    if clean_condition != MATCH_ALWAYS:
        try:
            rule_engine.Rule(clean_condition)
        except rule_engine.errors.EngineError as exc:
            raise ValueError("invalid_guideline_condition") from exc

    material = json.dumps(
        {
            "condition": clean_condition,
            "action": clean_action,
            "description": clean_description,
            "evidence_ids": sorted(set(evidence_ids)),
            "provenance": clean_provenance,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    guideline_id = "guideline-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]
    library = _ensure_library(
        db, agent, source=_guideline_library_source(agent.id), kind="persona_guideline_library"
    )
    existing = {
        row["meta_data"].get("guideline_id")
        for row in _library_rows(db, library, "reviewed_guideline")
    }
    if guideline_id not in existing:
        insert_subpage(
            library,
            guideline_id,
            clean_action,
            meta_data={
                "yance_kind": "reviewed_guideline",
                "guideline_id": guideline_id,
                "condition": clean_condition,
                "action": clean_action,
                "description": clean_description,
                "confidence": confidence,
                "evidence_ids": sorted(set(evidence_ids))[:80],
                "provenance": clean_provenance,
                "review_decision": decision,
                "reviewed": True,
                "policy_owner": "rule-engine==5.0.2",
                "persona_mutation": False,
            },
        )
    return {
        "stored": True,
        "decision": decision,
        "guideline_id": guideline_id,
        "condition": clean_condition,
        "action": clean_action,
        "confidence": confidence,
    }


def list_guidelines(db: Session, agent: Agent) -> list[dict[str, Any]]:
    found = KnowledgeRepository(db).get_by_sources(
        agent.organization_id, [_guideline_library_source(agent.id)]
    )
    if not found:
        return []
    return [row["meta_data"] for row in _library_rows(db, found[0], "reviewed_guideline")]


def _guideline_matches(condition: str, context: PersonaContext) -> bool:
    if not condition or condition == MATCH_ALWAYS:
        return True
    try:
        return bool(rule_engine.Rule(condition).matches(context.as_rule_data()))
    except rule_engine.errors.EngineError:
        return False


def resolve_persona(
    db: Session,
    agent: Agent,
    *,
    customer_id: UUID | str | None = None,
    session_id: UUID | str | None = None,
    channel: str | None = None,
    current_turn_override: Iterable[str] | None = None,
) -> dict[str, Any]:
    customer, session = _verified_scope_linkage(
        db, agent, customer_id=customer_id, session_id=session_id
    )

    effective = _learning_scope(agent.instructions, str(customer.id) if customer else None)
    source_scope = "global"

    contact = _contact_override(customer, agent.id)
    if contact and contact.get("mode") == "replace":
        effective = _string_list(contact.get("instructions"))
        source_scope = "contact"

    conversation = session.persona_override if session and isinstance(session.persona_override, dict) else None
    if conversation and conversation.get("mode") == "replace":
        effective = _string_list(conversation.get("instructions"))
        source_scope = "conversation"

    customer_meta = customer.meta_data if customer and isinstance(customer.meta_data, dict) else {}
    context = PersonaContext(
        agent_id=str(agent.id),
        customer_id=str(customer.id) if customer else None,
        session_id=str(session.session_id) if session else None,
        channel=channel or (session.channel if session else None),
        language=_clean_text(customer_meta.get("language"), 80) or None,
        relationship_stage=_clean_text(customer_meta.get("relationship_stage"), 120) or None,
    )
    matched_guidelines: list[dict[str, Any]] = []
    for guideline in list_guidelines(db, agent):
        condition = str(guideline.get("condition") or MATCH_ALWAYS)
        if _guideline_matches(condition, context):
            action = _clean_text(guideline.get("action"), 1600)
            if action:
                effective.append(action)
                matched_guidelines.append(
                    {
                        "guideline_id": guideline.get("guideline_id"),
                        "condition": condition,
                        "action": action,
                        "confidence": guideline.get("confidence"),
                        "provenance": guideline.get("provenance"),
                    }
                )

    turn = _string_list(list(current_turn_override or []))
    if turn:
        effective.extend(turn)
        source_scope = "turn"

    return {
        "instructions": effective,
        "base_instructions": list(agent.instructions or []),
        "scope": source_scope,
        "contact_override": contact,
        "conversation_override": conversation,
        "turn_override": turn,
        "matched_guidelines": matched_guidelines,
        "context": context.as_rule_data(),
    }


def persona_history(agent: Agent) -> list[dict[str, Any]]:
    history: list[dict[str, Any]] = []
    for version in list(getattr(agent, "versions", []) or [])[-80:]:
        raw = getattr(version, "_instructions", getattr(version, "instructions", None))
        try:
            instructions = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError:
            instructions = [raw] if raw else []
        history.append(
            {
                "transaction_id": int(version.transaction_id),
                "instructions": instructions or [],
            }
        )
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
    return {
        "rolled_back": True,
        "transaction_id": transaction_id,
        "instructions": agent.instructions,
    }


def current_projection(
    db: Session,
    agent: Agent,
    *,
    customer_id: UUID | str | None = None,
    session_id: UUID | str | None = None,
) -> dict[str, Any]:
    resolved = resolve_persona(
        db,
        agent,
        customer_id=customer_id,
        session_id=session_id,
    )
    active_structured = resolved["conversation_override"] or resolved["contact_override"]
    if not active_structured:
        base_only = [
            str(item)
            for item in agent.instructions or []
            if not str(item).startswith("[[YANCE_SCOPE:")
        ]
        for seed in list_seeds(db, agent):
            if render_seed_instructions(seed) == base_only:
                active_structured = seed
                break
    active_structured = active_structured or {}
    return {
        "agent_id": str(agent.id),
        "base_persona": list(agent.instructions or []),
        "effective_persona": resolved["instructions"],
        "effective_scope": resolved["scope"],
        "contact_override": resolved["contact_override"],
        "conversation_override": resolved["conversation_override"],
        "matched_guidelines": resolved["matched_guidelines"],
        "identity_facts": active_structured.get("identity_facts", {}),
        "style_traits": active_structured.get("style_traits", {}),
        "relationship_rules": active_structured.get("relationship_rules", {}),
        "owner_contract": {
            "base": "ChatterMate Agent.instructions",
            "history": "SQLAlchemy-Continuum",
            "seed_style_guidelines": "ChatterMate Knowledge + Agno/PgVector",
            "guideline_matcher": "rule-engine==5.0.2",
            "learning": "Window173 public seam",
            "reply_consumption": "Reply Brain/Human-Likeness public seam",
        },
    }
