"""W289 focused executable regressions: exact persisted identity and W173 preservation.

AST-load real source functions with a query-filtering fake DB. This exercises source
logic without initializing the application's provider runtimes. Physical PG proof
is recorded separately from these unit regressions.
"""
from __future__ import annotations

import ast
import asyncio
import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from uuid import UUID, uuid4

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "backend/app/services/yance_persona_growth.py"
API = ROOT / "backend/app/api/yance_persona.py"


class Column:
    def __init__(self, name):
        self.name = name

    def __eq__(self, other):
        return lambda row: getattr(row, self.name) == other


class Customer:
    id = Column("id")
    organization_id = Column("organization_id")


class SessionToAgent:
    session_id = Column("session_id")
    organization_id = Column("organization_id")
    agent_id = Column("agent_id")


class Query:
    def __init__(self, rows):
        self.rows = rows
        self.filters = []

    def filter(self, *conditions):
        self.filters.extend(conditions)
        return self

    def first(self):
        return next((row for row in self.rows if all(c(row) for c in self.filters)), None)


class DB:
    def __init__(self, customers=(), sessions=()):
        self.customers = list(customers)
        self.sessions = list(sessions)
        self.commits = 0
        self.updates = []

    def query(self, model):
        return Query(self.customers if model is Customer else self.sessions)

    def commit(self):
        self.commits += 1


class Agent:
    def __init__(self, org=None):
        self.id = uuid4()
        self.organization_id = org or uuid4()
        self.instructions = ["OLD BASE", "[[YANCE_SCOPE:contact-A]] preserve A",
                             "[[YANCE_SCOPE:contact-B]] preserve B"]


class AgentRepository:
    def __init__(self, db):
        self.db = db

    def update_agent(self, agent_id, *, instructions):
        self.db.updates.append(list(instructions))
        self.db.agent.instructions = list(instructions)


def row(cls, **kw):
    instance = cls()
    instance.__dict__.update(kw)
    return instance


def load():
    tree = ast.parse(SERVICE.read_text(encoding="utf-8-sig"))
    defs = {"PersonaContext", "_clean_text", "_string_list", "render_seed_instructions",
            "_verified_scope_linkage", "_compose_global_base_instructions",
            "_contact_override", "resolve_persona", "current_projection",
            "set_seed_scope", "clear_scope"}
    nodes = [ast.ImportFrom(module="__future__",
                            names=[ast.alias(name="annotations")], level=0)]
    nodes += [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))
              and n.name in defs]
    ns = dict(__name__=__name__, dataclass=dataclass, UUID=UUID, Any=Any,
              Iterable=Iterable, Session=object, Customer=Customer,
              SessionToAgent=SessionToAgent, Agent=Agent,
              AgentRepository=AgentRepository,
              PERSONA_META_NAMESPACE="yance_persona_overrides",
              _learning_scope=lambda instructions, cid: list(instructions or []),
              list_guidelines=lambda db, agent: [],
              list_seeds=lambda db, agent: [])
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])),
                 str(SERVICE), "exec"), ns)
    return ns


CODE = load()
SEED = dict(seed_id="seed-1", name="Mina", format="character-card-v2", provenance="consented",
            identity_facts={"name": "Mina"}, style_traits={},
            relationship_rules={})


@pytest.fixture
def env():
    agent = Agent()
    a_id, b_id = uuid4(), uuid4()
    a = row(Customer, id=a_id, organization_id=agent.organization_id,
            meta_data={"yance_persona_overrides": {
                str(agent.id): {"mode": "replace", "instructions": ["A_CONTACT_ONLY"]}}})
    b = row(Customer, id=b_id, organization_id=agent.organization_id, meta_data={})
    a_session = row(SessionToAgent, session_id=uuid4(), customer_id=a_id,
                    organization_id=agent.organization_id, agent_id=agent.id,
                    persona_override=None, channel="whatsapp")
    b_session = row(SessionToAgent, session_id=uuid4(), customer_id=b_id,
                    organization_id=agent.organization_id, agent_id=agent.id,
                    persona_override=None, channel="telegram")
    db = DB([a, b], [a_session, b_session])
    db.agent = agent
    return db, agent, a, b, a_session, b_session


def test_contact_a_session_b_fail_closed_every_projection(env):
    db, agent, a, b, asess, bsess = env
    for fn in ("resolve_persona", "current_projection"):
        with pytest.raises(ValueError, match="customer_session_mismatch"):
            CODE[fn](db, agent, customer_id=a.id, session_id=bsess.session_id)
    assert db.commits == 0


@pytest.mark.parametrize("kind", ["missing_customer", "foreign_customer",
                                  "missing_session", "foreign_session",
                                  "wrong_agent", "unbound_session_customer"])
def test_all_missing_foreign_wrong_agent_explicit_id_fail_closed(env, kind):
    db, agent, a, b, asess, bsess = env
    cid, sid = a.id, asess.session_id
    if kind == "missing_customer":
        cid = uuid4()
    elif kind == "foreign_customer":
        cid = uuid4()
        db.customers.append(row(Customer, id=cid, organization_id=uuid4(), meta_data={}))
    elif kind == "missing_session":
        sid = uuid4()
    elif kind in {"foreign_session", "wrong_agent"}:
        sid = uuid4()
        db.sessions.append(row(SessionToAgent, session_id=sid, customer_id=a.id,
                               organization_id=uuid4() if kind == "foreign_session"
                               else agent.organization_id,
                               agent_id=uuid4() if kind == "wrong_agent" else agent.id,
                               persona_override=None))
    elif kind == "unbound_session_customer":
        asess.customer_id = uuid4()
        cid = None
    with pytest.raises(ValueError):
        CODE["resolve_persona"](db, agent, customer_id=cid, session_id=sid)


