"""W321: recovery reuses the EXISTING ChatRepository execution guard.

The actual two-client JWT / Socket.IO / PostgreSQL physical proof is kept
separately, not replaced by mocked network ACKs in this unit regression.
"""
import asyncio
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest

from app.models.chat_history import ChatHistory
from app.models.session_to_agent import SessionStatus, SessionToAgent
from app.services import message_delivery as delivery


@pytest.mark.asyncio
async def test_recovery_two_simultaneous_handlers_only_one_canonical_delivery(
    db, test_agent, test_customer, test_organization, monkeypatch
):
    session = SessionToAgent(
        session_id=uuid4(), organization_id=test_organization.id,
        agent_id=test_agent.id, customer_id=test_customer.id,
        status=SessionStatus.OPEN, channel="web",
    )
    db.add(session)
    db.commit()
    bot = ChatHistory(
        message="Recovery candidate", message_type="bot",
        session_id=session.session_id,
        organization_id=test_organization.id,
        customer_id=test_customer.id, agent_id=test_agent.id,
        attributes={
            "provider_delivery": {"state": "sending", "channel": "web"},
            "ai_auto_authority": {"source_message_id": 12345},
        },
    )
    db.add(bot)
    db.commit()
    calls = []

    async def fake_downstream(_db, _session, payload):
        # Only the downstream external transport is substituted; guard,
        # query, canonical ORM persistence and two actual async recovery
        # coroutines remain real.
        calls.append(payload["message_id"])
        await asyncio.sleep(0.04)
        db.refresh(bot)
        bot.attributes = {
            **(bot.attributes or {}),
            "provider_delivery": {"state": "succeeded", "channel": "web"},
        }
        db.commit()
        return NS(ok=True)

    monkeypatch.setattr(delivery, "deliver_to_customer", fake_downstream)
    outcomes = await asyncio.wait_for(asyncio.gather(
        delivery.recover_pending_web_auto_messages(db, session),
        delivery.recover_pending_web_auto_messages(db, session),
    ), timeout=3)
    assert sorted(outcomes) == [0, 1]
    assert calls == [bot.id]
    db.refresh(bot)
    assert bot.attributes["provider_delivery"]["state"] == "succeeded"
    assert db.query(ChatHistory).filter(ChatHistory.id == bot.id).count() == 1
    assert await delivery.recover_pending_web_auto_messages(db, session) == 0


@pytest.mark.asyncio
async def test_recovery_no_authority_or_failed_state_never_replays(
    db, test_agent, test_customer, test_organization, monkeypatch
):
    session = SessionToAgent(
        session_id=uuid4(), organization_id=test_organization.id,
        agent_id=test_agent.id, customer_id=test_customer.id,
        status=SessionStatus.OPEN, channel="web",
    )
    db.add(session)
    bot = ChatHistory(
        message="Already finalized", message_type="bot",
        session_id=session.session_id, organization_id=test_organization.id,
        customer_id=test_customer.id, agent_id=test_agent.id,
        attributes={"provider_delivery": {"state": "succeeded", "channel": "web"},
                    "ai_auto_authority": {"source_message_id": 3}},
    )
    db.add(bot)
    db.commit()
    calls = []
    async def unexpected(*_args, **_kwargs):
        calls.append(True)
        return NS(ok=True)
    monkeypatch.setattr(delivery, "deliver_to_customer", unexpected)
    assert await delivery.recover_pending_web_auto_messages(db, session) == 0
    assert calls == []
