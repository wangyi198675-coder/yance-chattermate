"""W302 real local Socket.IO receiver with PostgreSQL persisted ChatHistory replay.

No external provider UAT. Run against disposable PG16.15 W294_PG_URL.
"""
from __future__ import annotations

import ast
import asyncio
import logging
import socket
import sys
import uuid
import threading
import time
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text
import socketio
import uvicorn

import test_window294_reply_commitment_pg as w294


class PersistedChatRepo:
    def __init__(self, db):
        self.db = db

    def update_message_attributes(self, mid, updates):
        row = self.db.get(w294.ChatHistory, mid)
        row.attributes = {**(row.attributes or {}), **updates}
        self.db.commit()

    def mark_delivery_failed(self, mid, reason):
        row = self.db.get(w294.ChatHistory, mid)
        row.attributes = {**(row.attributes or {}), "delivery_status": reason}
        self.db.commit()


def install_actual_canonical_execution_guard():
    """W321: use the actual production guard in this minimal PG test seam.

    W302 compiles real message_delivery functions while injecting a reduced
    ChatRepository fixture. The W321 production recovery now legitimately
    calls client_send_execution_guard; import its exact AST rather than
    inventing a fake/no-op lock or relaxing old delivery assertions.
    """
    import textwrap
    from contextlib import asynccontextmanager
    from concurrent.futures import ThreadPoolExecutor
    from weakref import WeakValueDictionary

    source = (Path(__file__).resolve().parents[1]
              / "app/repositories/chat.py").read_text(encoding="utf-8")
    owner = next(item for item in ast.parse(source).body
                 if isinstance(item, ast.ClassDef) and item.name == "ChatRepository")
    guard = next(item for item in owner.body
                 if isinstance(item, ast.AsyncFunctionDef)
                 and item.name == "client_send_execution_guard")
    ns = {
        "asynccontextmanager": asynccontextmanager,
        "ThreadPoolExecutor": ThreadPoolExecutor,
        "WeakValueDictionary": WeakValueDictionary,
        "asyncio": asyncio,
        "text": text,
        "_sqlite_client_send_locks": WeakValueDictionary(),
    }
    exec("from __future__ import annotations\nclass _NativeGuard:\n"
         + textwrap.indent(ast.unparse(guard), "    "), ns)
    PersistedChatRepo.client_send_execution_guard = (
        ns["_NativeGuard"].client_send_execution_guard
    )


install_actual_canonical_execution_guard()


def actual_delivery_namespace(socket_server, sessions):
    """Compile ACTUAL production delivery functions; inject only app infrastructure."""
    source = (Path(__file__).resolve().parents[1]
              / "app/services/message_delivery.py").read_text(encoding="utf-8")
    wanted = {"deliver_to_customer", "_delivery_message",
              "_persist_delivery_attempt", "recover_pending_web_auto_messages"}
    nodes = [node for node in ast.parse(source).body
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
             and node.name in wanted]
    assert len(nodes) == len(wanted), set(wanted) - {node.name for node in nodes}
    def result(ok, reason=None, **kwargs):
        return types.SimpleNamespace(ok=ok, reason=reason, **kwargs)
    ns = {
        "WEB_CHANNEL": "web", "SessionLocal": sessions,
        "revalidate_auto_send": w294.gate.revalidate_auto_send,
        "ChatRepository": PersistedChatRepo, "DeliveryResult": result,
        "sio": socket_server, "ChatHistory": w294.ChatHistory,
        "datetime": datetime, "timezone": timezone,
        "logger": logging.getLogger("w302-web-socket"),
    }
    exec("from __future__ import annotations\n" +
         "\n\n".join(ast.unparse(node) for node in nodes), ns)
    return ns


