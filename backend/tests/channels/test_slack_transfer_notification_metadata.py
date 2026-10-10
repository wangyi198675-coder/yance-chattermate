"""Window240: exact Slack Workspace identity in all chat notification paths."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

import app.agents.chat_agent as chat_agent
import app.services.chat_notifications as notices
import app.services.human_routing as human
from app.models.schemas.chat import ChatResponse, TransferReasonType
from app.models.session_to_agent import SessionStatus
from app.services.notifications import ChatNotificationEvent


@pytest.fixture
def workspace_links(monkeypatch):
    """Same org and Slack user ID; only session->conversation selects A or B."""
    org_id = uuid4()
    sessions = {}
    conversations = {}
    accounts = {}
    for team in ("T_A", "T_B"):
        session = SimpleNamespace(
            session_id=uuid4(), organization_id=org_id, channel="slack",
            user_id=None, status=SessionStatus.OPEN, group_id=None,
            external_user_id="U_SHARED",
        )
        account = SimpleNamespace(
            id=uuid4(), organization_id=org_id, channel_type="slack",
            external_account_id=team,
        )
        conversation = SimpleNamespace(
            id=uuid4(), session_id=session.session_id, organization_id=org_id,
            channel_type="slack", channel_account_id=account.id,
            external_user_id="U_SHARED",
        )
        sessions[team] = session
        conversations[session.session_id] = conversation
        accounts[account.id] = account

    class ConversationRepo:
        def __init__(self, db):
            pass

        def get_unique_by_session(self, session_id):
            return conversations.get(session_id)

    class AccountRepo:
        def __init__(self, db):
            pass

        def get_by_id(self, account_id):
            return accounts.get(account_id)

    monkeypatch.setattr(notices, "ChannelConversationRepository", ConversationRepo)
    monkeypatch.setattr(notices, "ChannelAccountRepository", AccountRepo)
    return sessions, conversations, accounts


def _expected(session, conversations, accounts):
    conversation = conversations[session.session_id]
    account = accounts[conversation.channel_account_id]
    return {
        "session_id": str(session.session_id),
        "channel_conversation_id": str(conversation.id),
        "channel_account_id": str(account.id),
        "external_account_id": account.external_account_id,
    }


def test_notification_metadata_scopes_shared_slack_user_to_exact_workspace(workspace_links):
    sessions, conversations, accounts = workspace_links
    db = MagicMock()
    for team in ("T_A", "T_B"):
        assert notices.chat_notification_metadata(db, sessions[team]) == _expected(
            sessions[team], conversations, accounts
        )
    assert sessions["T_A"].external_user_id == sessions["T_B"].external_user_id
    assert conversations[sessions["T_A"].session_id].channel_account_id != (
        conversations[sessions["T_B"].session_id].channel_account_id
    )


@pytest.mark.parametrize("broken", [
    "missing_conversation", "wrong_session", "wrong_conversation_org",
    "wrong_channel", "missing_account", "wrong_account_id",
    "wrong_account_org", "wrong_account_type", "missing_team_id",
])
def test_missing_or_invalid_linkage_never_uses_sibling_identity(workspace_links, broken):
    sessions, conversations, accounts = workspace_links
    session = sessions["T_A"]
    conversation = conversations[session.session_id]
    account = accounts[conversation.channel_account_id]
    if broken == "missing_conversation":
        conversations.pop(session.session_id)
    elif broken == "wrong_session":
        conversation.session_id = sessions["T_B"].session_id
    elif broken == "wrong_conversation_org":
        conversation.organization_id = uuid4()
    elif broken == "wrong_channel":
        conversation.channel_type = "telegram"
    elif broken == "missing_account":
        accounts.pop(account.id)
    elif broken == "wrong_account_id":
        account.id = uuid4()
    elif broken == "wrong_account_org":
        account.organization_id = uuid4()
    elif broken == "wrong_account_type":
        account.channel_type = "messenger"
    elif broken == "missing_team_id":
        account.external_account_id = ""
    assert notices.chat_notification_metadata(MagicMock(), session) == {
        "session_id": str(session.session_id)
    }


@pytest.mark.asyncio
async def test_new_chat_and_assigned_keep_same_canonical_identity(monkeypatch, workspace_links):
    sessions, conversations, accounts = workspace_links
    recipient = SimpleNamespace(id=uuid4())
    monkeypatch.setattr(notices, "UserRepository", lambda db: SimpleNamespace(
        get_users_with_any_permission=lambda *args: [recipient],
    ))
    emit = AsyncMock()
    monkeypatch.setattr(notices, "notify_chat_event", emit)
    db = MagicMock()
    for team in ("T_A", "T_B"):
        session = sessions[team]
        expected = _expected(session, conversations, accounts)
        await notices.notify_new_chat(db, session)
        assert emit.await_args.kwargs["event"] == ChatNotificationEvent.NEW_CHAT
        assert emit.await_args.kwargs["metadata"] == expected
        await notices.notify_chat_assigned(db, session, recipient.id)
        assert emit.await_args.kwargs["event"] == ChatNotificationEvent.CHAT_ASSIGNED
        assert emit.await_args.kwargs["metadata"] == expected


@pytest.mark.asyncio
async def test_human_route_transfer_metadata_is_workspace_scoped(monkeypatch, workspace_links):
    sessions, conversations, accounts = workspace_links
    monkeypatch.setattr(human, "SessionToAgentRepository", lambda db: SimpleNamespace(
        update_session=lambda *args: True,
    ))
    monkeypatch.setattr(human, "_transfer_recipients", lambda *args: [uuid4()])
    emit = AsyncMock()
    monkeypatch.setattr(human, "notify_chat_event", emit)
    monkeypatch.setattr(human, "notify_customer", AsyncMock())
    for team in ("T_A", "T_B"):
        session = sessions[team]
        assert await human.route_session_to_human(
            MagicMock(), session, reason="DIRECT_REQUEST", description="please take over"
        )
        assert emit.await_args.kwargs["event"] == ChatNotificationEvent.CHAT_TRANSFER
        assert emit.await_args.kwargs["metadata"] == {
            **_expected(session, conversations, accounts),
            "transfer_reason": "DIRECT_REQUEST",
            "transfer_description": "please take over",
        }


@pytest.mark.asyncio
@pytest.mark.parametrize("workflow_transfer", (False, True))
async def test_agent_transfer_metadata_is_workspace_scoped(
    monkeypatch, workspace_links, workflow_transfer
):
    sessions, conversations, accounts = workspace_links
    current = {"session": None}

    class SessionRepo:
        def __init__(self, db):
            pass

        def update_session(self, *args):
            return True

        def get_session(self, session_id):
            session = current["session"]
            return session if str(session.session_id) == str(session_id) else None

    monkeypatch.setattr(chat_agent, "SessionToAgentRepository", SessionRepo)
    monkeypatch.setattr(chat_agent, "notify_chat_event", AsyncMock())
    monkeypatch.setattr(
        chat_agent, "get_agent_availability_response",
        AsyncMock(return_value={"message": "A human can help.", "transfer_to_human": True}),
    )
    group_id = uuid4()
    self = SimpleNamespace(
        agent_data=SimpleNamespace(groups=[SimpleNamespace(id=group_id)]),
        api_key=None, model_name="test", model_type="test", base_url=None,
    )
    db = MagicMock()
    db.query.return_value.join.return_value.filter.return_value.all.return_value = [
        SimpleNamespace(id=uuid4())
    ]
    repo = MagicMock()
    repo.get_session_history = AsyncMock(return_value=[])
    response = ChatResponse(
        message="handoff", transfer_to_human=True,
        transfer_reason=TransferReasonType.DIRECT_REQUEST,
        transfer_description="workflow needs a person",
    )
    for team in ("T_A", "T_B"):
        session = sessions[team]
        current["session"] = session
        await chat_agent.ChatAgent._handle_transfer(
            self, response, str(session.session_id), str(session.organization_id),
            str(uuid4()), str(uuid4()), db, repo,
            transfer_group_id=group_id if workflow_transfer else None,
        )
        metadata = chat_agent.notify_chat_event.await_args.kwargs["metadata"]
        assert metadata == {
            **_expected(session, conversations, accounts),
            "transfer_reason": "DIRECT_REQUEST",
            "transfer_description": "workflow needs a person",
        }

    # A lookup for A must never borrow B's channel identity when A is absent.
    current["session"] = sessions["T_B"]
    missing_session_id = sessions["T_A"].session_id
    await chat_agent.ChatAgent._handle_transfer(
        self, response, str(missing_session_id), str(sessions["T_A"].organization_id),
        str(uuid4()), str(uuid4()), db, repo,
        transfer_group_id=group_id if workflow_transfer else None,
    )
    assert chat_agent.notify_chat_event.await_args.kwargs["metadata"] == {
        "session_id": str(missing_session_id),
        "transfer_reason": "DIRECT_REQUEST",
        "transfer_description": "workflow needs a person",
    }


@pytest.mark.asyncio
async def test_missing_transfer_linkage_still_has_deeplink_and_reason(monkeypatch, workspace_links):
    sessions, conversations, accounts = workspace_links
    session = sessions["T_A"]
    conversations.pop(session.session_id)
    monkeypatch.setattr(human, "SessionToAgentRepository", lambda db: SimpleNamespace(
        update_session=lambda *args: True,
    ))
    monkeypatch.setattr(human, "_transfer_recipients", lambda *args: [uuid4()])
    emit = AsyncMock()
    monkeypatch.setattr(human, "notify_chat_event", emit)
    monkeypatch.setattr(human, "notify_customer", AsyncMock())
    assert await human.route_session_to_human(
        MagicMock(), session, reason="DIRECT_REQUEST", description="handoff",
    )
    assert emit.await_args.kwargs["metadata"] == {
        "session_id": str(session.session_id),
        "transfer_reason": "DIRECT_REQUEST",
        "transfer_description": "handoff",
    }
