"""Window254 production-AST safety regression.

Dependency-free tests use real production function bodies with mock DB/Socket.
This is NOT source-matching app pytest, PostgreSQL concurrency, or provider UAT.
"""
from __future__ import annotations

import ast
import asyncio
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from uuid import UUID, uuid4

BACKEND = Path(__file__).resolve().parents[1]


def load_functions(relative, names, globals_):
    source = (BACKEND / relative).read_text(encoding="utf-8")
    body = [n for n in ast.parse(source).body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
    assert {n.name for n in body} == set(names)
    exec(compile(ast.Module(body=body, type_ignores=[]), relative, "exec"), globals_)
    return globals_


class Column:
    def __eq__(self, other):
        return self


class SessionToAgent:
    session_id = Column()


class DB:
    def __init__(self, channel="web", workflow=False):
        self.session = NS(session_id=uuid4(), status="open", user_id=None,
                          channel=channel, workflow_id=uuid4() if workflow else None)
    def expire_all(self):
        pass
    def query(self, owner):
        assert owner is SessionToAgent
        return self
    def filter(self, *_):
        return self
    def first(self):
        return self.session


R = load_functions(
    "app/services/yance_reply_runtime.py",
    {"ai_auto_capability_denial", "ai_auto_authority_snapshot",
     "revalidate_ai_auto_authority"},
    {"SessionToAgent": SessionToAgent, "SessionStatus": NS(OPEN="open"),
     "Session": DB, "UUID": UUID, "Any": object},
)


@dataclass
class DeliveryResult:
    ok: bool
    reason: str | None = None


class Spy:
    def __init__(self):
        self.physical_emits = 0
        self.provider_sends = 0
    async def emit(self, *_args, **_kwargs):
        self.physical_emits += 1
    async def channel_send(self, *_args):
        self.provider_sends += 1
        return DeliveryResult(ok=True)


def delivery(db, spy, message):
    async def guarded_auto(*_args):
        return DeliveryResult(ok=False, reason="mock_authority_not_proven")
    return load_functions(
        "app/services/message_delivery.py",
        {"deliver_to_customer"},
        {"_deliver_ai_auto_web": guarded_auto,
         "WEB_CHANNEL": "web", "DeliveryResult": DeliveryResult,
         "Session": DB, "SessionToAgent": SessionToAgent,
         "_delivery_message": lambda _db, p: message,
         "_deliver_to_channel": spy.channel_send, "sio": spy},
    )["deliver_to_customer"]


class Window254FailClosed(unittest.TestCase):
    def test_01_backend_capability_matrix(self):
        for channel in ("web", "line", "slack", "telegram", "whatsapp",
                        "messenger", "instagram", "facebook"):
            with self.subTest(channel=channel):
                db = DB(channel=channel)
                denied = R["ai_auto_capability_denial"](db.session)
                if channel == "web":
                    self.assertEqual(denied, "")
                    continue  # Web positive gated by actual production owner (PG suite).
                self.assertEqual(denied, "ai_auto_channel_unavailable")
                snapshot, reason = R["ai_auto_authority_snapshot"](
                    db, db.session.session_id, 11
                )
                self.assertIsNone(snapshot)
                self.assertIn(reason, {"ai_auto_channel_unavailable", "ai_auto_receive_only"})

    def test_02_workflow_unavailable(self):
        db = DB(workflow=True)
        _, reason = R["ai_auto_authority_snapshot"](db, db.session.session_id, 11)
        self.assertEqual(reason, "ai_auto_workflow_unavailable")

    def test_03_takeover_and_non_open_fails(self):
        db = DB()
        db.session.user_id = uuid4()
        self.assertEqual(R["ai_auto_authority_snapshot"](db, db.session.session_id, 11)[1],
                         "manual_takeover")
        db.session.user_id = None
        db.session.status = "closed"
        self.assertEqual(R["ai_auto_authority_snapshot"](db, db.session.session_id, 11)[1],
                         "manual_takeover")

    def test_04_old_snapshot_cannot_reenter(self):
        db = DB()
        self.assertEqual(R["revalidate_ai_auto_authority"](
            db, db.session.session_id, {"revision": "legacy"}
        ), "ai_auto_authority_missing")

    def test_05_simulated_revision_and_route_matrix_zero_physical_send(self):
        # This is a mock-transport negative matrix, NOT a PostgreSQL race proof.
        for mutation in ("takeover", "goal", "permission", "relationship",
                         "persona", "policy", "account", "inbound", "closed",
                         "reentry", "retry", "workflow", "line", "slack"):
            with self.subTest(mutation=mutation):
                db = DB()
                spy = Spy()
                bot = NS(attributes={"yance_auto_authority":
                          {"source_message_id": 11, "revision": "old"}})
                setattr(db.session, "revision_change", mutation)
                result = asyncio.run(delivery(db, spy, bot)(
                    db, db.session,
                    {"message_id": 99, "message": "outbound", "yance_ai_auto": True}
                ))
                self.assertFalse(result.ok)
                self.assertEqual(spy.physical_emits, 0)
                self.assertEqual(spy.provider_sends, 0)

    def test_06_old_bot_without_auto_flag_cannot_bypass(self):
        db = DB()
        spy = Spy()
        bot = NS(attributes={"yance_auto_authority":
                  {"source_message_id": 11, "revision": "old"}})
        result = asyncio.run(delivery(db, spy, bot)(
            db, db.session, {"message_id": 99, "message": "outbound"}
        ))
        self.assertFalse(result.ok)
        self.assertEqual(spy.physical_emits, 0)

    def test_07_human_and_assist_paths_remain_available(self):
        for kind in ("HUMAN", "AI_ASSIST"):
            with self.subTest(kind=kind):
                db = DB()
                spy = Spy()
                human_message = NS(attributes={"client_send_action_kind": kind})
                result = asyncio.run(delivery(db, spy, human_message)(
                    db, db.session, {"message_id": 88, "message": "sent manually"}
                ))
                self.assertTrue(result.ok)
                self.assertEqual(spy.physical_emits, 1)
                self.assertEqual(spy.provider_sends, 0)

    def test_08_runtime_projection_same_denial_owner(self):
        source = (BACKEND / "app/services/yance_reply_runtime.py").read_text("utf-8")
        fn = next(n for n in ast.parse(source).body
                  if isinstance(n, ast.FunctionDef) and n.name == "runtime_projection")
        calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name)
                 and n.func.id == "ai_auto_capability_denial"]
        self.assertTrue(calls, "runtime projection must consume backend denial")
        self.assertIn('"ai_auto_available": bool(', ast.get_source_segment(source, fn))

    def test_09_direct_rest_release_cannot_bypass_capability(self):
        source = (BACKEND / "app/api/session_to_agent.py").read_text("utf-8")
        fn = next(n for n in ast.parse(source).body
                  if isinstance(n, ast.AsyncFunctionDef) and n.name == "release_chat_to_ai")
        gate = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name)
                and n.func.id == "ai_auto_capability_denial"]
        self.assertEqual(len(gate), 1)
        body = ast.get_source_segment(source, fn)
        self.assertLess(body.index("unavailable = ai_auto_capability_denial(session)"),
                        body.index("session.user_id = None"))

    def test_10_composer_reflects_capability_denial(self):
        vue = (BACKEND.parent / "frontend/src/yance/components/"
               "YanceReplyBrainRuntimeComposition.vue").read_text("utf-8")
        self.assertIn("runtime.value?.ai_auto_available", vue)
        self.assertIn("if (runtime.value?.ai_auto_available === false)", vue)
        self.assertIn(":disabled=\"runtime?.ai_auto_available === false\"", vue)

    def test_11_learning_never_conflates_provider_acceptance_and_reply(self):
        source = (BACKEND / "app/services/yance_reply_runtime.py").read_text("utf-8")
        fn = next(n for n in ast.parse(source).body
                  if isinstance(n, ast.FunctionDef) and n.name == "finalize_successful_send_learning")
        body = ast.get_source_segment(source, fn)
        self.assertIn('matched["outcome"] = "provider_accepted"', body)
        self.assertIn('"outcome": "provider_accepted"', body)
        self.assertNotIn('matched["outcome"] = "delivered"', body)

    def test_12_widget_denial_routes_inbound_to_normal_manual_inbox(self):
        """Static branch proof only; app/socket E2E remains unqualified."""
        source = (BACKEND / "app/api/widget_chat.py").read_text("utf-8")
        fn = next(n for n in ast.parse(source).body
                  if isinstance(n, ast.AsyncFunctionDef) and n.name == "handle_widget_chat")
        body = ast.get_source_segment(source, fn)
        start = body.index("ai_replies_enabled = session.get(")
        denial = body.index("else ai_auto_capability_denial(active_session)")
        fallback = body.index("ai_replies_enabled = False", denial)
        auto = body.index("elif ai_replies_enabled and active_session.status")
        manual = body.index("else:\n            chat_repo = ChatRepository(db)", auto)
        self.assertIn("not live_agent.ai_replies_enabled", body)
        self.assertLess(start, denial)
        self.assertLess(denial, fallback)
        self.assertLess(fallback, auto)
        self.assertLess(auto, manual)


if __name__ == "__main__":
    unittest.main(verbosity=2)
