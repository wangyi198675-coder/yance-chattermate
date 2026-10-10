from pathlib import Path
import importlib
import sys
import types
import pytest

BACKEND = Path(__file__).resolve().parents[1]
APP = BACKEND / "app"
for name, path in {"app": APP, "app.core": APP / "core"}.items():
    if name not in sys.modules:
        pkg = types.ModuleType(name)
        pkg.__path__ = [str(path)]
        sys.modules[name] = pkg


def test_owner_contract_routes_product_semantics_to_mature_owners_only():
    m = importlib.import_module("app.core.yance_owner_contract")
    assert m.GIRLFRIEND_OWNER_CONTRACTS["send_message"].owner == "chattermate.message_delivery"
    assert m.GIRLFRIEND_OWNER_CONTRACTS["find_contact"].owner == "chattermate.customer_people"
    assert m.GIRLFRIEND_OWNER_CONTRACTS["run_workflow"].owner == "chattermate.workflow"
    assert m.GIRLFRIEND_OWNER_CONTRACTS["knowledge_ingest"].owner == "chattermate.knowledge"
    assert m.GIRLFRIEND_OWNER_CONTRACTS["faq_generate"].owner == "chattermate.faq_generator"
    assert m.GIRLFRIEND_OWNER_CONTRACTS["call_tool"].owner == "chattermate.mcp"
    assert m.GIRLFRIEND_OWNER_CONTRACTS["crm_sync"].owner == "chattermate.crm"
    assert m.GIRLFRIEND_OWNER_CONTRACTS["ticket_investigation"].owner == "chattermate.ticket_investigation"
    assert m.GIRLFRIEND_OWNER_CONTRACTS["jira_action"].owner == "chattermate.jira"
    assert m.GIRLFRIEND_OWNER_CONTRACTS["database_tool"].owner == "chattermate.guardrailed_db"
    assert m.GIRLFRIEND_OWNER_CONTRACTS["notification"].owner == "chattermate.notifications"
    assert m.REPLY_OWNER_CONTRACTS["final_send"].owner == "chattermate.message_delivery"
    assert m.REPLY_OWNER_CONTRACTS["persona_history"].owner == "sqlalchemy_continuum"
    assert m.REPLY_OWNER_CONTRACTS["deterministic_image_edit"].admitted
    assert m.REPLY_OWNER_CONTRACTS["audio_video_transform"].admitted
    assert m.GIRLFRIEND_OWNER_CONTRACTS["deterministic_image_edit"].owner == "imagemagick"
    assert m.REPLY_OWNER_CONTRACTS["relationship_memory"].admitted
    assert m.REPLY_OWNER_CONTRACTS["relationship_memory"].owner == "chattermate.customer_chat_history_projection"
    assert not m.REPLY_OWNER_CONTRACTS["relationship_graph"].admitted
    assert m.REPLY_OWNER_CONTRACTS["translation"].owner == "deepl.official_translation_api"
    assert m.REPLY_OWNER_CONTRACTS["translation"].admitted
    assert m.GIRLFRIEND_OWNER_CONTRACTS["translation"].owner == "deepl.official_translation_api"


def test_owner_contract_fails_closed_for_unadmitted_or_unknown_owner():
    m = importlib.import_module("app.core.yance_owner_contract")
    assert m.require_admitted("reply", "translation").owner == "deepl.official_translation_api"
    with pytest.raises(m.UnknownOwnerContract):
        m.require_admitted("girlfriend", "invent_a_new_engine")


def test_owner_contract_is_declarative_and_does_not_execute_actions():
    source = (APP / "core/yance_owner_contract.py").read_text(encoding="utf-8-sig")
    for forbidden in ("subprocess", "requests.", "httpx", "asyncio", "send_text(", "execute("):
        assert forbidden not in source
    assert "argos_translate" not in source
