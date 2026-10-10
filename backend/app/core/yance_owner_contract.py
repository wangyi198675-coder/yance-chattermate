"""Yance product-semantic owner selection contract.

This module is deliberately declarative. It selects WHO owns a primitive and
whether that owner has passed production admission; it never performs the
primitive itself.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class OwnerContract:
    owner: str
    authority: str
    admitted: bool
    reason: str


class OwnerNotAdmitted(RuntimeError):
    pass


class UnknownOwnerContract(KeyError):
    pass


GIRLFRIEND_OWNER_CONTRACTS = {
    "send_message": OwnerContract("chattermate.message_delivery", "ChatHistory + ChannelConversation", True, "native"),
    "find_contact": OwnerContract("chattermate.customer_people", "Customer", True, "native"),
    "search_history": OwnerContract("chattermate.chat_history", "ChatHistory", True, "native"),
    "assign_handoff": OwnerContract("chattermate.human_routing", "SessionToAgent", True, "native"),
    "search_knowledge": OwnerContract("chattermate.knowledge", "Knowledge + FAQ", True, "native"),
    "run_workflow": OwnerContract("chattermate.workflow", "Workflow + SessionToAgent", True, "native"),
    "knowledge_ingest": OwnerContract("chattermate.knowledge", "Knowledge", True, "native"),
    "faq_generate": OwnerContract("chattermate.faq_generator", "FAQ + Knowledge", True, "native"),
    "call_tool": OwnerContract("chattermate.mcp", "MCPTool", True, "native"),
    "crm_sync": OwnerContract("chattermate.crm", "Customer remains canonical", True, "native adapter"),
    "ticket_investigation": OwnerContract("chattermate.ticket_investigation", "Ticket + Investigation", True, "native"),
    "jira_action": OwnerContract("chattermate.jira", "Jira integration", True, "native"),
    "database_tool": OwnerContract("chattermate.guardrailed_db", "external DB remains source", True, "native guarded tool"),
    "notification": OwnerContract("chattermate.notifications", "User notification state", True, "native"),
    "model_selection": OwnerContract("chattermate.model_catalog", "AIConfig", True, "native"),
    "persona_history": OwnerContract("sqlalchemy_continuum", "Agent.instructions history only", True, "Wave B admitted"),
    "deterministic_image_edit": OwnerContract("imagemagick", "artifact path -> ChatterMate FileAttachment", True, "Wave B admitted external CLI"),
    "audio_video_transform": OwnerContract("ffmpeg", "artifact path -> ChatterMate FileAttachment", True, "Wave B admitted external CLI"),
    "translation": OwnerContract("deepl.official_translation_api", "encrypted ChatHistory.attributes projection + Customer.meta_data language preference", True, "Window178 mature official owner; runtime health remains credential-gated"),
    "relationship_memory": OwnerContract(
        "chattermate.customer_chat_history_projection",
        "Customer.meta_data + ChatHistory evidence",
        True,
        "Window177 evidence-governed native projection",
    ),
    "relationship_graph": OwnerContract(
        "graphiti+neo4j_aura",
        "optional derived graph only",
        False,
        "Graphiti correctness hold; never canonical person/conversation truth",
    ),
    "voice": OwnerContract("voice_owner", "generated FileAttachment", False, "Wave D not admitted"),
    "generative_media": OwnerContract("comfyui", "generated FileAttachment", False, "Wave E not admitted"),
}

PERSONA_OWNER_CONTRACTS = {
    "base_persona": OwnerContract("chattermate.agent", "Agent.instructions", True, "canonical current Persona authority"),
    "history": OwnerContract("sqlalchemy_continuum", "Agent.instructions versions", True, "existing version owner"),
    "seed_library": OwnerContract("chattermate.knowledge_agno_pgvector", "Knowledge + PgVector metadata", True, "no second Persona DB/vector DB"),
    "style_corpus": OwnerContract("chattermate.knowledge_agno_pgvector", "explicitly-consented Knowledge/PgVector rows", True, "ordinary Knowledge remains inert"),
    "reviewed_guidelines": OwnerContract("chattermate.knowledge_agno_pgvector+rule-engine", "Knowledge metadata + deterministic condition match", True, "rule-engine 5.0.2 owns condition evaluation without a second LLM runtime"),
    "contact_scope": OwnerContract("chattermate.customer", "Customer.meta_data namespaced override", True, "existing person/contact owner"),
    "conversation_scope": OwnerContract("chattermate.session_to_agent", "SessionToAgent.persona_override", True, "existing conversation owner"),
    "turn_scope": OwnerContract("transient_reply_seam", "non-persisted ChatAgent/Reply Brain call argument", True, "P09 never creates stored Persona state"),
}

REPLY_OWNER_CONTRACTS = {
    "candidate_generation": OwnerContract("chattermate.agent", "Agent + AIConfig", True, "native"),
    "candidate_ranking": OwnerContract("chattermate.agent", "Agent + AIConfig", True, "native"),
    "recompute": OwnerContract("chattermate.agent", "Agent + AIConfig", True, "native"),
    "file_attachment": OwnerContract("chattermate.file_attachment", "FileAttachment", True, "native"),
    "final_send": OwnerContract("chattermate.message_delivery", "ChatHistory + ChannelConversation", True, "native"),
    "learning_evidence": OwnerContract("chattermate.chat_history_rating", "ChatHistory + Rating", True, "native"),
    "persona_history": OwnerContract("sqlalchemy_continuum", "Agent.instructions history only", True, "Wave B admitted"),
    "deterministic_image_edit": OwnerContract("imagemagick", "artifact path -> ChatterMate FileAttachment", True, "Wave B admitted external CLI"),
    "audio_video_transform": OwnerContract("ffmpeg", "artifact path -> ChatterMate FileAttachment", True, "Wave B admitted external CLI"),
    "translation": OwnerContract("deepl.official_translation_api", "encrypted ChatHistory.attributes projection + Customer.meta_data language preference", True, "Window178 mature official owner; runtime health remains credential-gated"),
    "relationship_memory": OwnerContract(
        "chattermate.customer_chat_history_projection",
        "Customer.meta_data + ChatHistory evidence",
        True,
        "Window177 evidence-governed native projection",
    ),
    "relationship_graph": OwnerContract(
        "graphiti+neo4j_aura",
        "optional derived graph only",
        False,
        "Graphiti correctness hold; never canonical person/conversation truth",
    ),
    "voice": OwnerContract("voice_owner", "generated FileAttachment", False, "Wave D not admitted"),
    "generative_media": OwnerContract("comfyui", "generated FileAttachment", False, "Wave E not admitted"),
}


def get_owner_contract(surface: str, action: str) -> OwnerContract:
    table = (
        GIRLFRIEND_OWNER_CONTRACTS if surface == "girlfriend"
        else REPLY_OWNER_CONTRACTS if surface == "reply"
        else PERSONA_OWNER_CONTRACTS if surface == "persona"
        else None
    )
    if table is None or action not in table:
        raise UnknownOwnerContract(f"{surface}:{action}")
    return table[action]


def require_admitted(surface: str, action: str) -> OwnerContract:
    contract = get_owner_contract(surface, action)
    if not contract.admitted:
        raise OwnerNotAdmitted(f"{surface}:{action} -> {contract.owner}: {contract.reason}")
    return contract
