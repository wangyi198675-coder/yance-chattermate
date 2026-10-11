"""W435 bounded native-account admission tests. No provider login or network."""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.channels import get_adapter
from app.models.channels import ChannelType
from app.channels.personal_social.base import TransportSessionStatus, TransportHealth
from app.channels.personal_social.native_bridge import (
    PersonalNativeError, PersonalSessionOwner, _inbound, ingest_live,
    make_personal_transport, personal_sessions, MAX_MEDIA_BYTES,
)


def account(kind=ChannelType.TELEGRAM_USER.value, org=None, uid=None, external="123456"):
    return SimpleNamespace(
        channel_type=kind, organization_id=org or uuid.uuid4(),
        id=uid or uuid.uuid4(), external_account_id=external, is_active=True,
    )


class FakeTransport:
    def __init__(self, identity, organization=None, *, connected=False):
        self.account_id = identity
        self.channel_account_id = identity
        self.organization_id = organization
        self.connected = connected
        self.calls = []
        self.content = b"hello"

    async def health(self):
        return TransportHealth(
            TransportSessionStatus.CONNECTED if self.connected else TransportSessionStatus.DISCONNECTED,
        )

    async def session_status(self):
        return (await self.health()).status

    async def connect(self):
        self.calls.append("connect")
        self.connected = True

    async def disconnect(self):
        self.calls.append("disconnect")
        self.connected = False

    async def close(self):
        self.calls.append("close")

    async def logout(self, **kwargs):
        self.calls.append(("logout", kwargs))
        self.connected = False

    async def media(self, reference):
        self.calls.append(("media", reference))
        return self.content

    async def reconnect(self):
        self.calls.append("reconnect")

    async def begin_qr_login(self, *, interactive_authorized=False):
        self.calls.append(("qr", interactive_authorized))

    async def next_login_challenge(self):
        return {"step": "real-provider-event"}

    async def auth_events(self):
        yield {"event": "qr", "source": "transport"}

    async def cancel_login(self):
        self.calls.append("cancel")


def test_exact_personal_identifiers_and_distinct_official_adapters():
    assert ChannelType.TELEGRAM_USER.value == "telegram_user"
    assert ChannelType.WHATSAPP_USER.value == "whatsapp_user"
    assert ChannelType.TELEGRAM_USER != ChannelType.TELEGRAM
    assert ChannelType.WHATSAPP_USER != ChannelType.WHATSAPP
    assert get_adapter("telegram").channel_type == "telegram"
    assert get_adapter("whatsapp").channel_type == "whatsapp"
    assert get_adapter("telegram_user").channel_type == "telegram_user"
    assert get_adapter("whatsapp_user").channel_type == "whatsapp_user"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["telegram_user", "whatsapp_user"])
async def test_no_webhook_or_unsafe_physical_egress(kind):
    adapter = get_adapter(kind)
    a = account(kind)
    assert await adapter.verify_webhook({}, b"message", a) is False
    assert adapter.parse_inbound({"event": "inbound"}) == []
    out = await adapter.send_text(a, SimpleNamespace(), "no real send")
    assert not out.ok and out.error == "PERSONAL_CANONICAL_ATTEMPT_ID_NOT_WIRED"
    media = await adapter.send_media(a, SimpleNamespace(), "file:///etc/passwd", "image/png")
    assert not media.ok and media.error == "PERSONAL_CANONICAL_MEDIA_BYTES_NOT_WIRED"