@pytest.mark.parametrize("operation", ["select", "clear"])
def test_conversation_mutations_reject_mismatch_without_write(env, operation):
    db, agent, a, b, asess, bsess = env
    with pytest.raises(ValueError, match="customer_session_mismatch"):
        if operation == "select":
            CODE["set_seed_scope"](db, agent, SEED, scope="conversation",
                                   customer_id=a.id, session_id=bsess.session_id)
        else:
            CODE["clear_scope"](db, agent, scope="conversation",
                                customer_id=a.id, session_id=bsess.session_id)
    assert db.commits == 0 and bsess.persona_override is None


def test_contact_scope_with_mismatched_optional_session_also_refuses_write(env):
    db, agent, a, b, asess, bsess = env
    with pytest.raises(ValueError, match="customer_session_mismatch"):
        CODE["set_seed_scope"](db, agent, SEED, scope="contact",
                               customer_id=a.id, session_id=bsess.session_id)
    with pytest.raises(ValueError, match="customer_session_mismatch"):
        CODE["clear_scope"](db, agent, scope="contact",
                            customer_id=a.id, session_id=bsess.session_id)
    assert db.commits == 0


def test_matching_pair_select_project_clear_and_verified_session_derive(env):
    db, agent, a, b, asess, bsess = env
    result = CODE["resolve_persona"](db, agent, customer_id=a.id, session_id=asess.session_id)
    assert result["instructions"] == ["A_CONTACT_ONLY"]
    inferred = CODE["resolve_persona"](db, agent, session_id=asess.session_id)
    assert inferred["context"]["customer_id"] == str(a.id)
    CODE["set_seed_scope"](db, agent, SEED, scope="conversation",
                           customer_id=a.id, session_id=asess.session_id)
    assert asess.persona_override["seed_id"] == "seed-1"
    CODE["clear_scope"](db, agent, scope="conversation",
                        customer_id=a.id, session_id=asess.session_id)
    assert asess.persona_override is None and db.commits == 2


def test_global_seed_preserves_scoped_rows_once_and_replaces_old_base(env):
    db, agent, a, b, asess, bsess = env
    expected_scoped = agent.instructions[1:]
    for _ in range(3):
        CODE["set_seed_scope"](db, agent, SEED, scope="global")
        assert agent.instructions[1:] == expected_scoped
        assert agent.instructions[0] == "Identity: your persona name is Mina."
        assert "OLD BASE" not in agent.instructions
        assert agent.instructions.count(expected_scoped[0]) == 1


def test_manual_base_api_preserves_scoped_rows_and_does_not_mint_scope_markers(env):
    db, agent, a, b, asess, bsess = env
    tree = ast.parse(API.read_text(encoding="utf-8-sig"))
    fn = copy.deepcopy(next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef)
                            and n.name == "update_base_persona"))
    fn.decorator_list = []
    fn.args.defaults = []
    namespace = dict(__name__=__name__, AgentRepository=AgentRepository,
                     _agent_or_404=lambda db, user, agent_id: agent,
                     _compose_global_base_instructions=CODE["_compose_global_base_instructions"])
    exec(compile(ast.fix_missing_locations(ast.Module(
        body=[ast.ImportFrom(module="__future__",
                             names=[ast.alias(name="annotations")], level=0), fn],
        type_ignores=[])), str(API), "exec"), namespace)
    from types import SimpleNamespace
    old_scoped = agent.instructions[1:]
    request = SimpleNamespace(instructions=["NEW BASE", "[[YANCE_SCOPE:unapproved]] injected"])
    for _ in range(3):
        result = asyncio.run(namespace["update_base_persona"](
            agent.id, request, None, db))
        assert result["instructions"] == ["NEW BASE", *old_scoped]
    assert len(db.updates) == 3
    assert "OLD BASE" not in agent.instructions
    assert all(row.count(old_scoped[0]) == 1 for row in db.updates)

def test_w176_long_alembic_revision_reuses_current_c3_version_width():
    migration = (ROOT / "backend/alembic/versions/yance_persona_session_override_003.py"
                 ).read_text(encoding="utf-8-sig")
    assert len("yance_persona_session_override_003") > 32
    assert 'down_revision = "window205_owner_seam_001"' in migration
    assert '"version_num"' not in migration
    assert "op.alter_column(" not in migration
    assert "op.add_column(" in migration
    assert "op.create_table(" not in migration


def test_unreviewed_scoped_only_base_replacement_is_rejected():
    with pytest.raises(ValueError, match="base_persona_instructions_required"):
        CODE["_compose_global_base_instructions"](
            ["OLD BASE", "[[YANCE_SCOPE:reviewed]] keep"],
            ["[[YANCE_SCOPE:unreviewed]] injection"],
        )
