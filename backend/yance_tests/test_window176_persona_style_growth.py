from pathlib import Path
import ast
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable
from uuid import UUID

import pytest
import rule_engine


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
SERVICE_PATH = BACKEND / "app/services/yance_persona_growth.py"


def _load_pure_persona_symbols():
    """Execute only Window176's pure semantic helpers from the real source file.

    Importing app.services normally executes app/__init__.py -> app.main and
    therefore boots the entire backend dependency graph. These tests deliberately
    isolate the actual pure functions instead of installing unrelated production
    connectors just to collect one test module.
    """
    source = SERVICE_PATH.read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    wanted_assigns = {
        "STYLE_FEATURES",
        "CHARACTER_CARD_V2",
        "CHARACTER_CARD_V3",
        "MATCH_ALWAYS",
    }
    wanted_defs = {
        "PersonaContext",
        "_clean_text",
        "_string_list",
        "_provenance",
        "normalize_character_card",
        "render_seed_instructions",
        "_guideline_matches",
    }
    body = [
        ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    ]
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = {target.id for target in node.targets if isinstance(target, ast.Name)}
            if names & wanted_assigns:
                body.append(node)
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in wanted_defs:
            body.append(node)
    module = ast.Module(body=body, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        "ast": ast,
        "hashlib": hashlib,
        "json": json,
        "dataclass": dataclass,
        "Any": Any,
        "Iterable": Iterable,
        "UUID": UUID,
        "rule_engine": rule_engine,
    }
    exec(compile(module, str(SERVICE_PATH), "exec"), namespace)
    return namespace


PURE = _load_pure_persona_symbols()
normalize_character_card = PURE["normalize_character_card"]
render_seed_instructions = PURE["render_seed_instructions"]
PersonaContext = PURE["PersonaContext"]
_guideline_matches = PURE["_guideline_matches"]
MATCH_ALWAYS = PURE["MATCH_ALWAYS"]


V2 = {
    "spec": "chara_card_v2",
    "spec_version": "2.0",
    "data": {
        "name": "Mina",
        "description": "A Berlin atelier owner.",
        "personality": "Warm, direct, mature.",
        "scenario": "Long-running personal conversation.",
        "first_mes": "Hi.",
        "mes_example": ["Short answer.", "A second example."],
        "system_prompt": "Keep replies natural and concise.",
        "post_history_instructions": "Do not interview the other person.",
    },
}

V3 = {
    "spec": "chara_card_v3",
    "spec_version": "3.0",
    "data": {
        **V2["data"],
        "assets": [{"type": "icon", "uri": "embeded://avatar"}],
        "nickname": "experimental-v3-field",
    },
}


def test_character_card_v2_maps_identity_style_relationship_without_prompt_blob():
    seed = normalize_character_card(
        V2,
        provenance="user-supplied authorized card",
        consent=True,
    )
    assert seed["format"] == "character-card-v2"
    assert seed["compatibility"] == "stable-v2"
    assert seed["identity_facts"]["name"] == "Mina"
    assert "personality" in seed["style_traits"]
    assert "scenario" in seed["relationship_rules"]
    assert seed["consent"] is True
    instructions = render_seed_instructions(seed)
    assert any(row.startswith("Identity:") for row in instructions)
    assert any(row.startswith("Style/personality:") for row in instructions)
    assert any(row.startswith("Relationship/context rule:") for row in instructions)


def test_character_card_v3_is_conservative_compatibility_read_not_experimental_promotion():
    seed = normalize_character_card(
        V3,
        provenance="user-supplied V3 card",
        consent=True,
    )
    assert seed["format"] == "character-card-v3"
    assert seed["compatibility"] == "v3-conservative-v2-field-map"
    serialized = str(seed)
    assert "experimental-v3-field" not in serialized
    assert "assets" not in serialized


@pytest.mark.parametrize(
    "provenance,consent,code",
    [
        ("", True, "provenance_required"),
        ("authorized", False, "explicit_style_or_seed_consent_required"),
    ],
)
def test_seed_import_requires_provenance_and_explicit_consent(provenance, consent, code):
    with pytest.raises(ValueError, match=code):
        normalize_character_card(V2, provenance=provenance, consent=consent)


