"""Window294: real PostgreSQL persisted-row AI_AUTO commitment adversarial proof.

Execute in isolated PG16.15 database (never canonical).
W294_PG_URL=postgresql+psycopg://1@127.0.0.1:55494/postgres
python -m unittest backend.yance_tests.test_window294_reply_commitment_pg -v
"""
from __future__ import annotations

import importlib.util
import os
import sys
import threading
import time
import types
import unittest
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Boolean, Table, create_engine
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

Base = declarative_base()


# W313: real physical PostgreSQL tenant/group/user/agent-group FK fixture
# mirrors existing production owners' organization_id and membership scope.
class Organization(Base):
    __tablename__ = "w294_organizations"
    id = Column(UUID(as_uuid=True), primary_key=True)


class Customer(Base):
    """Source-matching existing Customer owner for canonical revision hashing."""
    __tablename__ = "w294_customers"
    id = Column(UUID(as_uuid=True), primary_key=True)
    organization_id = Column(UUID(as_uuid=True),
                             ForeignKey("w294_organizations.id"), nullable=False)
    meta_data = Column(JSON, nullable=False, default=dict)


class UserGroup(Base):
    __tablename__ = "w294_groups"
    id = Column(UUID(as_uuid=True), primary_key=True)
    organization_id = Column(UUID(as_uuid=True),
                             ForeignKey("w294_organizations.id"), nullable=False)
    name = Column(String, nullable=False)


class User(Base):
    __tablename__ = "w294_users"
    id = Column(UUID(as_uuid=True), primary_key=True)
    organization_id = Column(UUID(as_uuid=True),
                             ForeignKey("w294_organizations.id"), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)


user_groups = Table(
    "w294_user_groups", Base.metadata,
    Column("user_id", UUID(as_uuid=True), ForeignKey("w294_users.id"), primary_key=True),
    Column("group_id", UUID(as_uuid=True), ForeignKey("w294_groups.id"), primary_key=True),
)
agent_usergroup = Table(
    "w294_agent_usergroup", Base.metadata,
    Column("agent_id", UUID(as_uuid=True), ForeignKey("w294_agents.id"), primary_key=True),
    Column("group_id", UUID(as_uuid=True), ForeignKey("w294_groups.id"), primary_key=True),
)


class SessionStatus(str, Enum):
    OPEN = "open"
    TRANSFERRED = "transferred"
    CLOSED = "closed"


class SessionToAgent(Base):
    __tablename__ = "w294_session_to_agents"
    session_id = Column(UUID(as_uuid=True), primary_key=True)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("w294_organizations.id"), nullable=False)
    agent_id = Column(UUID(as_uuid=True), ForeignKey("w294_agents.id"), nullable=False)
    customer_id = Column(UUID(as_uuid=True), ForeignKey("w294_customers.id"), nullable=True)
    user_id = Column(UUID(as_uuid=True), nullable=True)
    status = Column(String, nullable=False)
    group_id = Column(UUID(as_uuid=True), ForeignKey("w294_groups.id"), nullable=True)
    workflow_id = Column(UUID(as_uuid=True), nullable=True)
    transfer_reason = Column(String)
    transfer_description = Column(String)
    closed_at = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True), nullable=False)


class Agent(Base):
    __tablename__ = "w294_agents"
    id = Column(UUID(as_uuid=True), primary_key=True)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("w294_organizations.id"), nullable=False)
    ai_replies_enabled = Column(Boolean, nullable=False)
    instructions = Column(JSON, nullable=False, default=list)
    groups = relationship("UserGroup", secondary=agent_usergroup)


class ChatHistory(Base):
    __tablename__ = "w294_chat_history"
    id = Column(Integer, primary_key=True, autoincrement=True)
    organization_id = Column(UUID(as_uuid=True), nullable=False)
    agent_id = Column(UUID(as_uuid=True), nullable=False)
    session_id = Column(UUID(as_uuid=True), ForeignKey("w294_session_to_agents.session_id"), nullable=False)
    customer_id = Column(UUID(as_uuid=True), ForeignKey("w294_customers.id"), nullable=True)
    message_type = Column(String, nullable=False)
    message = Column(String, nullable=False)
    attributes = Column(JSON, nullable=False, default=dict)


# Exercise the ACTUAL W294 gate module against persisted PostgreSQL rows.
for name in ("app", "app.models", "app.models.agent", "app.models.chat_history", "app.models.session_to_agent", "app.models.customer"):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.modules["app.models.agent"].Agent = Agent
sys.modules["app.models.customer"].Customer = Customer
sys.modules["app.models.chat_history"].ChatHistory = ChatHistory
sys.modules["app.models.session_to_agent"].SessionToAgent = SessionToAgent
sys.modules["app.models.session_to_agent"].SessionStatus = SessionStatus

