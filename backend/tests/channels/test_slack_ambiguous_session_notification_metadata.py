"""Window256: Slack notification identity must not select an ambiguous sibling Workspace."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

import app.services.chat_notifications as notices
import app.services.human_routing as human
import app.agents.chat_agent as chat_agent
from app.models.channels.channel_conversation import ChannelConversation
from app.models.schemas.chat import ChatResponse, TransferReasonType
from app.models.session_to_agent import SessionStatus
from app.repositories.channels.conversations import ChannelConversationRepository
from app.services.notifications import ChatNotificationEvent


class SessionRows:
    """Execute repository's real bounded query on modeled rows, not a mocked winner."""
    def __init__(self, rows):
        self.rows = rows
        self.session_id = None
        self.bound = None

    def filter(self, criterion):
        self.session_id = criterion.right.value
        return self

    def limit(self, n):
        assert n == 2, "notification identity must check for duplicate sessions"
        self.bound = n
        return self

    def all(self):
        assert self.bound == 2, "must not choose .first() / newest"
        return [row for row in self.rows if row.session_id == self.session_id][:self.bound]


@pytest.fixture
def links(monkeypatch):
    org, sid = uuid4(), uuid4()
    session = SimpleNamespace(
        session_id=sid, organization_id=org, channel="slack",
        external_user_id="U_SAME", user_id=None, status=SessionStatus.OPEN,
        group_id=None,
    )
    accounts = {}
    conversations = {}
    for team in ("T_ALPHA", "T_BRAVO"):
        account = SimpleNamespace(
            id=uuid4(), organization_id=org, channel_type="slack",
            external_account_id=team, is_active=True,
        )
        conversation = SimpleNamespace(
            id=uuid4(), channel_account_id=account.id, session_id=sid,
            organization_id=org, channel_type="slack",
            external_user_id="U_SAME", external_conversation_id="D_SAME",
        )
        accounts[account.id] = account
        conversations[team] = conversation

    monkeypatch.setattr(notices, "ChannelAccountRepository", lambda db: SimpleNamespace(
        get_by_id=lambda account_id: accounts.get(account_id),
    ))

    def fake_db(rows):
        query = SessionRows(rows)
        db = MagicMock()
        db.query.side_effect = lambda model: query if model is ChannelConversation else None
        return db

    return session, accounts, conversations, fake_db


def session_only(session):
    return {"session_id": str(session.session_id)}


def canonical(session, conversation, account):
    return {**session_only(session), "channel_account_id": str(account.id),
            "channel_conversation_id": str(conversation.id),
            "external_account_id": account.external_account_id}


@pytest.mark.parametrize("order", [("T_ALPHA", "T_BRAVO"), ("T_BRAVO", "T_ALPHA")])
def test_same_session_two_workspaces_both_creation_orders_fail_closed(links, order):
    session, accounts, conversations, fake_db = links
    rows = [conversations[name] for name in order]
    assert rows[0].channel_account_id != rows[1].channel_account_id
    assert rows[0].external_user_id == rows[1].external_user_id
    db = fake_db(rows)
    assert ChannelConversationRepository(db).get_unique_by_session(session.session_id) is None
    assert notices.chat_notification_metadata(db, session) == session_only(session)


@pytest.mark.parametrize("team", ["T_ALPHA", "T_BRAVO"])
def test_unique_row_resolves_only_its_exact_account(links, team):
    session, accounts, conversations, fake_db = links
    conversation = conversations[team]
    assert notices.chat_notification_metadata(fake_db([conversation]), session) == canonical(
        session, conversation, accounts[conversation.channel_account_id]
    )


def test_a_missing_b_belongs_to_another_session_never_falls_back(links):
    session, accounts, conversations, fake_db = links
    conversations["T_BRAVO"].session_id = uuid4()
    assert notices.chat_notification_metadata(fake_db([conversations["T_BRAVO"]]), session) == session_only(session)
    assert notices.chat_notification_metadata(fake_db([]), session) == session_only(session)


@pytest.mark.parametrize("fault", ["cross_org_row", "cross_channel_row", "inactive_account",
                                     "missing_account", "missing_workspace", "wrong_session"])
def test_unusable_or_inconsistent_unique_linkage_fails_closed(links, fault):
    session, accounts, conversations, fake_db = links
    row = conversations["T_ALPHA"]
    account = accounts[row.channel_account_id]
    if fault == "cross_org_row":
        row.organization_id = uuid4()
    elif fault == "cross_channel_row":
        row.channel_type = "telegram"
    elif fault == "inactive_account":
        account.is_active = False
    elif fault == "missing_account":
        accounts.pop(account.id)
    elif fault == "missing_workspace":
        account.external_account_id = ""
    elif fault == "wrong_session":
        row.session_id = uuid4()
    assert notices.chat_notification_metadata(fake_db([row]), session) == session_only(session)