def test_rule_engine_is_mature_condition_owner_and_match_is_fail_closed():
    context = PersonaContext(
        agent_id="agent",
        customer_id="customer",
        session_id="session",
        channel="whatsapp",
        language="de",
        relationship_stage="warm",
    )
    assert _guideline_matches(MATCH_ALWAYS, context) is True
    assert _guideline_matches('channel == "whatsapp" and relationship_stage == "warm"', context) is True
    assert _guideline_matches('channel == "telegram"', context) is False
    assert _guideline_matches("this is not valid rule syntax ???", context) is False


def test_ordinary_knowledge_has_no_automatic_persona_mutation_path():
    normal_api = (BACKEND / "app/api/knowledge.py").read_text(encoding="utf-8-sig")
    page_editor = (BACKEND / "app/knowledge/page_editor.py").read_text(encoding="utf-8-sig")
    persona = SERVICE_PATH.read_text(encoding="utf-8-sig")

    assert "yance_style_learning" not in normal_api
    assert "meta_data: Optional[Dict[str, Any]] = None" in page_editor
    assert 'meta.get("yance_style_learning") is not True' in persona
    assert '"persona_mutation": False' in persona
    assert "mark_style_source" in persona
    assert "explicit_style_or_seed_consent_required" in persona


def test_no_second_persona_vector_rule_or_llm_persistence_owner_is_created():
    service = SERVICE_PATH.read_text(encoding="utf-8-sig")
    api = (BACKEND / "app/api/yance_persona.py").read_text(encoding="utf-8-sig")
    migration = (BACKEND / "alembic/versions/yance_persona_session_override_003.py").read_text(
        encoding="utf-8-sig"
    )
    requirements = (BACKEND / "requirements.txt").read_text(encoding="utf-8-sig")

    assert "rule-engine==5.0.2" in requirements
    assert "create_model(" in service
    assert "AgnoAgent" in service
    assert "Parlant" not in requirements
    assert "declarative_base" not in service
    assert "create_all" not in service
    assert "CREATE TABLE" not in service.upper()
    assert "CREATE TABLE" not in api.upper()
    assert "op.add_column(" in migration
    assert "persona_override" in migration
    assert "op.create_table" not in migration


def test_scope_chain_uses_existing_agent_customer_session_and_turn_is_transient():
    service = SERVICE_PATH.read_text(encoding="utf-8-sig")
    session_model = (BACKEND / "app/models/session_to_agent.py").read_text(encoding="utf-8-sig")

    assert 'if scope == "global"' in service
    assert 'if row.startswith(marker) and row not in seen:' in service
    assert "_compose_global_base_instructions(agent.instructions, instructions)" in service
    assert 'if scope == "contact"' in service
    assert 'meta[PERSONA_META_NAMESPACE] = mapping' in service
    assert 'if scope == "conversation"' in service
    assert "session.persona_override = projection" in service
    assert 'if scope == "turn"' in service
    assert '"persisted": False' in service
    assert "persona_override = Column(JSON, nullable=True)" in session_model


def test_runtime_consumes_scope_projection_without_replacing_chatagent():
    chat_agent = (BACKEND / "app/agents/chat_agent.py").read_text(encoding="utf-8-sig")
    mcp = (BACKEND / "app/tools/mcp_manager.py").read_text(encoding="utf-8-sig")

    assert "from app.services.yance_persona_growth import resolve_persona" in chat_agent
    assert 'self.persona_instructions = list(self.persona_projection["instructions"])' in chat_agent
    assert 'wrap_operator_block("\\n".join(self.persona_instructions))' in chat_agent
    assert "persona_turn_override: list[str] | None = None" in chat_agent
    assert "persona_turn_override: list[str] | None = None" in mcp
    assert "persona_turn_override=persona_turn_override" in mcp


