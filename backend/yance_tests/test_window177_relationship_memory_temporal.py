from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (BACKEND / relative).read_text(encoding="utf-8-sig")


def test_window177_uses_existing_customer_and_chat_history_authorities_only():
    source = _read("app/services/relationship_context.py")
    assert "Customer.meta_data" in source
    assert "ChatHistory is the conversation-evidence authority" in source
    assert "RELATIONSHIP_MEMORY_KEY = \"relationship_memory\"" in source
    for forbidden in (
        "YanceRelationshipDB",
        "YanceMemoryDB",
        "create_engine(",
        "scheduler",
        "Celery",
        "apscheduler",
    ):
        assert forbidden not in source


def test_window177_requires_explicit_confirmation_and_provenance():
    source = _read("app/services/relationship_context.py")
    schema = _read("app/models/schemas/relationship.py")
    assert "operator_confirmation" in source
    assert "confirmed=True" in source
    assert "source does not belong to this person" in source
    assert "unsupported source reference" in source
    assert 'MemoryEffect = Literal["context", "no_reply", "defer"]' in schema


def test_window177_temporal_is_explicit_and_fail_closed():
    source = _read("app/services/relationship_context.py")
    assert "contact_timezone_known=known" in source
    assert 'precision = "operator_fallback"' in source
    assert "# Never enforce a fabricated contact-local schedule." in source
    assert "outside_confirmed_contact_window" in source
    assert "ZoneInfo(request.contact_timezone)" in source


def test_window177_relationship_metrics_are_derived_not_persisted():
    source = _read("app/services/relationship_context.py")
    assert "def _metrics(" in source
    assert "def _decision(" in source
    assert "customer.meta_data = meta" in source
    # Only bounded confirmed memory/temporal settings are persisted.
    assert 'meta[RELATIONSHIP_MEMORY_KEY] = payload' in source
    for key in ("stage", "momentum", "temperature", "risk"):
        assert f'meta["{key}"]' not in source
        assert f"meta['{key}']" not in source


def test_window177_goal_inputs_are_consumed_without_second_goal_store():
    api = _read("app/api/people.py")
    assert "current_goal: Optional[str] = Query" in api
    assert "long_term_goal: Optional[str] = Query" in api
    assert "second Goal authority" in api
    assert "GoalProjection(" in api


def test_window177_owner_contract_admits_native_projection_but_holds_optional_graph():
    source = _read("app/core/yance_owner_contract.py")
    assert '"relationship_memory": OwnerContract(' in source
    assert '"chattermate.customer_chat_history_projection"' in source
    assert '"relationship_graph": OwnerContract(' in source
    assert '"graphiti+neo4j_aura"' in source
    assert "Graphiti correctness hold" in source


def test_window177_api_routes_are_real_and_permission_guarded():
    api = _read("app/api/people.py")
    for route in (
        '@router.get("/{customer_id}/relationship-context"',
        '@router.put("/{customer_id}/relationship-memory"',
        '@router.patch("/{customer_id}/relationship-temporal"',
    ):
        assert route in api
    assert "_require_people_access(current_user, db, PEOPLE_WRITE_PERMISSIONS)" in api