@pytest.mark.parametrize("fault", ["cross_org_row", "cross_channel_row", "inactive_account"])
def test_ineligible_sibling_row_must_not_be_filtered_to_make_an_identity(links, fault):
    session, accounts, conversations, fake_db = links
    sibling = conversations["T_BRAVO"]
    if fault == "cross_org_row":
        sibling.organization_id = uuid4()
    elif fault == "cross_channel_row":
        sibling.channel_type = "messenger"
    else:
        accounts[sibling.channel_account_id].is_active = False
    assert notices.chat_notification_metadata(
        fake_db([conversations["T_ALPHA"], sibling]), session
    ) == session_only(session)


def test_repo_failure_or_bad_uuid_fails_closed(links):
    session, accounts, conversations, fake_db = links
    assert ChannelConversationRepository(fake_db([])).get_unique_by_session("not-a-uuid") is None
    db = MagicMock()
    db.query.side_effect = RuntimeError("DB unavailable")
    assert notices.chat_notification_metadata(db, session) == session_only(session)


@pytest.mark.asyncio
async def test_new_chat_assigned_and_human_transfer_keep_only_session_on_ambiguity(monkeypatch, links):
    session, accounts, conversations, fake_db = links
    db = fake_db(list(conversations.values()))
    recipient = SimpleNamespace(id=uuid4())
    monkeypatch.setattr(notices, "UserRepository", lambda _: SimpleNamespace(
        get_users_with_any_permission=lambda *_: [recipient],
    ))
    emit = AsyncMock()
    monkeypatch.setattr(notices, "notify_chat_event", emit)
    await notices.notify_new_chat(db, session)
    assert emit.await_args.kwargs["event"] == ChatNotificationEvent.NEW_CHAT
    assert emit.await_args.kwargs["metadata"] == session_only(session)
    await notices.notify_chat_assigned(db, session, recipient.id)
    assert emit.await_args.kwargs["event"] == ChatNotificationEvent.CHAT_ASSIGNED
    assert emit.await_args.kwargs["metadata"] == session_only(session)

    transfer_emit = AsyncMock()
    monkeypatch.setattr(human, "SessionToAgentRepository", lambda _: SimpleNamespace(
        update_session=lambda *args: True,
    ))
    monkeypatch.setattr(human, "_transfer_recipients", lambda *args: [recipient.id])
    monkeypatch.setattr(human, "notify_chat_event", transfer_emit)
    monkeypatch.setattr(human, "notify_customer", AsyncMock())
    assert await human.route_session_to_human(
        db, session, reason="DIRECT_REQUEST", description="take over"
    )
    assert transfer_emit.await_args.kwargs["event"] == ChatNotificationEvent.CHAT_TRANSFER
    assert transfer_emit.await_args.kwargs["metadata"] == {
        **session_only(session), "transfer_reason": "DIRECT_REQUEST",
        "transfer_description": "take over",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("workflow", [False, True])
async def test_chat_agent_transfer_paths_keep_reason_not_workspace(monkeypatch, links, workflow):
    session, accounts, conversations, fake_db = links
    db = fake_db(list(conversations.values()))
    # Transfer recipient query is independent of ChannelConversation identity.
    real_query = db.query.side_effect
    recipients = MagicMock()
    recipients.join.return_value.filter.return_value.all.return_value = [
        SimpleNamespace(id=uuid4())
    ]
    db.query.side_effect = lambda model: (
        recipients if model is not ChannelConversation else real_query(model)
    )
    monkeypatch.setattr(chat_agent, "SessionToAgentRepository", lambda _: SimpleNamespace(
        update_session=lambda *args: True, get_session=lambda sid: session,
    ))
    emit = AsyncMock()
    monkeypatch.setattr(chat_agent, "notify_chat_event", emit)
    monkeypatch.setattr(chat_agent, "get_agent_availability_response",
                        AsyncMock(return_value={"message": "A human can help.",
                                                "transfer_to_human": True}))
    group_id = uuid4()
    agent = SimpleNamespace(
        agent_data=SimpleNamespace(groups=[SimpleNamespace(id=group_id)]),
        api_key=None, model_name="test", model_type="test", base_url=None,
    )
    history_repo = MagicMock()
    history_repo.get_session_history = AsyncMock(return_value=[])
    await chat_agent.ChatAgent._handle_transfer(
        agent, ChatResponse(
            message="handoff", transfer_to_human=True,
            transfer_reason=TransferReasonType.DIRECT_REQUEST,
            transfer_description="a person is needed",
        ),
        str(session.session_id), str(session.organization_id),
        str(uuid4()), str(uuid4()), db, history_repo,
        transfer_group_id=group_id if workflow else None,
    )
    assert emit.await_args.kwargs["event"] == ChatNotificationEvent.CHAT_TRANSFER
    assert emit.await_args.kwargs["metadata"] == {
        **session_only(session), "transfer_reason": "DIRECT_REQUEST",
        "transfer_description": "a person is needed",
    }