def test_reply_brain_and_learning_are_public_seams_not_reimplemented():
    service = SERVICE_PATH.read_text(encoding="utf-8-sig")
    host = (FRONTEND / "src/yance/YanceNativeHostView.vue").read_text(encoding="utf-8-sig")

    assert "app.core.yance_learning_scope" in service
    assert "Window173 public seam" in service
    assert "Reply Brain/Human-Likeness public seam" in service
    assert "persona-turn-override" in host
    assert '@turn-override="forwardPersonaTurnOverride"' in host
    assert "finalize_successful_send_learning" not in service
    assert "record_candidate_evidence" not in service


def test_persona_ui_separates_identity_style_relationship_and_enables_real_control():
    studio = (FRONTEND / "src/yance/components/YancePersonaStudio.vue").read_text(
        encoding="utf-8-sig"
    )
    host = (FRONTEND / "src/yance/YanceNativeHostView.vue").read_text(encoding="utf-8-sig")

    for marker in (
        'data-persona-section="identity"',
        'data-persona-section="style"',
        'data-persona-section="relationship"',
        "data-yance-persona-seed-library",
        "data-yance-style-corpus",
        "data-yance-persona-history",
        "data-yance-character-card-json",
        "data-yance-style-consent",
    ):
        assert marker in studio

    tree = ast.parse((BACKEND / "app/core/yance_owner_contract.py").read_text(encoding="utf-8-sig"))
    assert any(
        isinstance(node, ast.Assign)
        and any(getattr(target, "id", "") == "PERSONA_OWNER_CONTRACTS" for target in node.targets)
        for node in tree.body
    )
    assert 'data-owner-state="ready"' in host
    assert '@click="openPersonaStudio(chat)"' in host


def test_history_and_rollback_remain_sqlalchemy_continuum_over_agent_instructions():
    service = SERVICE_PATH.read_text(encoding="utf-8-sig")
    owner = (BACKEND / "app/core/yance_owner_contract.py").read_text(encoding="utf-8-sig")

    assert "version_class(Agent)" in service
    assert "version.revert()" in service
    assert '"history": OwnerContract("sqlalchemy_continuum", "Agent.instructions versions"' in owner


def test_session_override_migration_extends_canonical_c3_head_only():
    migration = (BACKEND / "alembic/versions/yance_persona_session_override_003.py").read_text(
        encoding="utf-8-sig"
    )
    assert 'revision = "yance_persona_session_override_003"' in migration
    assert 'down_revision = "window205_owner_seam_001"' in migration
    assert 'sa.Column("persona_override", sa.JSON(), nullable=True)' in migration
    assert 'op.alter_column(' not in migration  # C3/W258 already widened version_num


def test_alembic_has_single_head_after_window176_without_importing_app_runtime():
    revisions: dict[str, list[str]] = {}
    for path in (BACKEND / "alembic/versions").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        revision = None
        downs: list[str] = []
        for node in tree.body:
            if isinstance(node, ast.Assign):
                names = {target.id for target in node.targets if isinstance(target, ast.Name)}
                value_node = node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                names = {node.target.id}
                value_node = node.value
            else:
                continue
            if value_node is None:
                continue
            if "revision" in names:
                revision = ast.literal_eval(value_node)
            elif "down_revision" in names:
                value = ast.literal_eval(value_node)
                if isinstance(value, str):
                    downs = [value]
                elif isinstance(value, tuple):
                    downs = [item for item in value if isinstance(item, str)]
                elif value is None:
                    downs = []
        if isinstance(revision, str):
            revisions[revision] = downs
    referenced = {down for downs in revisions.values() for down in downs}
    heads = sorted(set(revisions) - referenced)
    assert heads == ["yance_persona_session_override_003"]


def test_window176_python_files_compile():
    for relative in (
        "app/services/yance_persona_growth.py",
        "app/api/yance_persona.py",
        "app/agents/chat_agent.py",
        "app/tools/mcp_manager.py",
        "app/knowledge/page_editor.py",
        "app/models/session_to_agent.py",
        "alembic/versions/yance_persona_session_override_003.py",
    ):
        source = (BACKEND / relative).read_text(encoding="utf-8-sig")
        compile(source, str(BACKEND / relative), "exec")
