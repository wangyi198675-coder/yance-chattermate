from pathlib import Path
import ast

BACKEND = Path(__file__).resolve().parents[1]


def _agent_column_attrs():
    tree = ast.parse((BACKEND / "app/models/agent.py").read_text(encoding="utf-8-sig"))
    agent = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Agent")
    return {
        node.targets[0].id
        for node in agent.body
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and isinstance(node.value, ast.Call)
        and getattr(node.value.func, "id", None) == "Column"
    }


def test_persona_history_uses_continuum_and_keeps_agent_as_current_authority():
    requirements = (BACKEND / "requirements.txt").read_text(encoding="utf-8-sig")
    assert "SQLAlchemy-Continuum==1.8.0" in requirements

    versioning = (BACKEND / "app/models/versioning.py").read_text(encoding="utf-8-sig")
    assert "make_versioned(user_cls=None)" in versioning

    agent_source = (BACKEND / "app/models/agent.py").read_text(encoding="utf-8-sig")
    tree = ast.parse(agent_source)
    agent = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Agent")
    versioned = next(
        node for node in agent.body
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "__versioned__" for t in node.targets)
    )
    config = ast.literal_eval(versioned.value)
    columns = _agent_column_attrs()
    assert "_instructions" in columns
    assert "id" in columns
    assert set(config["exclude"]) == columns - {"id", "_instructions"}
    assert "_instructions" not in config["exclude"]


def test_persona_history_migration_is_history_only_and_chains_from_current_head():
    migration = (BACKEND / "alembic/versions/yance_persona_history_002.py").read_text(encoding="utf-8-sig")
    assert 'down_revision = "yance_person_identity_001"' in migration
    assert '"agents_version"' in migration
    assert '"transaction"' in migration
    assert '"instructions"' in migration
    for forbidden in ("name", "description", "tools", "is_active", "guardrail_prompt"):
        assert f'"{forbidden}"' not in migration
