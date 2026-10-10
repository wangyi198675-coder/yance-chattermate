"""Window217: bounded Slack workspace isolation regressions (no live credentials)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest

import app.api.channels.slack as oauth
import app.api.webhooks.slack as webhook
import app.channels.slack as provider
import app.services.channel_chat as channel_chat
import app.services.chat_notifications as notification
from app.channels.base import InboundMessage
from fastapi import BackgroundTasks


@pytest.mark.asyncio
async def test_oauth_two_teams_and_reinstall_exact_account(monkeypatch):
    org = uuid4()
    payloads = iter([
        {"ok": True, "team": {"id": "T_A", "name": "Alpha"}, "access_token": "token-a"},
        {"ok": True, "team": {"id": "T_B", "name": "Beta"}, "access_token": "token-b"},
        {"ok": True, "team": {"id": "T_A", "name": "Alpha"}, "access_token": "token-a2"},
    ])
    accounts = {}

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, *args, **kwargs):
            return SimpleNamespace(json=lambda: next(payloads))

    class Repo:
        def __init__(self, db):
            pass

        def get_by_external_id(self, channel, team_id):
            assert channel == "slack"
            return accounts.get(team_id)

        def create_account(self, organization_id, channel_type, external_account_id, credentials, display_name):
            account = SimpleNamespace(
                id=uuid4(), organization_id=organization_id,
                external_account_id=external_account_id, credentials=credentials.copy(),
                display_name=display_name, is_active=True,
            )
            accounts[external_account_id] = account
            return account

        def update_credentials(self, account, credentials):
            account.credentials = credentials.copy()
            return account

        def set_active(self, account, active):
            account.is_active = active
            return account

    monkeypatch.setattr(oauth, "_pop_state", lambda _: str(org))
    monkeypatch.setattr(oauth.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(oauth, "ChannelAccountRepository", Repo)

    a = await oauth.slack_oauth_callback(code="a", state="valid", db=MagicMock())
    a_id = accounts["T_A"].id
    assert parse_qs(urlparse(a.headers["location"]).query)["account_id"] == [str(a_id)]

    b = await oauth.slack_oauth_callback(code="b", state="valid", db=MagicMock())
    b_id = accounts["T_B"].id
    assert a_id != b_id
    assert parse_qs(urlparse(b.headers["location"]).query)["account_id"] == [str(b_id)]

    await oauth.slack_oauth_callback(code="a2", state="valid", db=MagicMock())
    assert accounts["T_A"].id == a_id
    assert accounts["T_B"].id == b_id
    assert accounts["T_A"].credentials["access_token"] == "token-a2"
    assert accounts["T_B"].credentials["access_token"] == "token-b"


@pytest.mark.asyncio
async def test_oauth_rejects_missing_team_or_token(monkeypatch):
    org = uuid4()
    payloads = iter([
        {"ok": True, "team": {}, "access_token": "token"},
        {"ok": True, "team": {"id": "T_A"}, "access_token": ""},
    ])

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, *args, **kwargs):
            return SimpleNamespace(json=lambda: next(payloads))

    monkeypatch.setattr(oauth, "_pop_state", lambda _: str(org))
    monkeypatch.setattr(oauth.httpx, "AsyncClient", FakeClient)
    repo = MagicMock()
    monkeypatch.setattr(oauth, "ChannelAccountRepository", lambda _: repo)

    for reason in ("missing_team_id", "missing_bot_token"):
        response = await oauth.slack_oauth_callback(code="valid", state="valid", db=MagicMock())
        assert parse_qs(urlparse(response.headers["location"]).query)["reason"] == [reason]
    repo.create_account.assert_not_called()
    repo.update_credentials.assert_not_called()


@pytest.mark.asyncio
async def test_signed_workspace_envelope_selects_exact_account(monkeypatch):
    a, b = SimpleNamespace(id=uuid4(), is_active=True), SimpleNamespace(id=uuid4(), is_active=True)
    repo = MagicMock()
    repo.get_by_external_id.side_effect = lambda _, team: {"T_A": a, "T_B": b}.get(team)
    monkeypatch.setattr(webhook, "verify_slack_signature", lambda *args: True)
    monkeypatch.setattr(webhook, "is_duplicate_message", lambda *args: False)
    monkeypatch.setattr(webhook, "ChannelAccountRepository", lambda db: repo)

    for team, expected in (("T_A", a), ("T_B", b)):
        request = MagicMock()
        request.body = AsyncMock(return_value=b"{}")
        request.json = AsyncMock(return_value={
            "type": "event_callback", "team_id": team, "event_id": "Ev_1",
            "event": {"type": "message", "channel_type": "im", "channel": "D_shared",
                      "user": "U_shared", "text": "hi", "ts": "1720000001.000200"},
        })
        tasks = BackgroundTasks()
        result = await webhook.slack_webhook(request, tasks, MagicMock())
        assert result == {"status": "ok"}
        assert len(tasks.tasks) == 1
        assert tasks.tasks[0].args[0] == expected.id
        assert tasks.tasks[0].args[1].external_account_id == team


@pytest.mark.asyncio
async def test_send_uses_exact_workspace_token_even_for_same_dm(monkeypatch):
    calls = []

    async def fake_api(method, token, payload, form=False):
        calls.append((method, token, payload["channel"]))
        return {"ok": True, "ts": "1.1"}

    monkeypatch.setattr(provider, "slack_api", fake_api)
    monkeypatch.setattr(provider.SlackAdapter, "_access_token",
                        staticmethod(lambda account: account.token))
    adapter = provider.SlackAdapter()
    conversation = SimpleNamespace(external_conversation_id="D_shared")
    for token in ("token-a", "token-b"):
        result = await adapter.send_text(SimpleNamespace(id=uuid4(), token=token),
                                         conversation, "hello")
        assert result.ok
    assert calls == [
        ("chat.postMessage", "token-a", "D_shared"),
        ("chat.postMessage", "token-b", "D_shared"),
    ]


@pytest.mark.asyncio
async def test_disconnect_one_workspace_does_not_delete_sibling(monkeypatch):
    a, b = SimpleNamespace(id=uuid4(), channel_type="slack"), SimpleNamespace(id=uuid4(), channel_type="slack")
    repo = MagicMock()
    repo.delete.return_value = True
    monkeypatch.setattr(oauth, "ChannelAccountRepository", lambda db: repo)
    monkeypatch.setattr(oauth, "get_org_account_or_404", lambda *args: a)
    revoke = AsyncMock()
    monkeypatch.setattr(oauth, "_revoke_token", revoke)
    assert await oauth.disconnect_slack(a.id, db=MagicMock(), organization=MagicMock()) == {"status": "disconnected"}
    repo.delete.assert_called_once_with(a)
    revoke.assert_awaited_once()
    assert b.id != a.id


def test_same_slack_user_id_is_not_same_customer_between_teams(monkeypatch):
    repo = MagicMock()
    repo.get_or_create_customer.return_value = SimpleNamespace(id=uuid4(), full_name="Ada")
    monkeypatch.setattr(channel_chat, "CustomerRepository", lambda db: repo)
    inbound = InboundMessage(external_account_id="T_A", external_conversation_id="D1",
                             external_user_id="U_same", external_message_id="Ev1", text="hi")
    organization_id = str(uuid4())
    for team in ("T_A", "T_B"):
        account = SimpleNamespace(channel_type="slack", external_account_id=team)
        channel_chat._get_or_create_customer(MagicMock(), account, inbound, organization_id)
    emails = [c.kwargs["email"] for c in repo.get_or_create_customer.call_args_list]
    assert emails == ["t_a.u_same@slack.channel", "t_b.u_same@slack.channel"]


def test_slack_notification_carries_canonical_account_and_conversation(monkeypatch):
    organization_id, session_id = uuid4(), uuid4()
    account = SimpleNamespace(id=uuid4(), channel_type="slack", external_account_id="T_A",
                              organization_id=organization_id)
    convo = SimpleNamespace(id=uuid4(), channel_account_id=account.id, session_id=session_id,
                            channel_type="slack", organization_id=organization_id)
    monkeypatch.setattr(notification, "ChannelConversationRepository",
                        lambda db: SimpleNamespace(get_unique_by_session=lambda _: convo))
    monkeypatch.setattr(notification, "ChannelAccountRepository",
                        lambda db: SimpleNamespace(get_by_id=lambda _: account))
    metadata = notification.chat_notification_metadata(MagicMock(), SimpleNamespace(
        session_id=session_id, channel="slack", organization_id=organization_id))
    assert metadata == {"session_id": str(session_id), "channel_account_id": str(account.id),
                        "channel_conversation_id": str(convo.id), "external_account_id": "T_A"}


@pytest.mark.asyncio
async def test_wrong_workspace_is_rejected_before_chat_or_send(monkeypatch):
    db = MagicMock()
    monkeypatch.setattr(channel_chat, "SessionLocal", lambda: db)
    account = SimpleNamespace(channel_type="slack", is_active=True, external_account_id="T_A")
    monkeypatch.setattr(channel_chat, "ChannelAccountRepository",
                        lambda _: SimpleNamespace(get_by_id=lambda _: account))
    chat_repo = MagicMock()
    monkeypatch.setattr(channel_chat, "ChatRepository", lambda _: chat_repo)
    inbound = InboundMessage(external_account_id="T_B", external_conversation_id="D_same",
                             external_user_id="U", external_message_id="Ev", text="hi")
    await channel_chat.process_channel_message(uuid4(), inbound)
    chat_repo.provider_message_exists.assert_not_called()
    db.close.assert_called_once()
