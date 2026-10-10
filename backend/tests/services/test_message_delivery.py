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

from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.channels.base import SendResult, WindowStatus
from app.repositories.channels import ChannelAccountRepository, ChannelConversationRepository
from app.repositories.session_to_agent import SessionToAgentRepository
from app.services import message_delivery
from app.services.message_delivery import deliver_to_customer


@pytest.fixture
def mock_sio(monkeypatch):
    sio = MagicMock()
    sio.emit = AsyncMock()
    monkeypatch.setattr(message_delivery, "sio", sio)
    return sio


def make_session(db, test_agent, test_customer, test_organization, channel):
    return SessionToAgentRepository(db).create_session(
        session_id=uuid4(),
        agent_id=test_agent.id,
        customer_id=test_customer.id,
        organization_id=test_organization.id,
        channel=channel,
    )


def make_channel_session(db, test_agent, test_customer, test_organization):
    session = make_session(db, test_agent, test_customer, test_organization, 'telegram')
    account = ChannelAccountRepository(db).create_account(
        organization_id=test_organization.id,
        channel_type='telegram',
        external_account_id='bot123',
        credentials={'bot_token': '123:abc'},
        display_name='@testbot',
    )
    ChannelConversationRepository(db).create(
        channel_account_id=account.id,
        channel_type='telegram',
        external_conversation_id='222',
        external_user_id='111',
        session_id=session.session_id,
        organization_id=test_organization.id,
        agent_id=test_agent.id,
        customer_id=test_customer.id,
    )
    return session, account




@pytest.mark.asyncio
async def test_web_session_uses_socket_emit_only(db, test_agent, test_customer, test_organization, mock_sio):
    session = make_session(db, test_agent, test_customer, test_organization, 'web')
    result = await deliver_to_customer(db, session, {'message': 'hi'})
    assert result.ok is True
    mock_sio.emit.assert_awaited_once_with(
        'chat_response', {'message': 'hi'}, room=str(session.session_id), namespace='/widget')


@pytest.mark.asyncio
async def test_channel_session_routes_to_adapter(db, test_agent, test_customer, test_organization, mock_sio, monkeypatch):
    session, _ = make_channel_session(db, test_agent, test_customer, test_organization)
    adapter = MagicMock()
    adapter.check_delivery_window.return_value = WindowStatus.OK
    adapter.format_outbound.side_effect = lambda t: t
    adapter.send_text = AsyncMock(return_value=SendResult(ok=True))
    monkeypatch.setattr(message_delivery, "get_adapter", lambda c: adapter)

    result = await deliver_to_customer(db, session, {'message': 'hello'})

    assert result.ok is True
    adapter.send_text.assert_awaited_once()
    assert adapter.send_text.await_args.args[2] == 'hello'
    mock_sio.emit.assert_awaited_once()  # dashboard viewers still get the event


@pytest.mark.asyncio
async def test_channel_session_window_expired(db, test_agent, test_customer, test_organization, mock_sio, monkeypatch):
    session, _ = make_channel_session(db, test_agent, test_customer, test_organization)
    adapter = MagicMock()
    adapter.check_delivery_window.return_value = WindowStatus.TEMPLATE_REQUIRED
    adapter.send_text = AsyncMock()
    monkeypatch.setattr(message_delivery, "get_adapter", lambda c: adapter)

    result = await deliver_to_customer(db, session, {'message': 'hello'})

    assert result.ok is False
    assert result.reason == 'window_expired'
    assert result.can_template is True
    adapter.send_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_channel_session_without_conversation_fails(db, test_agent, test_customer, test_organization, mock_sio, monkeypatch):
    session = make_session(db, test_agent, test_customer, test_organization, 'telegram')
    monkeypatch.setattr(message_delivery, "get_adapter", lambda c: MagicMock())

    result = await deliver_to_customer(db, session, {'message': 'hello'})

    assert result.ok is False
    assert result.reason == 'no_channel_conversation'


@pytest.mark.asyncio
async def test_send_failure_reported(db, test_agent, test_customer, test_organization, mock_sio, monkeypatch):
    session, _ = make_channel_session(db, test_agent, test_customer, test_organization)
    adapter = MagicMock()
    adapter.check_delivery_window.return_value = WindowStatus.OK
    adapter.format_outbound.side_effect = lambda t: t
    adapter.send_text = AsyncMock(return_value=SendResult(ok=False, error='chat not found'))
    monkeypatch.setattr(message_delivery, "get_adapter", lambda c: adapter)

    result = await deliver_to_customer(db, session, {'message': 'hello'})

    assert result.ok is False
    assert result.reason == 'chat not found'