@pytest.mark.asyncio
async def test_no_implicit_login_cannot_bind_twice_or_mismatch_tenant():
    owner = PersonalSessionOwner()
    a = account()
    t = FakeTransport(str(a.id), str(a.organization_id))
    with pytest.raises(PersonalNativeError, match="AUTHORIZATION"):
        owner.bind(a, t)
    assert not t.calls
    owner.bind(a, t, user_authorized=True)
    assert await owner.status(a) == TransportSessionStatus.DISCONNECTED
    with pytest.raises(PersonalNativeError, match="ALREADY_BOUND"):
        owner.bind(a, t, user_authorized=True)
    sibling = account(uid=a.id, org=uuid.uuid4())
    with pytest.raises(PersonalNativeError, match="NOT_BOUND"):
        owner.get(sibling)
    with pytest.raises(PersonalNativeError, match="AUTHORIZATION"):
        await owner.connect(a)
    assert not t.calls
    await owner.connect(a, user_authorized=True)
    assert await owner.status(a) == TransportSessionStatus.CONNECTED
    with pytest.raises(PersonalNativeError, match="AUTHORIZATION"):
        await owner.logout(a)
    await owner.logout(a, user_authorized=True)
    assert t.calls == ["connect", ("logout", {"interactive_authorized": True})]
    assert await owner.status(a) == TransportSessionStatus.DISCONNECTED


@pytest.mark.asyncio
async def test_multiaccount_isolation_and_wa_logout_custody():
    owner = PersonalSessionOwner()
    a, b = account("whatsapp_user"), account("whatsapp_user")
    ta, tb = FakeTransport(str(a.id)), FakeTransport(str(b.id))
    owner.bind(a, ta, user_authorized=True)
    owner.bind(b, tb, user_authorized=True)
    assert owner.get(a) is ta and owner.get(b) is tb
    await owner.disconnect(a)
    assert ta.calls == ["disconnect", "close"]
    assert owner.get(b) is tb
    await owner.logout(b, user_authorized=True)
    assert tb.calls == [("logout", {})]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["telegram_user", "whatsapp_user"])
async def test_qr_reconnect_and_cancel_require_consent_and_preserve_real_events(kind):
    a = account(kind)
    t = FakeTransport(str(a.id), str(a.organization_id))
    owner = PersonalSessionOwner()
    owner.bind(a, t, user_authorized=True)
    with pytest.raises(PersonalNativeError, match="AUTHORIZATION"):
        await owner.begin_qr(a)
    with pytest.raises(PersonalNativeError, match="AUTHORIZATION"):
        await owner.reconnect(a)
    with pytest.raises(PersonalNativeError, match="AUTHORIZATION"):
        await owner.cancel_login(a)
    assert t.calls == []
    await owner.begin_qr(a, user_authorized=True)
    event = await owner.next_auth_event(a)
    await owner.reconnect(a, user_authorized=True)
    await owner.cancel_login(a, user_authorized=True)
    if kind == "telegram_user":
        assert event == {"step": "real-provider-event"}
        assert t.calls == [("qr", True), "reconnect", "disconnect"]
    else:
        assert event == {"event": "qr", "source": "transport"}
        assert t.calls == ["connect", "reconnect", "cancel"]


def test_telegram_composite_inbound_scope_and_provider_direction():
    a = account()
    frame = {
        "organization_id": str(a.organization_id),
        "channel_account_id": str(a.id), "provider": "telegram",
        "account_kind": "personal", "external_conversation_id": "777",
        "external_message_id": "777:42", "sender_id": "123",
        "text": "hi", "is_customer_turn": True, "from_me": False,
    }
    msg = _inbound(a, frame)
    assert msg.external_account_id == a.external_account_id
    assert msg.external_conversation_id == "777"
    assert msg.external_message_id == "777:42"
    for patch in (
        {"organization_id": str(uuid.uuid4())},
        {"channel_account_id": str(uuid.uuid4())},
        {"external_message_id": "42"},
        {"from_me": True},
        {"is_customer_turn": False},
        {"provider": "telegram-bot"},
    ):
        with pytest.raises(PersonalNativeError):
            _inbound(a, {**frame, **patch})


