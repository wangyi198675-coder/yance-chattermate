"""Guard the single native owner-to-People goal projection seam (W339)."""
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (BACKEND / path).read_text(encoding="utf-8-sig")


def test_people_goal_read_uses_existing_customer_owner_after_access_checks():
    source = _read("app/api/people.py")
    start = source.index("async def get_relationship_context(")
    end = source.index('@router.put("/{customer_id}/relationship-memory"', start)
    endpoint = source[start:end]
    assert endpoint.index("_require_people_access(") < endpoint.index("goal_projection(customer")
    assert endpoint.index("get_customer(current_user.organization_id, customer_id)") < endpoint.index("goal_projection(customer")
    assert "goal_projection(customer, current=current_goal)" in endpoint
    assert "long_term=long_term_goal or stored.long_term" in endpoint
    assert "goal_input:long_term" in endpoint
    assert 'relationship_memory:goal:long_term' in endpoint


def test_native_builder_defaults_to_confirmed_owner_projection():
    source = _read("app/services/relationship_context.py")
    start = source.index("def build_relationship_context(")
    assert "goals = goals if goals is not None else goal_projection(customer)" in source[start:]


def test_unconfirmed_inactive_and_cleared_goals_remain_fail_closed():
    source = _read("app/services/relationship_context.py")
    start = source.index("def goal_projection(")
    end = source.index("def set_long_term_goal(", start)
    projection = source[start:end]
    assert 'raw.get("confirmed") is True' in projection
    assert 'raw.get("active") is True' in projection
    assert 'isinstance(raw.get("long_term"), str)' in projection
    assert 'long_term = raw["long_term"].strip() or None' in projection


def test_no_secondary_goal_persistence_or_scheduler():
    source = _read("app/api/people.py")
    start = source.index("async def get_relationship_context(")
    end = source.index('@router.put("/{customer_id}/relationship-memory"', start)
    endpoint = source[start:end]
    for forbidden in ("db.commit(", "db.add(", "scheduler", "Graphiti", "set_long_term_goal("):
        assert forbidden not in endpoint
