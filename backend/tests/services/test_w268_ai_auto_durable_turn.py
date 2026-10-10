"""W268 app-model tests for durable current-turn controls and AI_AUTO snapshots.

Uses the repository's actual SQLite app schema and owner functions. Temporal
and Relationship decision are frozen only to avoid clock-dependent outcomes.
These are NOT PostgreSQL physical-send tests.
"""
from datetime import datetime, timezone
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest
from app.models.chat_history import ChatHistory
from app.models.session_to_agent import SessionToAgent, SessionStatus
from app.services import yance_reply_runtime as rt
from app.services.yance_turn_authority import (
    read_turn_controls,write_turn_controls,TurnAuthorityConflict
)


@pytest.fixture
def turn(db,test_customer,test_organization,monkeypatch,request):
    # Continuum's own dynamic transaction table is not always included by
    # the legacy conftest Base.metadata.create_all() on a fresh SQLite run.
    # Build its real mapped table for this fixture, not a fake transaction DB.
    from sqlalchemy_continuum import versioning_manager
    from sqlalchemy.orm import configure_mappers
    from app.database import Base
    configure_mappers()
    Base.metadata.create_all(bind=db.get_bind(),checkfirst=True)
    transaction_cls = versioning_manager.transaction_cls
    if transaction_cls is not None:
        transaction_cls.__table__.create(bind=db.get_bind(),checkfirst=True)
    test_agent=request.getfixturevalue('test_agent')
    test_agent.ai_replies_enabled=True
    sid=uuid4()
    session=SessionToAgent(session_id=sid,agent_id=test_agent.id,
          customer_id=test_customer.id,organization_id=test_organization.id,
          status=SessionStatus.OPEN,channel="web")
    db.add(session)
    db.commit()
    source=ChatHistory(message="Hello",message_type="user",session_id=sid,
         customer_id=test_customer.id,agent_id=test_agent.id,
         organization_id=test_organization.id,attributes={})
    db.add(source)
    db.commit()
    # Real full app model/revisions; isolate temporal policy to a stable valid window.
    temporal=NS(defer_recommended=False,
                local_time=datetime(2026,10,8,12,0,tzinfo=timezone.utc),
                effective_timezone="UTC",preferred_contact_start="00:00",
                preferred_contact_end="23:59")
    monkeypatch.setattr(rt,"build_relationship_context",
                        lambda *_args,**_kwargs: NS(
                            temporal=temporal,boundaries=[],sensitive_topics=[]))
    return session,source,test_agent,test_customer


def test_turn_controls_versioned_cas_and_permission_default(db,turn):
    session,source,_,_=turn
    initially=read_turn_controls(db,session)
    assert initially=={
        "source_message_id":source.id,"version":0,"current_goal":None,
        "allow_sensitive_context":False,
    }
    saved=write_turn_controls(db,session.session_id,source_message_id=source.id,
           expected_version=0,current_goal="  Understand the request  ",
           allow_sensitive_context=True)
    assert saved["version"]==1
    assert saved["current_goal"]=="Understand the request"
    assert saved["allow_sensitive_context"] is True
    db.expire_all()
    assert read_turn_controls(db,session)==saved
    with pytest.raises(TurnAuthorityConflict,match="current_turn_revision_conflict"):
        write_turn_controls(db,session.session_id,source_message_id=source.id,
            expected_version=0,current_goal="stale overwrite",
            allow_sensitive_context=False)
    assert read_turn_controls(db,session)==saved


def test_new_inbound_invalidates_stale_controls_write(db,turn):
    session,source,_,_=turn
    db.add(ChatHistory(message="Latest",message_type="user",
          session_id=session.session_id,organization_id=session.organization_id,
          customer_id=session.customer_id,attributes={}))
    db.commit()
    with pytest.raises(TurnAuthorityConflict,match="current_turn_changed"):
        write_turn_controls(db,session.session_id,source_message_id=source.id,
            expected_version=0,current_goal="do not retarget",
            allow_sensitive_context=True)
    assert read_turn_controls(db,session)["allow_sensitive_context"] is False


def test_web_auto_positive_snapshot_and_sensitive_cas_invalidation(db,turn):
    session,source,_,_=turn
    assert rt.ai_auto_capability_denial(session)==""
    snapshot,reason=rt.ai_auto_authority_snapshot(db,session.session_id,source.id)
    assert reason is None and snapshot and snapshot["revision"]
    assert rt.revalidate_ai_auto_authority(db,session.session_id,snapshot) is None
    write_turn_controls(db,session.session_id,source_message_id=source.id,
            expected_version=0,current_goal="new goal",allow_sensitive_context=True)
    assert rt.revalidate_ai_auto_authority(db,session.session_id,snapshot)=="ai_auto_context_stale"


def test_latest_inbound_snapshot_with_multiple_real_history_rows(db, turn):
    """W274: a mature conversation has >1 user row; never Query.scalar().one()."""
    session, first, agent, customer = turn
    second = ChatHistory(message="Another inbound", message_type="user",
        session_id=session.session_id, organization_id=session.organization_id,
        customer_id=customer.id, agent_id=agent.id, attributes={})
    db.add(second)
    db.commit()
    stale, reason = rt.ai_auto_authority_snapshot(db, session.session_id, first.id)
    assert stale is None and reason == "conversation_context_changed"
    fresh, reason = rt.ai_auto_authority_snapshot(db, session.session_id, second.id)
    assert reason is None and fresh is not None
    assert rt.revalidate_ai_auto_authority(db, session.session_id, fresh) is None