@pytest.mark.asyncio
async def test_attachment_only_routes_to_adapter_send_media(
        db, test_agent, test_customer, test_organization, mock_sio, monkeypatch):
    session, _ = make_channel_session(db, test_agent, test_customer, test_organization)
    adapter = MagicMock()
    adapter.check_delivery_window.return_value = WindowStatus.OK
    adapter.format_outbound.side_effect = lambda t: t
    adapter.send_text = AsyncMock(return_value=SendResult(ok=True))
    adapter.send_media = AsyncMock(return_value=SendResult(ok=True, external_message_id="m-media"))
    monkeypatch.setattr(message_delivery, "get_adapter", lambda c: adapter)

    result = await deliver_to_customer(db, session, {"attachments": [{
        "file_url": "https://cdn.example/photo.jpg", "content_type": "image/jpeg",
        "filename": "photo.jpg", "file_size": 123,
    }]})

    assert result.ok is True
    adapter.send_text.assert_not_awaited()
    adapter.send_media.assert_awaited_once()
    assert adapter.send_media.await_args.args[2:] == (
        "https://cdn.example/photo.jpg", "image/jpeg")


@pytest.mark.asyncio
async def test_text_and_attachment_routes_both_native_sends(
        db, test_agent, test_customer, test_organization, mock_sio, monkeypatch):
    session, _ = make_channel_session(db, test_agent, test_customer, test_organization)
    adapter = MagicMock()
    adapter.check_delivery_window.return_value = WindowStatus.OK
    adapter.format_outbound.side_effect = lambda t: t
    adapter.send_text = AsyncMock(return_value=SendResult(ok=True, external_message_id="m-text"))
    adapter.send_media = AsyncMock(return_value=SendResult(ok=True, external_message_id="m-media"))
    monkeypatch.setattr(message_delivery, "get_adapter", lambda c: adapter)

    result = await deliver_to_customer(db, session, {
        "message": "caption", "attachments": [{
            "file_url": "https://cdn.example/report.pdf", "content_type": "application/pdf"}]})

    assert result.ok is True
    adapter.send_text.assert_awaited_once()
    adapter.send_media.assert_awaited_once()


@pytest.mark.asyncio
async def test_media_provider_failure_is_reported_fail_closed(
        db, test_agent, test_customer, test_organization, mock_sio, monkeypatch):
    session, _ = make_channel_session(db, test_agent, test_customer, test_organization)
    adapter = MagicMock()
    adapter.check_delivery_window.return_value = WindowStatus.OK
    adapter.format_outbound.side_effect = lambda t: t
    adapter.send_text = AsyncMock(return_value=SendResult(ok=True))
    adapter.send_media = AsyncMock(return_value=SendResult(ok=False, error="provider rejected media"))
    monkeypatch.setattr(message_delivery, "get_adapter", lambda c: adapter)

    result = await deliver_to_customer(db, session, {"attachments": [{
        "file_url": "https://cdn.example/photo.jpg", "content_type": "image/jpeg"}]})

    assert result.ok is False
    assert result.reason == "provider rejected media"


@pytest.mark.asyncio
async def test_whatsapp_template_succeeded_intent_replay_never_resends(monkeypatch):
    from types import SimpleNamespace

    receipt = {
        "kind": "template",
        "index": 0,
        "ok": True,
        "external_message_id": "wamid.REPLAY",
    }
    message = SimpleNamespace(
        id=123,
        attributes={
            "outbound_template": "hello_world",
            "provider_delivery": {
                "state": "succeeded",
                "receipts": [receipt],
            },
        },
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = message

    conversation = SimpleNamespace(channel_account_id=uuid4())
    account = SimpleNamespace(is_active=True)
    monkeypatch.setattr(
        message_delivery,
        "ChannelConversationRepository",
        lambda _db: SimpleNamespace(get_by_session=lambda _sid: conversation),
    )
    monkeypatch.setattr(
        message_delivery,
        "ChannelAccountRepository",
        lambda _db: SimpleNamespace(get_by_id=lambda _id: account),
    )

    adapter = MagicMock()
    adapter.send_template = AsyncMock()
    monkeypatch.setattr(message_delivery, "get_adapter", lambda _channel: adapter)
    session = SimpleNamespace(session_id=uuid4())

    replay = await message_delivery._deliver_to_channel(
        db,
        session,
        "whatsapp",
        {
            "message_id": 123,
            "message": "Hello",
            "template": {
                "name": "hello_world",
                "language": "en_US",
                "components": None,
            },
        },
    )

    assert replay.ok is True
    assert replay.reason == "already_delivered"
    assert replay.provider_receipts == [receipt]
    adapter.send_template.assert_not_awaited()
