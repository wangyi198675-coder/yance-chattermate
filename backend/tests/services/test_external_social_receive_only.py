"""
Copyright 2024-2026 ChatterMate

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.orm import configure_mappers

from app.channels.base import InboundMessage
from app.models.channels import ChannelConversation
from app.models.chat_history import ChatHistory
from app.models.customer import Customer
from app.models.file_attachment import FileAttachment
from app.models.session_to_agent import SessionToAgent
from app.repositories.channels import (
    AgentChannelConfigRepository,
    ChannelAccountRepository,
)
from app.services import channel_chat
from app.services.channel_chat import process_channel_message

# SQLAlchemy-Continuum materializes its transaction/version tables when ORM
# mappers are configured. Do it during collection so the first SQLite fixture's
# Base.metadata.create_all() sees the same tables as later tests.
configure_mappers()


SOCIAL_CHANNELS = ("messenger", "whatsapp", "instagram", "telegram")


class _NonClosing:
    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def close(self):
        pass


def _make_inbound(channel, message_id="m1", text="hello", attachments=None):
    return InboundMessage(
        external_account_id=f"{channel}-account",
        external_conversation_id="conversation-1",
        external_user_id="customer-1",
        external_message_id=message_id,
        text=text,
        profile={"name": "Ada Lovelace"},
        attachments=list(attachments or []),
    )


def _make_account(db, test_organization, test_agent, channel):
    account = ChannelAccountRepository(db).create_account(
        organization_id=test_organization.id,
        channel_type=channel,
        external_account_id=f"{channel}-account",
        credentials={},
        display_name=f"test-{channel}",
    )
    AgentChannelConfigRepository(db).set_agent(account.id, test_agent.id)
    return account


def _adapter():
    adapter = MagicMock()
    adapter.conversation_state = MagicMock(return_value={})
    adapter.send_typing = AsyncMock()
    return adapter


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", SOCIAL_CHANNELS)
@pytest.mark.parametrize("ai_enabled", (False, True))
async def test_social_inbound_persists_relays_and_never_auto_sends(
    db, test_organization, test_agent, test_ai_config, monkeypatch, channel, ai_enabled
):
    account = _make_account(db, test_organization, test_agent, channel)
    test_agent.ai_replies_enabled = ai_enabled
    db.commit()

    adapter = _adapter()
    sio = MagicMock()
    sio.emit = AsyncMock()
    monkeypatch.setattr(channel_chat, "SessionLocal", lambda: _NonClosing(db))
    monkeypatch.setattr(channel_chat, "get_adapter", lambda _channel: adapter)
    monkeypatch.setattr(channel_chat, "sio", sio)

    with patch.object(channel_chat, "_run_chat_agent", new=AsyncMock()) as run_agent, \
         patch.object(channel_chat, "_deliver", new=AsyncMock()) as deliver, \
         patch.object(channel_chat, "_send_via_adapter", new=AsyncMock()) as service_send, \
         patch.object(channel_chat, "_send_channel_prompts", new=AsyncMock()) as prompts, \
         patch.object(channel_chat, "notify_customer", new=AsyncMock()) as notice:
        await process_channel_message(account.id, _make_inbound(channel))

    rows = db.query(ChatHistory).all()
    assert len(rows) == 1
    assert rows[0].message_type == "user"
    assert rows[0].provider_channel == channel
    assert rows[0].external_account_id == f"{channel}-account"
    assert rows[0].external_message_id == "m1"
    assert db.query(ChannelConversation).count() == 1
    assert db.query(Customer).count() == 1

    conversation = db.query(ChannelConversation).one()
    session = db.query(SessionToAgent).filter_by(
        session_id=conversation.session_id
    ).one()
    relays = [
        call for call in sio.emit.await_args_list
        if call.args and call.args[0] == "chat_reply"
    ]
    assert relays
    assert any(call.kwargs.get("room") == str(session.session_id) for call in relays)

    run_agent.assert_not_awaited()
    deliver.assert_not_awaited()
    service_send.assert_not_awaited()
    prompts.assert_not_awaited()
    notice.assert_not_awaited()
    adapter.send_typing.assert_not_awaited()
    assert db.query(ChatHistory).filter(
        ChatHistory.message_type.in_(("bot", "agent"))
    ).count() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("ai_enabled", (False, True))
async def test_messenger_existing_conversation_remains_receive_only(
    db, test_organization, test_agent, test_ai_config, monkeypatch, ai_enabled
):
    account = _make_account(db, test_organization, test_agent, "messenger")
    test_agent.ai_replies_enabled = ai_enabled
    db.commit()

    adapter = _adapter()
    sio = MagicMock()
    sio.emit = AsyncMock()
    monkeypatch.setattr(channel_chat, "SessionLocal", lambda: _NonClosing(db))
    monkeypatch.setattr(channel_chat, "get_adapter", lambda _channel: adapter)
    monkeypatch.setattr(channel_chat, "sio", sio)

    with patch.object(channel_chat, "_run_chat_agent", new=AsyncMock()) as run_agent, \
         patch.object(channel_chat, "_deliver", new=AsyncMock()) as deliver:
        await process_channel_message(account.id, _make_inbound("messenger", "m1", "first"))
        await process_channel_message(account.id, _make_inbound("messenger", "m2", "second"))

    assert db.query(ChannelConversation).count() == 1
    assert db.query(ChatHistory).filter_by(message_type="user").count() == 2
    run_agent.assert_not_awaited()
    deliver.assert_not_awaited()
    adapter.send_typing.assert_not_awaited()


@pytest.mark.asyncio
async def test_social_duplicate_provider_identity_stays_exactly_once(
    db, test_organization, test_agent, test_ai_config, monkeypatch
):
    account = _make_account(db, test_organization, test_agent, "messenger")
    adapter = _adapter()
    sio = MagicMock()
    sio.emit = AsyncMock()
    monkeypatch.setattr(channel_chat, "SessionLocal", lambda: _NonClosing(db))
    monkeypatch.setattr(channel_chat, "get_adapter", lambda _channel: adapter)
    monkeypatch.setattr(channel_chat, "sio", sio)

    inbound = _make_inbound("messenger", "same-mid")
    with patch.object(channel_chat, "_deliver", new=AsyncMock()) as deliver:
        await process_channel_message(account.id, inbound)
        await process_channel_message(account.id, inbound)

    assert db.query(ChatHistory).filter_by(
        provider_channel="messenger",
        external_account_id="messenger-account",
        external_message_id="same-mid",
    ).count() == 1
    deliver.assert_not_awaited()


@pytest.mark.asyncio
async def test_two_instagram_accounts_persist_separate_conversations_and_history(
    db, test_organization, test_agent, test_ai_config, monkeypatch
):
    """Same IGSID and MID on separate IG accounts must not collide."""
    first = _make_account(db, test_organization, test_agent, "instagram")
    repo = ChannelAccountRepository(db)
    second = repo.create_account(
        organization_id=test_organization.id,
        channel_type="instagram",
        external_account_id="instagram-sibling",
        credentials={"access_token": "token-B"},
        display_name="@sibling",
    )
    AgentChannelConfigRepository(db).set_agent(second.id, test_agent.id)

    adapter = _adapter()
    sio = MagicMock()
    sio.emit = AsyncMock()
    monkeypatch.setattr(channel_chat, "SessionLocal", lambda: _NonClosing(db))
    monkeypatch.setattr(channel_chat, "get_adapter", lambda _channel: adapter)
    monkeypatch.setattr(channel_chat, "sio", sio)

    inbound_a = _make_inbound("instagram", "same-mid", "from A")
    inbound_b = _make_inbound("instagram", "same-mid", "from B")
    inbound_b.external_account_id = "instagram-sibling"
    with patch.object(channel_chat, "notify_new_chat", new=AsyncMock()) as notice, \
         patch.object(channel_chat, "_deliver", new=AsyncMock()) as deliver:
        await process_channel_message(first.id, inbound_a)
        await process_channel_message(second.id, inbound_b)

    conversations = db.query(ChannelConversation).all()
    assert len(conversations) == 2
    assert {c.channel_account_id for c in conversations} == {first.id, second.id}
    assert conversations[0].session_id != conversations[1].session_id
    # Same IGSID is only meaningful inside its own professional account.
    # Separate sessions alone are insufficient if their Customer truth merges.
    assert conversations[0].customer_id != conversations[1].customer_id
    customers = db.query(Customer).filter(Customer.id.in_([
        c.customer_id for c in conversations
    ])).all()
    assert len(customers) == 2
    assert {c.email for c in customers} == {
        "instagram-account.customer-1@instagram.channel",
        "instagram-sibling.customer-1@instagram.channel",
    }
    histories = db.query(ChatHistory).filter_by(provider_channel="instagram").all()
    assert len(histories) == 2
    assert {h.external_account_id: h.message for h in histories} == {
        "instagram-account": "from A", "instagram-sibling": "from B"}
    assert notice.await_count == 2
    deliver.assert_not_awaited()

    assert repo.delete(first)
    assert repo.get_by_id(second.id) is not None
    surviving = db.query(ChannelConversation).filter_by(channel_account_id=second.id).one()
    assert surviving.session_id in {c.session_id for c in conversations}
    assert db.query(ChatHistory).filter_by(external_account_id="instagram-sibling").count() == 1


@pytest.mark.asyncio
async def test_social_media_is_materialized_before_receive_only_return(
    db, test_organization, test_agent, test_ai_config, monkeypatch
):
    account = _make_account(db, test_organization, test_agent, "messenger")
    adapter = _adapter()
    sio = MagicMock()
    sio.emit = AsyncMock()
    monkeypatch.setattr(channel_chat, "SessionLocal", lambda: _NonClosing(db))
    monkeypatch.setattr(channel_chat, "get_adapter", lambda _channel: adapter)
    monkeypatch.setattr(channel_chat, "sio", sio)

    async def materialize(_adapter, _account, inbound, _org_id):
        inbound.attachments = [{
            "provider_type": "image",
            "provider_id": "image-1",
            "file_url": "/uploads/image-1.jpg",
            "filename": "image-1.jpg",
            "content_type": "image/jpeg",
            "file_size": 3,
        }]

    inbound = _make_inbound(
        "messenger", "media-mid", attachments=[{"provider_type": "image", "provider_id": "image-1"}]
    )
    with patch.object(channel_chat, "_materialize_inbound_media", new=AsyncMock(side_effect=materialize)) as materializer, \
         patch.object(channel_chat, "_deliver", new=AsyncMock()) as deliver:
        await process_channel_message(account.id, inbound)

    materializer.assert_awaited_once()
    assert db.query(ChatHistory).filter_by(
        provider_channel="messenger", external_message_id="media-mid"
    ).count() == 1
    assert db.query(FileAttachment).count() == 1
    deliver.assert_not_awaited()