class Window302RealSocketPostgresProof(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        w294.Window294PostgreSQLProof.setUpClass()
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            cls.port = s.getsockname()[1]
        cls.sio = socketio.AsyncServer(async_mode="asgi", logger=False,
                                       engineio_logger=False)
        @cls.sio.event(namespace="/widget")
        async def connect(sid, environ, auth=None):
            await cls.sio.enter_room(sid, cls.room, namespace="/widget")
        cls.server = uvicorn.Server(uvicorn.Config(
            socketio.ASGIApp(cls.sio), host="127.0.0.1", port=cls.port,
            log_level="error", lifespan="off"))
        cls.server_thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.room = "unbound"
        cls.server_thread.start()
        for _ in range(100):
            if cls.server.started:
                break
            time.sleep(0.05)
        if not cls.server.started:
            raise RuntimeError("real local ASGI Socket.IO receiver did not start")

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.server_thread.join(timeout=5)
        assert not cls.server_thread.is_alive(), "Socket.IO test server not stopped"
        w294.Window294PostgreSQLProof.tearDownClass()

    def setUp(self):
        self.fixture = w294.Window294PostgreSQLProof(
            methodName="test_single_send_and_retry_reentry_idempotence")
        self.fixture.setUp()
        self.room = str(self.fixture.session_id)
        # Socket.IO connect handler is only allowed after room assignment.
        type(self).room = self.room
        self.visible = {}
        self.notice_calls = []
        self.foreign_groups = []
        self.all_events = []
        self.allow_ack = True
        self.received_session_statuses = []
        self.client = socketio.Client(reconnection=False, logger=False,
                                      engineio_logger=False)
        @self.client.on("chat_response", namespace="/widget")
        def receive(payload):
            assert isinstance(payload.get("message_id"), int)
            mid = payload["message_id"]
            self.all_events.append(mid)
            self.visible.setdefault(mid, payload)
            if not self.allow_ack:
                return None  # physically received but ACK deliberately missing
            return {"message_id": mid, "accepted": True}
        self.client.connect(f"http://127.0.0.1:{self.port}",
                            namespaces=["/widget"], transports=["websocket"],
                            wait_timeout=5)
        self.ns = actual_delivery_namespace(self.sio, self.fixture.make_session)

    def tearDown(self):
        self.client.disconnect()
        if self.foreign_groups:
            with self.fixture.make_session() as db:
                for org_id, gid, uid in reversed(self.foreign_groups):
                    db.execute(w294.agent_usergroup.delete().where(
                        w294.agent_usergroup.c.group_id == gid))
                    db.execute(w294.user_groups.delete().where(
                        w294.user_groups.c.user_id == uid))
                    db.query(w294.User).filter(w294.User.id == uid).delete()
                    db.query(w294.UserGroup).filter(w294.UserGroup.id == gid).delete()
                    db.query(w294.Organization).filter(w294.Organization.id == org_id).delete()
                db.commit()
        self.fixture.tearDown()

    def send(self, *, authority=None, bot_id=None, text="Hello", db=None):
        fixture = self.fixture
        record = types.SimpleNamespace(session_id=fixture.session_id, channel="web")
        payload = {
            "message_id": bot_id or fixture.bot_id,
            "message": text,
            "session_id": str(fixture.session_id),
            "type": "chat_response",
            "_ai_auto_authority": authority or fixture.snapshot,
        }
        async def do_send(current_db):
            return await self.ns["deliver_to_customer"](current_db, record, payload)
        if db is not None:
            return asyncio.run(do_send(db))
        with fixture.make_session() as own_db:
            return asyncio.run(do_send(own_db))

    def persisted(self, mid=None):
        with self.fixture.make_session() as db:
            bot = db.get(w294.ChatHistory, mid or self.fixture.bot_id)
            return (bot.attributes or {}).get("provider_delivery", {}).get("state")

    def precommit(self):
        with self.fixture.make_session() as db:
            row = db.get(w294.ChatHistory, self.fixture.bot_id)
            row.attributes = {
                "ai_auto_pending": True,
                "provider_delivery": {"channel": "web", "state": "sending"},
                "ai_auto_authority": self.fixture.snapshot,
            }
            db.commit()

    def test_a_precommit_before_socket_then_recover_same_id(self):
        self.precommit()
        self.assertEqual(self.visible, {})
        record = types.SimpleNamespace(session_id=self.fixture.session_id, channel="web")
        with self.fixture.make_session() as db:
            recovered = asyncio.run(self.ns["recover_pending_web_auto_messages"](db, record))
        self.assertEqual(recovered, 1)
        self.assertEqual(list(self.visible), [self.fixture.bot_id])
        self.assertEqual(self.persisted(), "succeeded")

    def test_b_receiver_acked_but_durable_success_crashed_then_replay(self):
        persist = self.ns["_persist_delivery_attempt"]
        crash = {"done": False}
        def crash_at_success(db, bot, channel, state, receipts, *args, **kwargs):
            if state == "succeeded" and not crash["done"]:
                crash["done"] = True
                raise RuntimeError("W302_INJECTED_POST_ACK_PRE_SUCCESS_CRASH")
            return persist(db, bot, channel, state, receipts, *args, **kwargs)
        self.ns["_persist_delivery_attempt"] = crash_at_success
        with self.assertRaisesRegex(RuntimeError, "INJECTED_POST_ACK_PRE_SUCCESS"):
            self.send()
        self.assertEqual(list(self.visible), [self.fixture.bot_id])
        self.assertEqual(self.persisted(), "sending")
        self.ns["_persist_delivery_attempt"] = persist
        self.assertTrue(self.send().ok)
        self.assertEqual(list(self.visible), [self.fixture.bot_id])
        self.assertEqual(self.persisted(), "succeeded")
        self.assertEqual(self.all_events.count(self.fixture.bot_id), 2)

    def test_c_succeeded_retry_does_not_push_second_visible(self):
        self.assertTrue(self.send().ok)
        duplicate = self.send()
        self.assertFalse(duplicate.ok)
        self.assertEqual(duplicate.reason, "auto_send_already_committed")
        self.assertEqual(list(self.visible), [self.fixture.bot_id])
        self.assertEqual(self.persisted(), "succeeded")

    def test_d_same_text_different_canonical_ids_visible_two(self):
        self.assertTrue(self.send().ok)
        fx = self.fixture
        with fx.make_session() as db:
            inbound = w294.ChatHistory(session_id=fx.session_id,
                organization_id=fx.org, agent_id=fx.agent_id,
                message="Different turn", message_type="user", attributes={})
            db.add(inbound); db.commit()
            bot = w294.ChatHistory(session_id=fx.session_id,
                organization_id=fx.org, agent_id=fx.agent_id,
                message="Hello", message_type="bot", attributes={})
            db.add(bot); db.commit()
            authority = w294.gate.build_auto_send_authority(
                db, db.get(w294.SessionToAgent, fx.session_id),
                organization_id=fx.org, agent_id=fx.agent_id,
                source_message_id=inbound.id, bot_message_id=bot.id)
            next_id = bot.id
        self.assertTrue(self.send(authority=authority, bot_id=next_id).ok)
        self.assertEqual(set(self.visible), {fx.bot_id, next_id})
        self.assertEqual(len(self.visible), 2)

    def test_e_same_bot_id_two_reentries_receiver_only_once(self):
        self.assertTrue(self.send().ok)
        self.send()
        self.assertEqual(list(self.visible), [self.fixture.bot_id])
        self.assertEqual(self.persisted(), "succeeded")

    def test_f_authority_revoked_before_commit_visible_zero(self):
        self.fixture.invalidate("takeover")
        result = self.send()
        self.assertFalse(result.ok)
        self.assertEqual(len(self.visible), 0)

    def test_workflow_snapshot_denials_and_valid_once(self):
        fx = self.fixture
        # The real workflow helper is dynamically compiled, with actual final
        # gate/delivery and PostgreSQL rows; workflow orchestration is separate.
        source = (Path(__file__).resolve().parents[1]
                  / "app/services/workflow_chat.py").read_text(encoding="utf-8")
        node = next(n for n in ast.parse(source).body
                    if isinstance(n, ast.AsyncFunctionDef)
                    and n.name == "deliver_workflow_auto_message")
        class Repo(PersistedChatRepo):
            def create_message(self, values):
                msg = w294.ChatHistory(**{k: v for k,v in values.items()
                    if k in {"message", "message_type", "session_id",
                             "organization_id", "agent_id", "attributes"}})
                self.db.add(msg); self.db.commit()
                return msg
        ns = {
            "ChatRepository": Repo,
            "build_auto_send_authority": w294.gate.build_auto_send_authority,
            "deliver_to_customer": self.ns["deliver_to_customer"],
            "logger": logging.getLogger("w302-workflow"),
        }
        exec("from __future__ import annotations\n" + ast.unparse(node), ns)
        helper = ns["deliver_workflow_auto_message"]
        record = types.SimpleNamespace(session_id=fx.session_id,
            channel="web", organization_id=fx.org, agent_id=fx.agent_id)
        with fx.make_session() as db:
            gen = w294.gate.context_revision(
                db, db.get(w294.SessionToAgent, fx.session_id))
        for label in ("takeover", "disabled", "closed", "new_inbound", "revision"):
            with self.subTest(label=label):
                with fx.make_session() as db:
                    before = len(self.visible)
                    fx.invalidate(label)
                    result = asyncio.run(helper(db, record,
                        session_id=str(fx.session_id), org_id=str(fx.org),
                        agent_id=str(fx.agent_id), customer_id=None,
                        message=f"Workflow {label}",
                        source_message_id=fx.source_id,
                        generation_revision=gen))
                    self.assertFalse(result.ok)
                    self.assertEqual(len(self.visible), before)
                    # Each rejected bot intent remains non-visible and is
                    # removed in this isolated fixture to reset revision.
                    db.query(w294.ChatHistory).filter(
                        w294.ChatHistory.session_id == fx.session_id,
                        w294.ChatHistory.id > fx.bot_id).delete()
                    session = db.get(w294.SessionToAgent, fx.session_id)
                    session.status = "open"; session.user_id = None
                    session.updated_at = datetime.fromisoformat(gen.split(":",3)[2])
                    db.get(w294.Agent, fx.agent_id).ai_replies_enabled = True
                    db.commit()
        # After revocations, a new inference must bind to a newly read
        # canonical relationship/turn revision; never reuse stale generation.
        with fx.make_session() as db:
            new_generation_revision = w294.gate.context_revision(
                db, db.get(w294.SessionToAgent, fx.session_id))
            good = asyncio.run(helper(db, record,
                session_id=str(fx.session_id), org_id=str(fx.org),
                agent_id=str(fx.agent_id), customer_id=None,
                message="Workflow approved",
                source_message_id=fx.source_id,
                generation_revision=new_generation_revision))
        self.assertTrue(good.ok, f"workflow should deliver after reset: {good.reason}")
        self.assertEqual(len(self.visible), 1)

    def test_two_workers_race_same_bot_id_receiver_once(self):
        barrier = threading.Barrier(2)
        outcomes = []
        errors = []
        lock = threading.Lock()
        def worker():
            try:
                barrier.wait(timeout=3)
                result = self.send()
                with lock:
                    outcomes.append(result.ok)
            except BaseException as exc:
                with lock:
                    errors.append(repr(exc))
        threads = [threading.Thread(target=worker, daemon=True) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        self.assertFalse(any(thread.is_alive() for thread in threads), "two-worker Web lock hang")
        self.assertFalse(errors, errors)
        self.assertEqual(sorted(outcomes), [False, True])
        self.assertEqual(list(self.visible), [self.fixture.bot_id])
        self.assertEqual(self.persisted(), "succeeded")

    def test_workflow_two_machine_messages_keep_exact_generation_revisions(self):
        fx = self.fixture
        source = (Path(__file__).resolve().parents[1] /
                  "app/services/workflow_chat.py").read_text(encoding="utf-8")
        node = next(n for n in ast.parse(source).body
                    if isinstance(n, ast.AsyncFunctionDef)
                    and n.name == "deliver_workflow_auto_message")
        class Repo(PersistedChatRepo):
            def create_message(self, values):
                bot = w294.ChatHistory(**{k: v for k, v in values.items() if
                    k in {"message", "message_type", "session_id",
                          "organization_id", "agent_id", "attributes"}})
                self.db.add(bot); self.db.commit()
                return bot
        ns = {"ChatRepository": Repo, "build_auto_send_authority":
              w294.gate.build_auto_send_authority,
              "deliver_to_customer": self.ns["deliver_to_customer"],
              "logger": logging.getLogger("w302-workflow")}
        exec("from __future__ import annotations\n" + ast.unparse(node), ns)
        helper = ns["deliver_workflow_auto_message"]
        record = types.SimpleNamespace(session_id=fx.session_id,
            channel="web", organization_id=fx.org, agent_id=fx.agent_id)
        with fx.make_session() as db:
            for name in ("Intermediate 1", "Final 2"):
                revision = w294.gate.context_revision(
                    db, db.get(w294.SessionToAgent, fx.session_id))
                delivered = asyncio.run(helper(db, record,
                    session_id=str(fx.session_id), org_id=str(fx.org),
                    agent_id=str(fx.agent_id), customer_id=None,
                    message=name, source_message_id=fx.source_id,
                    generation_revision=revision))
                self.assertTrue(delivered.ok, name)
        self.assertEqual(len(self.visible), 2)
        self.assertEqual({item["message"] for item in self.visible.values()},
                         {"Intermediate 1", "Final 2"})

    def test_workflow_internal_updated_at_only_revision_reconcile(self):
        fx = self.fixture
        with fx.make_session() as db:
            session = db.get(w294.SessionToAgent, fx.session_id)
            revision_before = w294.gate.context_revision(db, session)
            session.updated_at = datetime(2027, 1, 1, tzinfo=timezone.utc)
            db.commit()
            revised = w294.gate.reconcile_workflow_own_revision(
                db, session, revision_before)
            self.assertNotEqual(revised, revision_before)
            self.assertEqual(revised, w294.gate.context_revision(db, session))
            # An intervening inbound cannot be disguised as a workflow update.
            db.add(w294.ChatHistory(
                session_id=fx.session_id, organization_id=fx.org,
                agent_id=fx.agent_id, message_type="user",
                message="late inbound", attributes={}))
            db.commit()
            self.assertEqual(w294.gate.reconcile_workflow_own_revision(
                db, session, revised), revised)


    def workflow_continuation_ns(self):
        """Compile real production workflow helper and continuation, not replicas."""
        source = (Path(__file__).resolve().parents[1] /
                  "app/services/workflow_chat.py").read_text(encoding="utf-8")
        names = {"deliver_workflow_auto_message", "resume_deferred_workflow_messages"}
        nodes = [n for n in ast.parse(source).body
                 if isinstance(n, ast.AsyncFunctionDef) and n.name in names]
        self.assertEqual({n.name for n in nodes}, names)
        class Repo(PersistedChatRepo):
            def create_message(self, values):
                row = w294.ChatHistory(**{k: v for k, v in values.items()
                    if k in {"message", "message_type", "session_id",
                             "organization_id", "agent_id", "attributes"}})
                self.db.add(row); self.db.commit()
                return row
        class SessionRepo:
            def __init__(self, db): self.db = db
            def close_session(self, sid, reason=None, description=None):
                row = self.db.get(w294.SessionToAgent, sid)
                row.status = "closed"
                self.db.commit()
        class WorkflowStub:
            def __init__(self, db): self.session_repo = SessionRepo(db)
        ns = {
            "ChatRepository": Repo, "ChatHistory": w294.ChatHistory,
            "SessionStatus": w294.SessionStatus, "WorkflowChatService": WorkflowStub,
            "build_auto_send_authority": w294.gate.build_auto_send_authority,
            "context_revision": w294.gate.context_revision,
            "deliver_to_customer": self.ns["deliver_to_customer"],
            "apply_pending_workflow_terminal_control":
                self.terminal_ns()["apply_pending_workflow_terminal_control"],
            "logger": logging.getLogger("w302-f03"),
        }
        exec("from __future__ import annotations\n" +
             "\n\n".join(ast.unparse(n) for n in nodes), ns)
        return ns

    def set_deferred_final(self):
        self.precommit()
        with self.fixture.make_session() as db:
            bot = db.get(w294.ChatHistory, self.fixture.bot_id)
            bot.attributes = {**bot.attributes,
                "workflow_deferred_tail": [{"kind": "final",
                     "message": "Final after intermediate",
                     "end_chat": True, "request_rating": False,
                     "transfer_to_human": False}]}
            db.commit()

    def test_t1_transfer_chat_gated_canonical_once_control_once(self):
        fx = self.fixture
        record = types.SimpleNamespace(session_id=fx.session_id, channel="web")
        with fx.make_session() as db:
            payload = {"message_id": fx.bot_id, "message": "Hello",
                       "session_id": str(fx.session_id), "type": "chat_response",
                       "transfer_to_human": True,
                       "_ai_auto_authority": fx.snapshot}
            gate = asyncio.run(self.ns["deliver_to_customer"](db, record, payload))
        self.assertTrue(gate.ok)
        self.assertEqual(list(self.visible), [fx.bot_id])
        self.assertTrue(self.visible[fx.bot_id]["transfer_to_human"])
        # Human transfer is ONE CONTROL action only after gated delivery.
        control = []
        if gate.ok: control.append("human_transfer")
        self.assertEqual(control, ["human_transfer"])
        with fx.make_session() as db:
            bots = db.query(w294.ChatHistory).filter(
                w294.ChatHistory.session_id == fx.session_id,
                w294.ChatHistory.message_type == "bot").all()
        self.assertEqual(len(bots), 1)
        src = (Path(__file__).resolve().parents[1] /
               "app/api/widget_chat.py").read_text(encoding="utf-8")
        self.assertNotIn("if response.transfer_to_human and hasattr(response, '_is_transfer_response'):", src)
        self.assertIn("apply_pending_workflow_terminal_control(", src)

    def test_t2_transfer_revoke_takeover_no_visible_chat_or_control(self):
        self.fixture.invalidate("takeover")
        result = self.send()
        self.assertFalse(result.ok)
        self.assertEqual(self.visible, {})
        self.assertEqual(result.reason, "auto_send_human_takeover")

    def test_t3_end_chat_final_gated_before_own_close(self):
        fx = self.fixture
        with fx.make_session() as db:
            self.assertEqual(db.get(w294.SessionToAgent, fx.session_id).status, "open")
        self.assertTrue(self.send().ok)
        self.assertEqual(list(self.visible), [fx.bot_id])
        with fx.make_session() as db:
            row = db.get(w294.SessionToAgent, fx.session_id)
            self.assertEqual(row.status, "open")
            row.status = "closed"  # existing widget own-close happens AFTER gate
            db.commit()
        self.assertEqual(self.persisted(), "succeeded")
        src = (Path(__file__).resolve().parents[1] /
               "app/api/widget_chat.py").read_text(encoding="utf-8")
        self.assertLess(src.index("auto_delivery = await deliver_to_customer"),
                        src.index("if response.end_chat and not ("))

    def test_t4_externally_closed_final_visible_zero(self):
        self.fixture.invalidate("closed")
        result = self.send()
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "auto_send_session_not_open")
        self.assertEqual(self.visible, {})

    def test_t5_intermediate_no_ack_reconnect_final_both_once(self):
        self.set_deferred_final()
        self.allow_ack = False
        sent = self.send()
        self.assertFalse(sent.ok)
        self.assertEqual(sent.reason, "web_receiver_ack_missing")
        self.assertEqual(self.persisted(), "sending")
        with self.fixture.make_session() as db:
            rows = db.query(w294.ChatHistory).filter(
                w294.ChatHistory.session_id == self.fixture.session_id,
                w294.ChatHistory.message_type == "bot").all()
            self.assertEqual(len(rows), 1, "final may not poison intermediate revision")
        self.client.disconnect()
        self.allow_ack = True
        self.client.connect(f"http://127.0.0.1:{self.port}",
                            namespaces=["/widget"], transports=["websocket"], wait_timeout=5)
        record = types.SimpleNamespace(session_id=self.fixture.session_id, channel="web")
        ns = self.workflow_continuation_ns()
        with self.fixture.make_session() as db:
            self.assertEqual(asyncio.run(
                self.ns["recover_pending_web_auto_messages"](db, record)), 1)
            session = db.get(w294.SessionToAgent, self.fixture.session_id)
            self.assertEqual(asyncio.run(ns["resume_deferred_workflow_messages"](db, session)), 1)
            self.assertEqual(asyncio.run(ns["resume_deferred_workflow_messages"](db, session)), 0)
            bots = db.query(w294.ChatHistory).filter(
                w294.ChatHistory.session_id == self.fixture.session_id,
                w294.ChatHistory.message_type == "bot").all()
            self.assertEqual(len(bots), 2)
            self.assertEqual(session.status, "closed")
            self.assertEqual({(b.attributes or {}).get("provider_delivery", {}).get("state")
                              for b in bots}, {"succeeded"})
        self.assertEqual(len(self.visible), 2)
        self.assertEqual(set(item["message"] for item in self.visible.values()),
                         {"Hello", "Final after intermediate"})
        self.assertEqual(len(set(self.all_events)), 2)
        self.assertEqual(len(self.all_events) - len(set(self.all_events)), 1,
                         "one physical retry permitted, duplicate visible IDs zero")

    def test_t6_no_ack_new_inbound_old_generation_fail_closed(self):
        self.client.disconnect()
        self.set_deferred_final()
        sent = self.send()
        self.assertFalse(sent.ok)
        self.assertEqual(self.persisted(), "sending")
        fx = self.fixture
        with fx.make_session() as db:
            db.add(w294.ChatHistory(session_id=fx.session_id,
                organization_id=fx.org, agent_id=fx.agent_id,
                message="New inbound", message_type="user", attributes={}))
            db.commit()
        self.client.connect(f"http://127.0.0.1:{self.port}",
                            namespaces=["/widget"], transports=["websocket"], wait_timeout=5)
        record = types.SimpleNamespace(session_id=fx.session_id, channel="web")
        ns = self.workflow_continuation_ns()
        with fx.make_session() as db:
            self.assertEqual(asyncio.run(
                self.ns["recover_pending_web_auto_messages"](db, record)), 0)
            self.assertEqual(asyncio.run(ns["resume_deferred_workflow_messages"](
                db, db.get(w294.SessionToAgent, fx.session_id))), 0)
            bots = db.query(w294.ChatHistory).filter(
                w294.ChatHistory.session_id == fx.session_id,
                w294.ChatHistory.message_type == "bot").all()
            self.assertEqual(len(bots), 1)
        self.assertEqual(self.visible, {})

    def test_t7_normal_successful_final_reconnect_does_not_duplicate(self):
        """ACKed predecessor with an already persisted child is not re-created."""
        self.set_deferred_final()
        fx = self.fixture
        self.assertTrue(self.send().ok)
        ns = self.workflow_continuation_ns()
        record = types.SimpleNamespace(session_id=fx.session_id, channel="web",
                                       organization_id=fx.org, agent_id=fx.agent_id)
        with fx.make_session() as db:
            generation = w294.gate.context_revision(
                db, db.get(w294.SessionToAgent, fx.session_id))
            result = asyncio.run(ns["deliver_workflow_auto_message"](
                db, record, session_id=str(fx.session_id), org_id=fx.org,
                agent_id=fx.agent_id, customer_id=None,
                message="Final after intermediate",
                source_message_id=fx.source_id, generation_revision=generation,
                attributes={"workflow_execution": True,
                            "workflow_continuation_from": fx.bot_id}))
            self.assertTrue(result.ok)
            session = db.get(w294.SessionToAgent, fx.session_id)
            self.assertEqual(asyncio.run(
                ns["resume_deferred_workflow_messages"](db, session)), 0)
            bots = db.query(w294.ChatHistory).filter(
                w294.ChatHistory.session_id == fx.session_id,
                w294.ChatHistory.message_type == "bot").all()
            self.assertEqual(len(bots), 2)
            self.assertTrue(all((b.attributes or {}).get("provider_delivery", {})
                                .get("state") == "succeeded" for b in bots))
        self.assertEqual(len(self.visible), 2)
        self.assertEqual(len(self.all_events), 2)

    def test_t8_final_intent_crash_before_precommit_recovers_same_id(self):
        """Crash between final ChatHistory insert and sending precommit is recoverable."""
        self.set_deferred_final()
        fx = self.fixture
        self.assertTrue(self.send().ok)
        ns = self.workflow_continuation_ns()
        with fx.make_session() as db:
            child = w294.ChatHistory(session_id=fx.session_id,
                organization_id=fx.org, agent_id=fx.agent_id,
                message="Final after intermediate", message_type="bot",
                attributes={"ai_auto_pending": True,
                            "workflow_continuation_from": fx.bot_id,
                            "workflow_execution": True})
            db.add(child); db.commit()
            child_id = child.id
            record = db.get(w294.SessionToAgent, fx.session_id)
            self.assertEqual(asyncio.run(
                ns["resume_deferred_workflow_messages"](db, record)), 1)
            bots = db.query(w294.ChatHistory).filter(
                w294.ChatHistory.session_id == fx.session_id,
                w294.ChatHistory.message_type == "bot").all()
            self.assertEqual(len(bots), 2)
            self.assertEqual({b.id for b in bots}, {fx.bot_id, child_id})
            self.assertTrue(all((b.attributes or {}).get("provider_delivery", {})
                                .get("state") == "succeeded" for b in bots))
        self.assertEqual(set(self.visible), {fx.bot_id, child_id})


    def terminal_ns(self):
        """Execute actual production terminal and direct store methods against PG."""
        from uuid import UUID
        source = (Path(__file__).resolve().parents[1]
                  / "app/services/workflow_chat.py").read_text(encoding="utf-8")
        parsed = ast.parse(source)
        names = {"workflow_terminal_intent", "workflow_transfer_spec",
                 "apply_pending_workflow_terminal_control",
                 "resume_pending_workflow_terminal_controls"}
        nodes = [n for n in parsed.body if isinstance(n, (ast.FunctionDef,
                 ast.AsyncFunctionDef)) and n.name in names]
        self.assertEqual({n.name for n in nodes}, names)
        cls = next(n for n in parsed.body if isinstance(n, ast.ClassDef)
                   and n.name == "WorkflowChatService")
        store = next(n for n in cls.body if isinstance(n, ast.FunctionDef)
                     and n.name == "_store_workflow_response")
        nodes.append(store)
        # The production source is AST-executed without changing its tenant
        # query or notification import. Inject PG-backed fixture table owners.
        sys.modules.setdefault("app.models.user", types.ModuleType("app.models.user"))
        sys.modules["app.models.user"].UserGroup = w294.UserGroup
        sys.modules["app.models.user"].User = w294.User
        sys.modules["app.models.user"].user_groups = w294.user_groups
        sys.modules.setdefault("app.services", types.ModuleType("app.services"))
        notifications = types.ModuleType("app.services.notifications")
        async def record_notice(*, db, user_ids, event, title, message, metadata):
            self.notice_calls.append({"users": set(user_ids),
                 "session_id": metadata.get("session_id"), "title": title})
        notifications.notify_chat_event = record_notice
        notifications.ChatNotificationEvent = types.SimpleNamespace(
            CHAT_TRANSFER="CHAT_TRANSFER")
        sys.modules["app.services.notifications"] = notifications
        ns = {
            "SessionLocal": self.fixture.make_session,
            "ChatHistory": w294.ChatHistory,
            "SessionToAgent": w294.SessionToAgent,
            "SessionStatus": w294.SessionStatus,
            "Agent": w294.Agent, "UserGroup": w294.UserGroup, "UUID": UUID,
            "datetime": datetime, "timezone": timezone,
            "revalidate_auto_send": w294.gate.revalidate_auto_send,
            "build_auto_send_authority": w294.gate.build_auto_send_authority,
            "logger": logging.getLogger("w302-terminal-physical"),
        }
        exec("from __future__ import annotations\n" +
             "\n\n".join(ast.unparse(n) for n in nodes), ns)
        return ns

    def set_direct_terminal(self, kind, *, target=None):
        """Persist the real production terminal intent on canonical ChatHistory."""
        ns = self.terminal_ns()
        fx = self.fixture
        obj = types.SimpleNamespace(
            transfer_to_human=kind == "transfer",
            end_chat=kind == "end_chat",
            message="Hello", transfer_reason="KNOWLEDGE_GAP",
            transfer_description="Workflow human handoff",
            transfer_group_id=target)
        obj.next_node_id = None
        control = ns["workflow_terminal_intent"](obj)
        self.assertEqual(control["state"], "pending")
        class Repo:
            def __init__(self, db):
                self.db = db
            def create_message(self, values):
                row = w294.ChatHistory(**{k: v for k, v in values.items()
                    if k in {"message", "message_type", "session_id",
                             "organization_id", "agent_id", "attributes"}})
                self.db.add(row)
                self.db.commit()
                return row
        with fx.make_session() as db:
            old = db.get(w294.ChatHistory, fx.bot_id)
            db.delete(old)
            db.commit()
            session = db.get(w294.SessionToAgent, fx.session_id)
            revision = w294.gate.context_revision(db, session)
            response = types.SimpleNamespace(
                message="Hello", transfer_to_human=obj.transfer_to_human,
                end_chat=obj.end_chat, request_rating=False)
            service = types.SimpleNamespace(chat_repo=Repo(db), db=db)
            ns["_store_workflow_response"](
                service, response, str(fx.session_id), str(fx.org),
                {"agent_id": str(fx.agent_id)}, None, session, obj,
                fx.source_id, revision)
            fx.bot_id = response._stored_message_id
            fx.snapshot = response._auto_authority_snapshot
            persisted = db.get(w294.ChatHistory, fx.bot_id)
            self.assertEqual((persisted.attributes or {})
                             ["workflow_terminal_control"], control)
        return ns

    def terminal_state(self):
        with self.fixture.make_session() as db:
            bot = db.get(w294.ChatHistory, self.fixture.bot_id)
            session = db.get(w294.SessionToAgent, self.fixture.session_id)
            return (session.status,
                    (bot.attributes or {}).get("workflow_terminal_control", {}).get("state"),
                    session.group_id, session.transfer_reason)

    def run_terminal_recovery(self, ns):
        fx = self.fixture
        with fx.make_session() as db:
            session = db.get(w294.SessionToAgent, fx.session_id)
            return asyncio.run(ns["resume_pending_workflow_terminal_controls"](db, session))

    def test_terminal_direct_transfer_no_ack_reconnect_once(self):
        ns = self.set_direct_terminal("transfer")
        self.allow_ack = False
        self.assertFalse(self.send().ok)
        self.assertEqual(self.persisted(), "sending")
        self.assertEqual(self.terminal_state()[0:2], ("open", "pending"))
        self.client.disconnect()
        self.allow_ack = True
        self.client.connect(f"http://127.0.0.1:{self.port}",
                            namespaces=["/widget"], transports=["websocket"], wait_timeout=5)
        record = types.SimpleNamespace(session_id=self.fixture.session_id, channel="web")
        with self.fixture.make_session() as db:
            self.assertEqual(asyncio.run(
                self.ns["recover_pending_web_auto_messages"](db, record)), 1)
        self.assertEqual(self.run_terminal_recovery(ns), 1)
        self.assertEqual(self.run_terminal_recovery(ns), 0)
        self.assertEqual(self.terminal_state()[0:2], ("transferred", "applied"))
        self.assertEqual(self.terminal_state()[3], "KNOWLEDGE_GAP")
        self.assertEqual(set(self.visible), {self.fixture.bot_id})
        self.assertEqual(self.persisted(), "succeeded")
        with self.fixture.make_session() as db:
            rows = db.query(w294.ChatHistory).filter(
                w294.ChatHistory.session_id == self.fixture.session_id,
                w294.ChatHistory.message_type == "bot").all()
        self.assertEqual(len(rows), 1)

    def test_terminal_direct_end_chat_no_ack_reconnect_once(self):
        ns = self.set_direct_terminal("end_chat")
        self.allow_ack = False
        self.assertFalse(self.send().ok)
        self.assertEqual(self.terminal_state()[0:2], ("open", "pending"))
        self.allow_ack = True
        record = types.SimpleNamespace(session_id=self.fixture.session_id, channel="web")
        with self.fixture.make_session() as db:
            self.assertEqual(asyncio.run(
                self.ns["recover_pending_web_auto_messages"](db, record)), 1)
        self.assertEqual(self.run_terminal_recovery(ns), 1)
        self.assertEqual(self.run_terminal_recovery(ns), 0)
        self.assertEqual(self.terminal_state()[0:2], ("closed", "applied"))
        self.assertEqual(set(self.visible), {self.fixture.bot_id})

    def test_terminal_post_ack_post_commit_crash_resumes_without_resend(self):
        ns = self.set_direct_terminal("transfer")
        self.assertTrue(self.send().ok)
        self.assertEqual(self.terminal_state()[0:2], ("open", "pending"))
        before = list(self.all_events)
        self.assertEqual(self.run_terminal_recovery(ns), 1)
        self.assertEqual(self.run_terminal_recovery(ns), 0)
        self.assertEqual(self.all_events, before)
        self.assertEqual(self.terminal_state()[0:2], ("transferred", "applied"))

    def test_terminal_ack_crash_post_commit_end_chat_recovers(self):
        ns = self.set_direct_terminal("end_chat")
        self.assertTrue(self.send().ok)
        self.assertEqual(self.terminal_state()[0:2], ("open", "pending"))
        self.assertEqual(self.run_terminal_recovery(ns), 1)
        self.assertEqual(self.terminal_state()[0:2], ("closed", "applied"))
        self.assertEqual(self.run_terminal_recovery(ns), 0)
        self.assertEqual(list(self.visible), [self.fixture.bot_id])

    def test_terminal_post_ack_takeover_veto_control_zero(self):
        ns = self.set_direct_terminal("transfer")
        self.assertTrue(self.send().ok)
        self.fixture.invalidate("takeover")
        self.assertEqual(self.run_terminal_recovery(ns), 0)
        self.assertEqual(self.terminal_state()[1], "pending")

    def test_terminal_post_ack_revoke_veto_control_zero(self):
        ns = self.set_direct_terminal("end_chat")
        self.assertTrue(self.send().ok)
        self.fixture.invalidate("disabled")
        self.assertEqual(self.run_terminal_recovery(ns), 0)
        self.assertEqual(self.terminal_state()[0:2], ("open", "pending"))

    def test_terminal_post_ack_new_inbound_veto_control_zero(self):
        ns = self.set_direct_terminal("transfer")
        self.assertTrue(self.send().ok)
        self.fixture.invalidate("new_inbound")
        self.assertEqual(self.run_terminal_recovery(ns), 0)
        self.assertEqual(self.terminal_state()[0:2], ("open", "pending"))

    def test_terminal_no_ack_revoked_before_retry_visible_zero_control_zero(self):
        ns = self.set_direct_terminal("end_chat")
        self.client.disconnect()
        self.assertFalse(self.send().ok)
        self.fixture.invalidate("closed")
        self.client.connect(f"http://127.0.0.1:{self.port}",
                            namespaces=["/widget"], transports=["websocket"], wait_timeout=5)
        record = types.SimpleNamespace(session_id=self.fixture.session_id, channel="web")
        with self.fixture.make_session() as db:
            self.assertEqual(asyncio.run(
                self.ns["recover_pending_web_auto_messages"](db, record)), 0)
        self.assertEqual(self.run_terminal_recovery(ns), 0)
        self.assertEqual(self.visible, {})
        self.assertEqual(self.terminal_state()[1], "pending")

    def test_terminal_concurrent_recovery_applies_exactly_once(self):
        ns = self.set_direct_terminal("transfer")
        self.assertTrue(self.send().ok)
        outcomes = []
        errors = []
        barrier = threading.Barrier(2)
        def worker():
            try:
                barrier.wait(timeout=4)
                outcomes.append(self.run_terminal_recovery(ns))
            except BaseException as exc:
                errors.append(repr(exc))
        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads: t.start()
        for t in threads: t.join(timeout=10)
        self.assertFalse(any(t.is_alive() for t in threads))
        self.assertFalse(errors, errors)
        self.assertEqual(sorted(outcomes), [0, 1])
        self.assertEqual(self.terminal_state()[0:2], ("transferred", "applied"))
        self.assertEqual(list(self.visible), [self.fixture.bot_id])


    def foreign_group(self):
        """Real PostgreSQL group/org/member FK rows in a different tenant."""
        org, gid, uid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        with self.fixture.make_session() as db:
            db.add(w294.Organization(id=org))
            db.commit()
            db.add(w294.UserGroup(id=gid, organization_id=org, name="Foreign tenant"))
            db.add(w294.User(id=uid, organization_id=org, is_active=True))
            db.commit()
            db.execute(w294.user_groups.insert().values(user_id=uid, group_id=gid))
            db.commit()
        self.foreign_groups.append((org, gid, uid))
        return org, gid, uid

    def test_w313_physical_fk_relationships_are_enforced(self):
        fx = self.fixture
        with fx.make_session() as db:
            foreign_keys = db.execute(text("""
                SELECT conrelid::regclass::text AS child,
                       confrelid::regclass::text AS parent
                FROM pg_constraint WHERE contype='f'
                  AND conrelid::regclass::text IN
                   ('w294_groups','w294_session_to_agents','w294_user_groups')
            """)).all()
            edges = set(foreign_keys)
            self.assertIn(("w294_groups", "w294_organizations"), edges)
            self.assertIn(("w294_session_to_agents", "w294_groups"), edges)
            self.assertIn(("w294_session_to_agents", "w294_organizations"), edges)
            self.assertIn(("w294_user_groups", "w294_groups"), edges)
            self.assertEqual(db.get(w294.UserGroup, fx.group_id).organization_id, fx.org)

    def test_w313_explicit_same_org_no_ack_then_control_and_notice_once(self):
        fx = self.fixture
        ns = self.set_direct_terminal("transfer", target=str(fx.group_id))
        self.allow_ack = False
        self.assertFalse(self.send().ok)
        self.assertEqual(self.persisted(), "sending")
        self.assertEqual(self.notice_calls, [])
        self.allow_ack = True
        record = types.SimpleNamespace(session_id=fx.session_id, channel="web")
        with fx.make_session() as db:
            self.assertEqual(asyncio.run(
                self.ns["recover_pending_web_auto_messages"](db, record)), 1)
        self.assertEqual(self.run_terminal_recovery(ns), 1)
        self.assertEqual(self.run_terminal_recovery(ns), 0)
        self.assertEqual(self.terminal_state()[0:3],
                         ("transferred", "applied", fx.group_id))
        self.assertEqual(len(self.notice_calls), 1)
        self.assertEqual(self.notice_calls[0]["users"], {fx.notice_user_id})
        self.assertEqual(set(self.visible), {fx.bot_id})
        with fx.make_session() as db:
            self.assertEqual(db.query(w294.ChatHistory).filter(
                w294.ChatHistory.session_id == fx.session_id,
                w294.ChatHistory.message_type == "bot").count(), 1)

    def test_w313_foreign_group_uuid_denies_post_ack_control_and_notice(self):
        _, foreign_gid, _ = self.foreign_group()
        ns = self.set_direct_terminal("transfer", target=str(foreign_gid))
        self.assertTrue(self.send().ok)
        self.assertEqual(self.run_terminal_recovery(ns), 0)
        self.assertEqual(self.run_terminal_recovery(ns), 0)
        self.assertEqual(self.terminal_state()[0:3], ("open", "pending", None))
        self.assertEqual(self.notice_calls, [])

    def test_w313_invalid_missing_uuid_fail_closed(self):
        for target in ("not-a-uuid", str(uuid.uuid4()), ""):
            with self.subTest(target=target):
                # Test isolated row generation without corrupting the prior
                # revision: a single direct terminal attempt per subtest.
                with self.fixture.make_session() as db:
                    session = db.get(w294.SessionToAgent, self.fixture.session_id)
                    session.status = "open"
                    session.group_id = None
                    bot = db.get(w294.ChatHistory, self.fixture.bot_id)
                    bot.attributes = {**(bot.attributes or {}),
                        "workflow_terminal_control": {
                            "state": "pending", "kind": "transfer",
                            "transfer": {"message": bot.message,
                                         "transfer_group_id": target}}}
                    db.commit()
                if self.persisted() != "succeeded":
                    self.assertTrue(self.send().ok)
                ns = self.terminal_ns()
                self.assertEqual(self.run_terminal_recovery(ns), 0)
                self.assertEqual(self.terminal_state()[0:3], ("open", "pending", None))
                self.assertEqual(self.notice_calls, [])
                # subsequent subtests maintain the already delivered row,
                # terminal authorization is tested without second emission.

    def test_w313_fallback_foreign_group_denies(self):
        _, gid, _ = self.foreign_group()
        fx = self.fixture
        with fx.make_session() as db:
            db.execute(w294.agent_usergroup.delete().where(
                w294.agent_usergroup.c.agent_id == fx.agent_id))
            db.execute(w294.agent_usergroup.insert().values(
                agent_id=fx.agent_id, group_id=gid))
            db.commit()
        ns = self.set_direct_terminal("transfer")
        self.assertTrue(self.send().ok)
        self.assertEqual(self.run_terminal_recovery(ns), 0)
        self.assertEqual(self.terminal_state()[0:3], ("open", "pending", None))
        self.assertEqual(self.notice_calls, [])

    def test_w313_fallback_absent_group_denies(self):
        fx = self.fixture
        with fx.make_session() as db:
            db.execute(w294.agent_usergroup.delete().where(
                w294.agent_usergroup.c.agent_id == fx.agent_id))
            db.commit()
        ns = self.set_direct_terminal("transfer")
        self.assertTrue(self.send().ok)
        self.assertEqual(self.run_terminal_recovery(ns), 0)
        self.assertEqual(self.terminal_state()[0:3], ("open", "pending", None))
        self.assertEqual(self.notice_calls, [])

    def test_w313_foreign_membership_filtered_from_notice(self):
        org, foreign_gid, foreign_uid = self.foreign_group()
        fx = self.fixture
        with fx.make_session() as db:
            # Deliberately insert a cross-tenant user_groups association,
            # which the base schema permits, to prove scoped recipients.
            db.execute(w294.user_groups.insert().values(
                user_id=foreign_uid, group_id=fx.group_id))
            db.commit()
        ns = self.set_direct_terminal("transfer", target=str(fx.group_id))
        self.assertTrue(self.send().ok)
        self.assertEqual(self.run_terminal_recovery(ns), 1)
        self.assertEqual(self.notice_calls[0]["users"], {fx.notice_user_id})
        self.assertEqual(len(self.notice_calls), 1)

    def test_w313_explicit_group_scope_flip_after_ack_denies(self):
        fx = self.fixture
        other_org, _, _ = self.foreign_group()
        ns = self.set_direct_terminal("transfer", target=str(fx.group_id))
        self.assertTrue(self.send().ok)
        with fx.make_session() as db:
            db.get(w294.UserGroup, fx.group_id).organization_id = other_org
            db.commit()
        self.assertEqual(self.run_terminal_recovery(ns), 0)
        self.assertEqual(self.terminal_state()[0:3], ("open", "pending", None))
        self.assertEqual(self.notice_calls, [])
        with fx.make_session() as db:
            db.get(w294.UserGroup, fx.group_id).organization_id = fx.org
            db.commit()

    def test_w313_explicit_valid_concurrent_exactly_one_notice(self):
        ns = self.set_direct_terminal(
            "transfer", target=str(self.fixture.group_id))
        self.assertTrue(self.send().ok)
        barrier = threading.Barrier(2)
        outcomes, errors = [], []
        def worker():
            try:
                barrier.wait(timeout=5)
                outcomes.append(self.run_terminal_recovery(ns))
            except BaseException as exc:
                errors.append(repr(exc))
        threads = [threading.Thread(target=worker) for _ in range(2)]
        for worker_thread in threads: worker_thread.start()
        for worker_thread in threads: worker_thread.join(timeout=12)
        self.assertFalse(any(t.is_alive() for t in threads))
        self.assertFalse(errors, errors)
        self.assertEqual(sorted(outcomes), [0, 1])
        self.assertEqual(len(self.notice_calls), 1)
        self.assertEqual(self.terminal_state()[0:3],
                         ("transferred", "applied", self.fixture.group_id))

    def test_w313_revoke_before_control_zero_notice(self):
        ns = self.set_direct_terminal("transfer", target=str(self.fixture.group_id))
        self.assertTrue(self.send().ok)
        self.fixture.invalidate("disabled")
        self.assertEqual(self.run_terminal_recovery(ns), 0)
        self.assertEqual(self.terminal_state()[0:3], ("open", "pending", None))
        self.assertEqual(self.notice_calls, [])

    def test_w313_inbound_before_control_zero_notice(self):
        ns = self.set_direct_terminal("transfer", target=str(self.fixture.group_id))
        self.assertTrue(self.send().ok)
        self.fixture.invalidate("new_inbound")
        self.assertEqual(self.run_terminal_recovery(ns), 0)
        self.assertEqual(self.terminal_state()[0:3], ("open", "pending", None))
        self.assertEqual(self.notice_calls, [])


if __name__ == "__main__":
    unittest.main()
