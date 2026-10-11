"""W445 personal TG/WA inbound safety policy: no auto-send or synthetic actor."""
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from tests.conftest import db, test_organization, test_agent  # use existing disposable SQLite ORM fixtures

from app.channels import get_adapter
from app.channels.personal_social.base import TransportSessionStatus
from app.channels.personal_social.native_bridge import (
    PersonalNativeError, ingest_live, personal_sessions,
)
from app.services import channel_chat, human_routing


@pytest.mark.parametrize("kind", ["telegram_user", "whatsapp_user"])
def test_personal_native_receive_only_authority_is_shared(kind):
    """Removing either ID causes this test and the actual ingress to fail."""
    policy = human_routing.RECEIVE_ONLY_SOCIAL_CHANNELS
    assert kind in policy
    assert channel_chat.RECEIVE_ONLY_SOCIAL_CHANNELS is policy
    assert get_adapter(kind).channel_type == kind
    assert all(x in policy for x in ("messenger", "whatsapp", "telegram", "instagram"))
    assert "web" not in policy


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["telegram_user", "whatsapp_user"])
async def test_personal_receipt_never_sends_human_ack_or_handover_notice(monkeypatch, kind):
    async def forbidden_delivery(*args, **kwargs):
        raise AssertionError("UNSOLICITED_PERSONAL_DELIVERY")
    monkeypatch.setattr(human_routing, "deliver_to_customer", forbidden_delivery)
    monkeypatch.setattr(human_routing, "ChatRepository",
                        lambda *_: (_ for _ in ()).throw(AssertionError("AUTO_NOTICE_PERSISTED")))
    session = SimpleNamespace(channel=kind)
    for only in (True, False):
        await human_routing.notify_customer(
            db=object(), session=session, message=human_routing.HUMAN_ONLY_ACK,
            channels_only=only
        )
        await human_routing.notify_customer(
            db=object(), session=session,
            message=human_routing.QUEUED_FOR_HUMAN_NOTICE,
            channels_only=only
        )


def _account(kind):
    return SimpleNamespace(
        id=uuid.uuid4(), organization_id=uuid.uuid4(), external_account_id=(
            "999@s.whatsapp.net" if kind == "whatsapp_user" else "123456"
        ), channel_type=kind, is_active=True,
    )


def _frame(account):
    if account.channel_type == "telegram_user":
        return {
            "organization_id": str(account.organization_id),
            "channel_account_id": str(account.id),
            "provider": "telegram", "account_kind": "personal",
            "external_conversation_id": "777",
            "external_message_id": "777:42", "sender_id": "321",
            "text": "real scoped message", "from_me": False,
            "is_customer_turn": True,
        }
    return {
        "event": "inbound", "accountId": str(account.id),
        "externalAccountId": account.external_account_id,
        "source": "live", "fromMe": False,
        "externalConversationId": "123456@s.whatsapp.net",
        "externalMessageId": "real42", "text": "real scoped message",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["telegram_user", "whatsapp_user"])
async def test_personal_ingress_only_calls_existing_canonical_channel_chat(monkeypatch, kind):
    """The only ingress owner is process_channel_message; never another DB."""
    account = _account(kind)
    msg = _frame(account)
    route = AsyncMock()
    monkeypatch.setattr(channel_chat, "process_channel_message", route)
    monkeypatch.setattr(personal_sessions, "status",
                        AsyncMock(return_value=TransportSessionStatus.CONNECTED))
    assert await ingest_live(account, msg) is True
    route.assert_awaited_once()
    canonical_account, received = route.await_args.args
    assert canonical_account == account.id
    assert received.text == "real scoped message"
    assert received.external_account_id == account.external_account_id
    assert received.external_message_id.endswith("42")
    # A second frame from a different account must fail before canonical access.
    bad = dict(msg)
    if kind == "telegram_user":
        bad["organization_id"] = str(uuid.uuid4())
    else:
        bad["accountId"] = str(uuid.uuid4())
    with pytest.raises(PersonalNativeError, match="SCOPE_OR_DIRECTION"):
        await ingest_live(account, bad)
    route.assert_awaited_once()
    monkeypatch.setattr(personal_sessions, "status",
                        AsyncMock(return_value=TransportSessionStatus.DISCONNECTED))
    with pytest.raises(PersonalNativeError, match="NOT_CONNECTED"):
        await ingest_live(account, msg)
    route.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["telegram_user", "whatsapp_user"])
async def test_real_canonical_db_message_is_stored_once_and_never_auto_sends(
        db, test_organization, test_agent, monkeypatch, kind):
    """Real existing ORM owners with a disposable test DB, no provider login."""
    from app.channels.base import InboundMessage
    from app.models.chat_history import ChatHistory
    from app.repositories.channels import ChannelAccountRepository, AgentChannelConfigRepository
    from unittest.mock import MagicMock, patch

    account = ChannelAccountRepository(db).create_account(
        organization_id=test_organization.id,
        channel_type=kind,
        external_account_id="999@s.whatsapp.net" if kind == "whatsapp_user" else "123456",
        credentials={},
        display_name="isolated-personal",
    )
    AgentChannelConfigRepository(db).set_agent(account.id, test_agent.id)

    class NonClosingSession:
        def __init__(self, inner):
            self._inner = inner
        def __getattr__(self, name):
            return getattr(self._inner, name)
        def close(self):
            pass

    monkeypatch.setattr(channel_chat, "SessionLocal", lambda: NonClosingSession(db))
    notifications = MagicMock()
    notifications.emit = AsyncMock()
    monkeypatch.setattr(channel_chat, "sio", notifications)

    inbound = InboundMessage(
        external_account_id=account.external_account_id,
        external_conversation_id=(
            "111@s.whatsapp.net" if kind == "whatsapp_user" else "777"
        ),
        external_user_id="111@s.whatsapp.net" if kind == "whatsapp_user" else "321",
        external_message_id=(
            "111@s.whatsapp.net:42" if kind == "whatsapp_user" else "777:42"
        ),
        text="canonical personal inbound",
        profile={"name": "Isolated customer"},
    )
    with patch.object(channel_chat.ChatAgent, "create_async", AsyncMock()) as model, \
         patch.object(channel_chat, "deliver_to_customer", AsyncMock()) as outgoing, \
         patch.object(channel_chat, "_send_via_adapter", AsyncMock()) as outbound_adapter:
        await channel_chat.process_channel_message(account.id, inbound)
        model.assert_not_awaited()
        outgoing.assert_not_awaited()
        outbound_adapter.assert_not_awaited()
        # A verified provider replay cannot persist a second canonical message.
        await channel_chat.process_channel_message(account.id, inbound)
        model.assert_not_awaited()
        outgoing.assert_not_awaited()
        outbound_adapter.assert_not_awaited()

    # ChatHistory.message is encrypted at rest, so its plaintext must NOT be
    # used as an SQL equality predicate. Use canonical provider identity.
    records = db.query(ChatHistory).filter(
        ChatHistory.provider_channel == kind,
        ChatHistory.external_account_id == account.external_account_id,
        ChatHistory.external_message_id == inbound.external_message_id,
    ).all()
    assert len(records) == 1
    assert records[0].message == "canonical personal inbound"
    assert records[0].message_type == "user"
    assert notifications.emit.await_count >= 1