path = Path(__file__).resolve().parents[1] / "app/services/yance_turn_authority.py"
spec = importlib.util.spec_from_file_location("w294_isolated_actual_gate", path)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class Window294PostgreSQLProof(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(os.environ.get(
            "W294_PG_URL", "postgresql+psycopg://1@127.0.0.1:55494/postgres"
        ), pool_pre_ping=True, isolation_level="READ COMMITTED")
        Base.metadata.create_all(cls.engine)
        cls.make_session = sessionmaker(bind=cls.engine, expire_on_commit=False)

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(cls.engine)
        cls.engine.dispose()

    def setUp(self):
        self.org = uuid.uuid4()
        self.agent_id = uuid.uuid4()
        self.customer_id = uuid.uuid4()
        self.session_id = uuid.uuid4()
        self.group_id = uuid.uuid4()
        self.notice_user_id = uuid.uuid4()
        with self.make_session() as db:
            db.add(Organization(id=self.org))
            db.commit()
            db.add(Customer(id=self.customer_id, organization_id=self.org, meta_data={}))
            db.commit()
            group = UserGroup(id=self.group_id, organization_id=self.org, name="Same tenant group")
            db.add(group)
            db.commit()
            agent = Agent(id=self.agent_id, organization_id=self.org, ai_replies_enabled=True)
            agent.groups.append(group)
            db.add(agent)
            user_member = User(id=self.notice_user_id, organization_id=self.org, is_active=True)
            db.add(user_member)
            db.commit()
            db.execute(user_groups.insert().values(
                user_id=self.notice_user_id, group_id=self.group_id))
            db.add(SessionToAgent(session_id=self.session_id, organization_id=self.org,
                                  agent_id=self.agent_id, customer_id=self.customer_id, user_id=None,
                                  status="open", updated_at=datetime.now(timezone.utc)))
            db.commit()
            user = ChatHistory(session_id=self.session_id, organization_id=self.org,
                               agent_id=self.agent_id, customer_id=self.customer_id, message="Hi", message_type="user", attributes={})
            db.add(user)
            db.commit()
            bot = ChatHistory(session_id=self.session_id, organization_id=self.org,
                              agent_id=self.agent_id, customer_id=self.customer_id, message="Hello", message_type="bot", attributes={})
            db.add(bot)
            db.commit()
            self.source_id = user.id
            self.bot_id = bot.id
            session = db.get(SessionToAgent, self.session_id)
            self.snapshot = {
                "organization_id": str(self.org), "agent_id": str(self.agent_id),
                "session_id": str(self.session_id), "source_message_id": self.source_id,
                "bot_message_id": self.bot_id,
                "context_revision": gate.context_revision(db, session, ignore_bot_message_id=self.bot_id),
                "mode": "AI_AUTO", "send_allowed": True, "sensitive_action": False
            }
            self.payload = {"message_id": self.bot_id, "message": "Hello"}

    def tearDown(self):
        with self.make_session() as db:
            db.query(ChatHistory).filter(ChatHistory.session_id == self.session_id).delete()
            db.query(SessionToAgent).filter(SessionToAgent.session_id == self.session_id).delete()
            db.execute(agent_usergroup.delete().where(agent_usergroup.c.agent_id == self.agent_id))
            db.query(Agent).filter(Agent.id == self.agent_id).delete()
            db.execute(user_groups.delete().where(user_groups.c.user_id == self.notice_user_id))
            db.query(User).filter(User.id == self.notice_user_id).delete()
            db.query(UserGroup).filter(UserGroup.id == self.group_id).delete()
            db.query(Customer).filter(Customer.id == self.customer_id).delete()
            db.query(Organization).filter(Organization.id == self.org).delete()
            db.commit()

    def commitment(self):
        with self.make_session() as db:
            result = gate.revalidate_auto_send(db, self.snapshot, self.payload)
            db.rollback()
            return result

    def invalidate(self, label):
        with self.make_session() as db:
            if label == "closed":
                s = db.get(SessionToAgent, self.session_id)
                s.status = "closed"
            elif label == "takeover":
                s = db.get(SessionToAgent, self.session_id)
                s.user_id = uuid.uuid4()
            elif label == "disabled":
                a = db.get(Agent, self.agent_id)
                a.ai_replies_enabled = False
            elif label == "new_inbound":
                db.add(ChatHistory(session_id=self.session_id, organization_id=self.org,
                                   agent_id=self.agent_id, message="new", message_type="user",
                                   attributes={}))
            elif label == "revision":
                s = db.get(SessionToAgent, self.session_id)
                s.updated_at = datetime.now(timezone.utc).replace(year=2027)
            db.commit()

    def test_five_post_reservation_revocations_are_fail_closed(self):
        for label in ("closed", "takeover", "disabled", "new_inbound", "revision"):
            with self.subTest(label=label):
                # Reset to pristine authority and then invalidate after snapshot.
                if label != "closed":
                    with self.make_session() as db:
                        s=db.get(SessionToAgent,self.session_id)
                        s.status="open"
                        s.user_id=None
                        s.updated_at=datetime.fromisoformat(self.snapshot["context_revision"].split(":",3)[2])
                        db.get(Agent,self.agent_id).ai_replies_enabled=True
                        db.query(ChatHistory).filter(
                            ChatHistory.session_id==self.session_id,ChatHistory.id>self.bot_id).delete()
                        db.commit()
                self.invalidate(label)
                result=self.commitment()
                self.assertIsNotNone(result, label)
                with self.make_session() as db:
                    self.assertEqual(db.query(ChatHistory).filter(
                        ChatHistory.session_id==self.session_id,
                        ChatHistory.message_type=="bot").count(),1)
                    self.assertNotEqual((db.get(ChatHistory,self.bot_id).attributes or {})
                                        .get("provider_delivery",{}).get("state"),"succeeded")

    def test_sensitive_and_no_reply_defer_boundaries(self):
        for patch in ({"sensitive_action":True}, {"reply_state":"no_reply"},
                      {"reply_state":"defer"}, {"confirmed_boundary_denies_send":True}):
            auth={**self.snapshot, **patch}
            with self.make_session() as db:
                self.assertIsNotNone(gate.revalidate_auto_send(db,auth,self.payload))
                db.rollback()

    def test_single_send_and_retry_reentry_idempotence(self):
        sends=[]
        with self.make_session() as db:
            self.assertIsNone(gate.revalidate_auto_send(db,self.snapshot,self.payload))
            sends.append(self.bot_id)
            msg=db.get(ChatHistory,self.bot_id)
            msg.attributes={"provider_delivery":{"state":"succeeded"}}
            db.commit()
        self.assertEqual(sends,[self.bot_id])
        self.assertEqual(self.commitment(),"auto_send_already_committed")

    def test_pg_fk_insert_waits_while_gate_holds_session_lock(self):
        begun=threading.Event()
        finished=threading.Event()
        def inbound_worker():
            with self.make_session() as other:
                begun.set()
                other.add(ChatHistory(session_id=self.session_id,organization_id=self.org,
                                      agent_id=self.agent_id,message_type="user",
                                      message="Racing inbound",attributes={}))
                other.commit()
                finished.set()
        with self.make_session() as db:
            self.assertIsNone(gate.revalidate_auto_send(db,self.snapshot,self.payload))
            th=threading.Thread(target=inbound_worker,daemon=True)
            th.start()
            self.assertTrue(begun.wait(2))
            self.assertFalse(finished.wait(0.2),"FK insert overtook FOR UPDATE")
            db.rollback()
        self.assertTrue(finished.wait(4))
        th.join(2)
        self.assertEqual(self.commitment(),"auto_send_latest_inbound_changed")


    def test_generation_revision_stale_prevents_adoption_and_learning(self):
        # Execute real W173 evidence function, imported from source without
        # bootstrapping the unrelated Agent/Agno/application runtime.
        import ast
        code = (Path(__file__).resolve().parents[1]
                / "app/services/yance_reply_runtime.py").read_text(encoding="utf-8")
        node = next(n for n in ast.parse(code).body if isinstance(n, ast.FunctionDef)
                    and n.name == "record_candidate_evidence")
        def latest_user_message(db, session_id):
            row = (db.query(ChatHistory).filter(ChatHistory.session_id == session_id)
                   .order_by(ChatHistory.id.desc()).first())
            return row if row is not None and row.message_type == "user" else None
        ns={"ChatHistory":ChatHistory, "SessionToAgent":SessionToAgent,
            "context_revision":gate.context_revision,
            "latest_user_message":latest_user_message}
        exec("from __future__ import annotations\n"+ast.unparse(node),ns)
        record=ns["record_candidate_evidence"]

        with self.make_session() as db:
            db.delete(db.get(ChatHistory,self.bot_id))
            db.commit()
            session=db.get(SessionToAgent,self.session_id)
            generation_revision=gate.context_revision(db,session)
            def evidence(revision=generation_revision, decision="adopt", do_not_learn=False):
                return record(db,session,source_message_id=self.source_id,
                              context_revision_at_generation=revision,
                              candidate_id=f"{self.source_id}:1",decision=decision,
                              draft="Generated",do_not_learn=do_not_learn)
            # Exact snapshot: accepted, event binds the ORIGINAL generation revision.
            accepted=evidence()
            self.assertTrue(accepted["recorded"])
            self.assertFalse(accepted["stale"])
            self.assertEqual(db.get(ChatHistory,self.source_id).attributes["yance_reply_evidence"][-1]
                             ["context_revision"],generation_revision)
            original_size=len(db.get(ChatHistory,self.source_id).attributes["yance_reply_evidence"])
            session.updated_at=datetime(2027,1,1,tzinfo=timezone.utc)
            db.commit()
            stale=evidence()
            self.assertTrue(stale["stale"])
            self.assertFalse(stale["recorded"])
            self.assertEqual(len(db.get(ChatHistory,self.source_id).attributes["yance_reply_evidence"]),
                             original_size)
            # An incorrect revision string must not refresh a stale candidate.
            self.assertFalse(evidence(revision="forged:revision")["recorded"])
            newer=ChatHistory(session_id=self.session_id,organization_id=self.org,
                              agent_id=self.agent_id,message_type="user",message="newer",attributes={})
            db.add(newer)
            db.commit()
            self.assertFalse(evidence()["recorded"])
            self.assertEqual(len(db.get(ChatHistory,self.source_id).attributes["yance_reply_evidence"]),
                             original_size)

    def test_do_not_learn_keeps_evidence_without_delivery_promotion(self):
        import ast
        code=(Path(__file__).resolve().parents[1]
              / "app/services/yance_reply_runtime.py").read_text(encoding="utf-8")
        node=next(n for n in ast.parse(code).body if isinstance(n,ast.FunctionDef)
                  and n.name=="finalize_successful_send_learning")
        ns={"ChatHistory":ChatHistory}
        exec("from __future__ import annotations\n"+ast.unparse(node),ns)
        finalize=ns["finalize_successful_send_learning"]
        with self.make_session() as db:
            source=db.get(ChatHistory,self.source_id)
            source.attributes={"yance_reply_evidence":[
                {"candidate_id":"c1","decision":"adopt","draft":"Hello",
                 "context_revision":self.snapshot["context_revision"],
                 "do_not_learn":True}]}
            sent=db.get(ChatHistory,self.bot_id)
            sent.message_type="agent"
            db.commit()
            finalize(db,self.bot_id)
            db.refresh(source)
            db.refresh(sent)
            self.assertNotIn("sent_message_id",source.attributes["yance_reply_evidence"][-1])
            self.assertNotIn("yance_learning",sent.attributes)

    def test_two_workers_share_single_physical_commitment(self):
        # Two independent PostgreSQL transactions race to commit the same
        # canonical bot row. The session FOR UPDATE lock serializes them.
        barrier = threading.Barrier(2)
        counts = []
        reasons = []
        lock = threading.Lock()

        def worker():
            barrier.wait()
            with self.make_session() as db:
                reason = gate.revalidate_auto_send(db, self.snapshot, self.payload)
                if reason is None:
                    with lock:
                        counts.append(self.bot_id)  # recipient/provider mock
                    bot = db.get(ChatHistory, self.bot_id)
                    bot.attributes = {"provider_delivery": {"state": "succeeded"}}
                    db.commit()
                else:
                    with lock:
                        reasons.append(reason)
                    db.rollback()

        threads = [threading.Thread(target=worker, daemon=True) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(5)
            self.assertFalse(thread.is_alive())
        self.assertEqual(counts, [self.bot_id])
        self.assertEqual(reasons, ["auto_send_already_committed"])
        with self.make_session() as db:
            self.assertEqual(db.query(ChatHistory).filter(
                ChatHistory.session_id == self.session_id,
                ChatHistory.message_type == "bot").count(), 1)

    def test_actual_message_delivery_call_path_uses_final_gate(self):
        import ast
        import asyncio
        from types import SimpleNamespace
        source=(Path(__file__).resolve().parents[1]
                / "app/services/message_delivery.py").read_text(encoding="utf-8")
        node=next(n for n in ast.parse(source).body if isinstance(n,ast.AsyncFunctionDef)
                  and n.name=="deliver_to_customer")
        delivery_counter={"provider":0,"recipient":0}
        def mark_failed(db, bot_id, reason):
            row=db.get(ChatHistory,bot_id)
            row.attributes={**(row.attributes or {}),"delivery_status":reason}
            db.commit()
        class ChatRepo:
            def __init__(self,db):self.db=db
            def mark_delivery_failed(self,mid,reason):
                mark_failed(self.db,mid,reason)
        class Socket:
            async def emit(self,event,payload,**kwargs):
                assert "_ai_auto_authority" not in payload
                delivery_counter["recipient"]+=1
        def result(ok,reason=None):return SimpleNamespace(ok=ok,reason=reason)
        async def provider(db,record,channel,payload):
            delivery_counter["provider"]+=1
            message=db.get(ChatHistory,payload["message_id"])
            message.attributes={**(message.attributes or {}),
                                "provider_delivery":{"state":"succeeded"}}
            db.commit()
            return result(True)
        ns={"WEB_CHANNEL":"web","SessionLocal":self.make_session,
            "revalidate_auto_send":gate.revalidate_auto_send,
            "_delivery_message":lambda db, payload: db.get(ChatHistory,payload["message_id"]),
            "ChatRepository":ChatRepo,"DeliveryResult":result,
            "_deliver_to_channel":provider,"sio":Socket()}
        exec("from __future__ import annotations\n"+ast.unparse(node),ns)
        deliver=ns["deliver_to_customer"]
        session_record=SimpleNamespace(session_id=self.session_id,channel="facebook")
        def send(snapshot=None):
            auth=snapshot if snapshot is not None else self.snapshot
            with self.make_session() as db:
                return asyncio.run(deliver(db,session_record,{**self.payload,
                                  "_ai_auto_authority":auth}))
        baseline=datetime.fromisoformat(self.snapshot["context_revision"].split(":",3)[2])
        for label in ("closed","takeover","disabled","new_inbound","revision"):
            with self.subTest(revocation=label):
                with self.make_session() as db:
                    session=db.get(SessionToAgent,self.session_id)
                    session.status="open"
                    session.user_id=None
                    session.updated_at=baseline
                    db.get(Agent,self.agent_id).ai_replies_enabled=True
                    db.query(ChatHistory).filter(ChatHistory.session_id==self.session_id,
                                                 ChatHistory.id>self.bot_id).delete()
                    db.get(ChatHistory,self.bot_id).attributes={}
                    db.commit()
                self.invalidate(label)     # transaction B
                outcome=send()              # worker A enters physical send
                self.assertFalse(outcome.ok)
                self.assertEqual(delivery_counter,{"provider":0,"recipient":0})
                with self.make_session() as db:
                    self.assertEqual(db.query(ChatHistory).filter(
                        ChatHistory.session_id==self.session_id,
                        ChatHistory.message_type=="bot").count(),1)
                    self.assertNotEqual((db.get(ChatHistory,self.bot_id).attributes or {})
                                        .get("provider_delivery",{}).get("state"),"succeeded")
        with self.make_session() as db:
            session=db.get(SessionToAgent,self.session_id)
            session.status="open"
            session.user_id=None
            session.updated_at=baseline
            db.get(Agent,self.agent_id).ai_replies_enabled=True
            db.query(ChatHistory).filter(ChatHistory.session_id==self.session_id,
                                         ChatHistory.id>self.bot_id).delete()
            db.get(ChatHistory,self.bot_id).attributes={}
            db.commit()
        sensitive=send({**self.snapshot,"sensitive_action":True})
        self.assertFalse(sensitive.ok)
        self.assertEqual(delivery_counter,{"provider":0,"recipient":0})
        # A valid turn reaches the sole provider and sole recipient once.
        with self.make_session() as db:
            db.get(ChatHistory,self.bot_id).attributes={}
            db.commit()
        # A positive operation after prior invalidations is a NEW authorized
        # generation. The old W294 snapshot is deliberately stale by design.
        with self.make_session() as db:
            session = db.get(SessionToAgent, self.session_id)
            self.snapshot["context_revision"] = gate.context_revision(
                db, session, ignore_bot_message_id=self.bot_id)
        allowed=send()
        self.assertTrue(allowed.ok, f"expected permitted physical send; received {allowed.reason}")
        self.assertEqual(delivery_counter,{"provider":1,"recipient":1})
        replay=send()
        self.assertFalse(replay.ok)
        self.assertEqual(replay.reason,"auto_send_already_committed")
        self.assertEqual(delivery_counter,{"provider":1,"recipient":1})
        with self.make_session() as db:
            row=db.get(ChatHistory,self.bot_id)
            self.assertEqual(row.attributes["provider_delivery"]["state"],"succeeded")
            self.assertNotIn("delivery_status",row.attributes)


if __name__=="__main__":
    unittest.main()
