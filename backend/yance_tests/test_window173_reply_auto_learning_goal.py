import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

_scope_spec = importlib.util.spec_from_file_location(
    "window173_yance_learning_scope",
    ROOT / "backend/app/core/yance_learning_scope.py",
)
_scope_module = importlib.util.module_from_spec(_scope_spec)
assert _scope_spec and _scope_spec.loader
_scope_spec.loader.exec_module(_scope_module)
effective_agent_instructions = _scope_module.effective_agent_instructions


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_scoped_learning_rules_are_filtered_without_a_second_store():
    instructions = [
        "ordinary rule",
        "[[YANCE_SCOPE:global]] global rule",
        "[[YANCE_SCOPE:contact:alice]] alice only",
        "[[YANCE_SCOPE:contact:bob]] bob only",
    ]
    assert effective_agent_instructions(instructions, "alice") == [
        "ordinary rule",
        "global rule",
        "alice only",
    ]
    assert effective_agent_instructions(instructions, "bob") == [
        "ordinary rule",
        "global rule",
        "bob only",
    ]
    assert effective_agent_instructions(instructions, None) == [
        "ordinary rule",
        "global rule",
    ]


def test_reply_brain_reuses_chat_agent_and_is_generation_only():
    source = read("backend/app/services/yance_reply_runtime.py")
    assert "ChatAgent.create_async" in source
    assert "_get_llm_response_only" in source
    assert "limit = 5 if limit > 3 else max(0, limit)" in source
    assert '"state": "ready" | "no_reply" | "defer"' in source
    assert "expected_revision != current_revision" in source
    assert "humanLikeness" in source
    assert "sendMessage" not in source
    assert "create_engine(" not in source
    assert "declarative_base(" not in source


def test_ai_auto_revalidates_before_bot_persistence_and_both_auto_callers_opt_in():
    agent = read("backend/app/agents/chat_agent.py")
    channels = read("backend/app/services/channel_chat.py")
    widget = read("backend/app/api/widget_chat.py")

    assert "require_auto_send_authority: bool = False" in agent
    assert 'return "manual_takeover"' in agent
    assert 'return "ai_auto_permission_revoked"' in agent
    assert 'return "conversation_context_changed"' in agent
    guard_at = agent.index("Revalidate the canonical AI_AUTO authority")
    store_at = agent.index("stored_message = chat_repo.create_message", guard_at)
    assert guard_at < store_at
    assert "require_auto_send_authority=True" in channels
    assert "require_auto_send_authority=True" in widget
    assert "_auto_abort_reason" in channels
    assert "_auto_abort_reason" in widget


def test_release_to_ai_requires_confirmation_and_existing_agent_permission():
    source = read("backend/app/api/session_to_agent.py")
    assert '"/{session_id}/release-to-ai"' in source
    assert "explicit_ai_auto_confirmation_required" in source
    assert "agent.ai_replies_enabled" in source
    assert "session.user_id = None" in source
    assert "session.status = SessionStatus.OPEN" in source
    # Window173 does not manufacture or persist a second mode owner.
    release = source[source.index('"/{session_id}/release-to-ai"'):]
    assert "Agent(" not in release
    assert "SessionToAgent(" not in release


def test_learning_is_evidence_first_and_only_finalized_after_canonical_delivery():
    runtime = read("backend/app/services/yance_reply_runtime.py")
    socket = read("backend/app/api/widget_chat.py")
    assert "yance_reply_evidence" in runtime
    assert "do_not_learn" in runtime
    assert "sent_message_id" in runtime
    assert "outcome" in runtime
    assert "if delivery.ok and not was_duplicate:" in socket
    delivery_at = socket.index("delivery = await deliver_to_customer")
    learn_at = socket.index("finalize_successful_send_learning", delivery_at)
    assert delivery_at < learn_at
    assert "AgentRepository(db).update_agent(agent.id, instructions=instructions)" in runtime
    assert "version_class(Agent)" in runtime
    assert "version.revert()" in runtime


def test_admitted_customer_long_term_goal_and_peer_typing_owner_truth():
    runtime = read("backend/app/services/yance_reply_runtime.py")
    assert '"long_term_goal_owner": "ready"' in runtime
    assert '"goal_owner": "Customer.meta_data.relationship_memory"' in runtime
    assert '"peer_typing_owner": "unavailable"' in runtime