def test_wa_live_only_composite_id_and_distinct_personal_identity():
    a = account("whatsapp_user", external="999@s.whatsapp.net")
    frame = {
        "event": "inbound", "accountId": str(a.id),
        "externalAccountId": "999@s.whatsapp.net", "fromMe": False,
        "source": "live", "externalConversationId": "123456@s.whatsapp.net",
        "externalMessageId": "abcd", "text": "Hi", "kind": "text",
    }
    msg = _inbound(a, frame)
    assert msg.external_message_id == "123456@s.whatsapp.net:abcd"
    assert msg.external_account_id == "999@s.whatsapp.net"
    for patch in (
        {"accountId": str(uuid.uuid4())},
        {"externalAccountId": "another@s.whatsapp.net"},
        {"fromMe": True}, {"source": "history"},
        {"externalConversationId": "bad-jid"},
        {"externalMessageId": ""},
    ):
        with pytest.raises(PersonalNativeError):
            _inbound(a, {**frame, **patch})


@pytest.mark.asyncio
async def test_existing_human_only_gate_required_before_canonical_ingress(monkeypatch):
    a = account()
    frame = {
        "organization_id": str(a.organization_id),
        "channel_account_id": str(a.id), "provider": "telegram",
        "account_kind": "personal", "external_conversation_id": "777",
        "external_message_id": "777:42", "text": "hello",
        "from_me": False, "is_customer_turn": True,
    }
    import app.services.channel_chat as channel_chat
    from unittest.mock import AsyncMock
    from app.services.human_routing import RECEIVE_ONLY_SOCIAL_CHANNELS
    assert a.channel_type in RECEIVE_ONLY_SOCIAL_CHANNELS
    assert channel_chat.RECEIVE_ONLY_SOCIAL_CHANNELS is RECEIVE_ONLY_SOCIAL_CHANNELS
    delivered_to_canonical = AsyncMock()
    monkeypatch.setattr(channel_chat, "process_channel_message", delivered_to_canonical)
    monkeypatch.setattr(personal_sessions, "status",
                        AsyncMock(return_value=TransportSessionStatus.CONNECTED))
    assert await ingest_live(a, frame) is True
    delivered_to_canonical.assert_awaited_once()
    actual_account, actual_inbound = delivered_to_canonical.await_args.args
    assert actual_account == a.id
    assert actual_inbound.external_account_id == a.external_account_id
    assert actual_inbound.external_message_id == "777:42"
    assert actual_inbound.text == "hello"
    # The verified provider connection and tenant check are not optional.
    monkeypatch.setattr(personal_sessions, "status",
                        AsyncMock(return_value=TransportSessionStatus.DISCONNECTED))
    with pytest.raises(PersonalNativeError, match="NOT_CONNECTED"):
        await ingest_live(a, frame)
    delivered_to_canonical.assert_awaited_once()


@pytest.mark.asyncio
async def test_native_media_is_bound_to_account_and_real_live_transport():
    a = account()
    t = FakeTransport(str(a.id), str(a.organization_id), connected=True)
    personal_sessions.bind(a, t, user_authorized=True)
    try:
        adapter = get_adapter("telegram_user")
        result = await adapter.fetch_inbound_media(
            a, {"provider_id": "123:8", "filename": "voice.ogg", "content_type": "audio/ogg"})
        assert result.content == b"hello" and result.filename == "voice.ogg"
        assert t.calls == [("media", "123:8")]
        t.content = b"x" * (MAX_MEDIA_BYTES + 1)
        with pytest.raises(PersonalNativeError, match="MEDIA_SIZE"):
            await adapter.fetch_inbound_media(a, {"provider_id": "123:8"})
        a.is_active = False
        with pytest.raises(PersonalNativeError, match="INACTIVE"):
            await adapter.fetch_inbound_media(a, {"provider_id": "123:8"})
        a.is_active = True
    finally:
        await personal_sessions.disconnect(a)


def test_no_unqualified_private_runtime_and_no_official_transport_swap():
    a = account()
    with pytest.raises(PersonalNativeError, match="PRIVATE_NODE"):
        make_personal_transport(a, node_executable="node")
    with pytest.raises(PersonalNativeError, match="NOT_A_PERSONAL"):
        make_personal_transport(account("telegram"), node_executable="node")