def test_cross_session_relationship_evidence_invalidates(db,turn):
    session,source,agent,customer=turn
    snapshot,reason=rt.ai_auto_authority_snapshot(db,session.session_id,source.id)
    assert reason is None
    another=SessionToAgent(session_id=uuid4(),agent_id=agent.id,
             customer_id=customer.id,organization_id=session.organization_id,
             status=SessionStatus.OPEN,channel="web")
    db.add(another)
    db.commit()
    db.add(ChatHistory(message="Another session evidence",message_type="user",
            session_id=another.session_id,organization_id=session.organization_id,
            customer_id=customer.id,agent_id=agent.id,attributes={}))
    db.commit()
    assert rt.revalidate_ai_auto_authority(db,session.session_id,snapshot)=="ai_auto_context_stale"


def test_manual_takeover_and_agent_revocation_invalidate(db,turn):
    session,source,agent,_=turn
    snapshot,reason=rt.ai_auto_authority_snapshot(db,session.session_id,source.id)
    assert reason is None
    agent.ai_replies_enabled=False
    db.commit()
    assert rt.revalidate_ai_auto_authority(db,session.session_id,snapshot)=="ai_auto_permission_revoked"
    agent.ai_replies_enabled=True
    session.status=SessionStatus.CLOSED
    db.commit()
    assert rt.revalidate_ai_auto_authority(db,session.session_id,snapshot)=="manual_takeover"


def _claimed_web_auto(db,session,source,seed="first"):
    from app.repositories.chat import ChatRepository
    from uuid import uuid5, NAMESPACE_URL
    snapshot, reason=rt.ai_auto_authority_snapshot(db,session.session_id,source.id)
    assert reason is None and snapshot
    payload=dict(message="Natural answer",message_type="bot",
        session_id=session.session_id, organization_id=session.organization_id,
        customer_id=session.customer_id,agent_id=session.agent_id,
        attributes={"yance_auto_authority":snapshot})
    intent=uuid5(NAMESPACE_URL,f"w268:{session.session_id}:{source.id}:{seed}")
    bot,claimed=ChatRepository(db).claim_or_get_client_send_intent(
        payload,intent,"ai_auto")
    return bot,claimed


@pytest.mark.asyncio
async def test_source_app_web_physical_emit_once_and_outcomes(db,turn,monkeypatch):
    """Actual app models and actual delivery boundary; SQLite fixture only."""
    from sqlalchemy.orm import sessionmaker
    from unittest.mock import AsyncMock
    from app.services import message_delivery as md
    session,source,_,_=turn
    bot,claimed=_claimed_web_auto(db,session,source)
    assert claimed and bot.client_send_intent_id is not None
    reused,reclaimed=_claimed_web_auto(db,session,source)
    assert not reclaimed and reused.id==bot.id
    spy=AsyncMock()
    monkeypatch.setattr(md,"sio",NS(emit=spy))
    local=sessionmaker(bind=db.get_bind(),autocommit=False,autoflush=False,
                       expire_on_commit=False)
    monkeypatch.setattr(md,"SessionLocal",local)
    payload=dict(message_id=bot.id,message=bot.message,yance_ai_auto=True)
    first=await md.deliver_to_customer(db,session,payload)
    assert first.ok, first.reason
    replay=await md.deliver_to_customer(db,session,payload)
    assert replay.ok
    assert spy.await_count==1
    db.expire_all()
    saved=db.get(ChatHistory,bot.id).attributes["provider_delivery"]
    assert saved["state"]=="succeeded"
    assert saved["outcome"]=="provider_accepted"
    assert saved["recipient_delivered"] is False
    assert saved["recipient_replied"] is False
    assert saved["success"] is False


@pytest.mark.asyncio
async def test_source_app_invalidated_goal_blocks_physical_emit(db,turn,monkeypatch):
    from sqlalchemy.orm import sessionmaker
    from unittest.mock import AsyncMock
    from app.services import message_delivery as md
    session,source,_,_=turn
    bot,_=_claimed_web_auto(db,session,source)
    # Operator commits a new version before the physical-send commitment.
    # Bot creation is allowed; sending its old snapshot is not.
    # The latest current-turn ChatHistory row remains inbound for this CAS.
    write_turn_controls(db,session.session_id,source_message_id=source.id,
        expected_version=0,current_goal="Changed after generation",
        allow_sensitive_context=True)
    spy=AsyncMock()
    monkeypatch.setattr(md,"sio",NS(emit=spy))
    monkeypatch.setattr(md,"SessionLocal",
        sessionmaker(bind=db.get_bind(),expire_on_commit=False))
    result=await md.deliver_to_customer(db,session,{
        "message_id":bot.id,"message":bot.message,"yance_ai_auto":True})
    assert not result.ok
    assert spy.await_count==0
