"""Standalone Window177 runtime smoke for the sealed Windows private Python.

It stubs only import-time ORM owners so the pure relationship/temporal decision
functions can be exercised without installing a second project environment.
"""
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys

BACKEND = Path(__file__).resolve().parents[1]
APP = BACKEND / "app"

for name, path in {
    "app": APP,
    "app.models": APP / "models",
    "app.models.schemas": APP / "models" / "schemas",
    "app.services": APP / "services",
    "app.repositories": APP / "repositories",
}.items():
    module = ModuleType(name)
    module.__path__ = [str(path)]
    sys.modules[name] = module

def stub_module(name, **values):
    module = ModuleType(name)
    for key, value in values.items():
        setattr(module, key, value)
    sys.modules[name] = module

class Placeholder:
    pass

stub_module("app.models.chat_history", ChatHistory=Placeholder)
stub_module("app.models.customer", Customer=Placeholder)
stub_module("app.models.organization", Organization=Placeholder)
stub_module("app.models.session_to_agent", SessionToAgent=Placeholder)
stub_module("app.models.schemas.people", project_person_profile=lambda _: None)
stub_module("app.repositories.people", PeopleRepository=Placeholder)

from app.models.schemas.relationship import (
    GoalProjection,
    RelationshipMemoryEntry,
    RelationshipMetrics,
    TemporalProjection,
)
from app.services.relationship_context import _decision, _metrics, _temporal_projection


def check(condition, label):
    if not condition:
        raise AssertionError(label)
    print(f"PASS {label}")


unknown = _temporal_projection(
    SimpleNamespace(meta_data={}),
    SimpleNamespace(timezone="Europe/Berlin"),
    now=datetime(2026, 10, 7, 20, 0, tzinfo=timezone.utc),
)
check(unknown.contact_timezone is None, "TM02 unknown contact timezone remains unknown")
check(not unknown.defer_recommended, "TM05 operator fallback never fabricates defer")

explicit = _temporal_projection(
    SimpleNamespace(meta_data={
        "relationship_memory": {
            "version": 1,
            "entries": [],
            "temporal": {
                "contact_timezone": "Europe/Berlin",
                "preferred_contact_start": "08:00",
                "preferred_contact_end": "18:00",
            },
        },
    }),
    SimpleNamespace(timezone="Asia/Phnom_Penh"),
    now=datetime(2026, 10, 7, 20, 0, tzinfo=timezone.utc),
)
check(explicit.contact_timezone_known, "TM02 explicit contact timezone accepted")
check(explicit.daypart == "evening", "TM03 contact daypart projected")
check(explicit.defer_recommended, "TM05 explicit outside-window defer projected")

messages = [
    SimpleNamespace(
        created_at=datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc),
        message_type="agent",
        sentiment_score=0.1,
    ),
    SimpleNamespace(
        created_at=datetime(2026, 10, 7, 10, 0, tzinfo=timezone.utc),
        message_type="user",
        sentiment_score=0.3,
    ),
]
metrics = _metrics(messages, [SimpleNamespace()], [], datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc))
check(metrics.stage == "new", "R01 stage derived from canonical activity")
check(metrics.momentum == "steady", "R02 momentum derived from recency")
check(metrics.temperature == "neutral", "R09 temperature derived from available sentiment")
check(metrics.last_inbound_at > metrics.last_outbound_at, "R08 inbound/outbound ordering retained")

boundary = RelationshipMemoryEntry(
    id="boundary-1",
    kind="boundary",
    text="Do not send tonight",
    effect="no_reply",
    created_at=datetime(2026, 10, 7, tzinfo=timezone.utc),
    updated_at=datetime(2026, 10, 7, tzinfo=timezone.utc),
)
neutral_time = TemporalProjection(
    operator_timezone="UTC",
    contact_timezone=None,
    contact_timezone_known=False,
    effective_timezone="UTC",
    precision="operator_fallback",
    local_time=datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc),
    daypart="afternoon",
)
decision = _decision(
    RelationshipMetrics(
        stage="developing",
        momentum="steady",
        temperature="neutral",
        risk="watch",
        message_count=8,
        session_count=1,
        active_days=3,
        basis=[],
    ),
    neutral_time,
    [boundary],
    GoalProjection(current="Continue conversation"),
)
check(decision.action == "no_reply", "R07 confirmed boundary overrides Goal with no_reply")

defer_decision = _decision(
    RelationshipMetrics(
        stage="developing",
        momentum="steady",
        temperature="neutral",
        risk="low",
        message_count=8,
        session_count=1,
        active_days=3,
        basis=[],
    ),
    explicit,
    [],
    GoalProjection(current="Continue conversation"),
)
check(defer_decision.action == "defer", "TM05 confirmed contact window produces defer")
check(defer_decision.defer_until is not None, "TM05 defer carries a concrete next eligible time")

reply_decision = _decision(
    metrics,
    neutral_time,
    [],
    GoalProjection(current="Continue conversation"),
)
check(reply_decision.action == "reply", "R08 latest inbound canonical message produces reply")

goal_decision = _decision(
    RelationshipMetrics(
        stage="developing",
        momentum="steady",
        temperature="neutral",
        risk="low",
        message_count=8,
        session_count=1,
        active_days=3,
        basis=[],
    ),
    neutral_time,
    [],
    GoalProjection(current="Follow up the open topic", long_term="Maintain continuity"),
)
check(goal_decision.action == "next_action", "R08 current Goal seam projects next action")
check("current goal" in goal_decision.next_best_action.lower(), "R08 why-now consumes current Goal without storing it")

long_term_decision = _decision(
    RelationshipMetrics(
        stage="established",
        momentum="steady",
        temperature="warm",
        risk="low",
        message_count=24,
        session_count=3,
        active_days=9,
        basis=[],
    ),
    neutral_time,
    [],
    GoalProjection(long_term="Maintain long-term continuity"),
)
check(long_term_decision.action == "next_action", "R08 long-term Goal seam projects next action")
check("long-term goal" in long_term_decision.next_best_action.lower(), "R08 long-term Goal is consumed without durable storage")

print("PASS_WINDOW177_RUNTIME_SMOKE")
