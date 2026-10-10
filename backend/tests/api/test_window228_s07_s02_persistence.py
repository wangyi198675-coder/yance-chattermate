"""Window228: real SQLAlchemy persistence, scope and derived-unread integration."""
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import chat as chat_api
from app.api import notification as notification_api
from app.core.auth import get_unified_chat_auth, get_current_user
from app.database import get_db
from app.models.chat_history import ChatHistory
from app.models.notification_settings import UserNotificationSettings
from app.models.organization import Organization
from app.models.role import Role
from app.models.session_to_agent import SessionToAgent
from app.models.user import User
from app.repositories.chat import ChatRepository
from app.repositories.session_to_agent import SessionToAgentRepository
from tests.conftest import TestingSessionLocal


def _session(db, user, customer, agent):
    row = SessionToAgent(
        session_id=uuid4(), organization_id=user.organization_id,
        customer_id=customer.id, agent_id=agent.id, user_id=user.id,
        channel="messenger",
    )
    db.add(row)
    db.commit()
    return row


def _incoming(db, row, customer, agent, message="Hallo"):
    history = ChatHistory(
        organization_id=row.organization_id, session_id=row.session_id,
        customer_id=customer.id, agent_id=agent.id,
        message_type="user", message=message,
    )
    db.add(history)
    db.commit()
    db.refresh(history)
    return history.id


def _overview(db, user):
    return ChatRepository(db).get_recent_chats(
        organization_id=user.organization_id, user_id=user.id
    )


def test_s07_same_table_roundtrip_and_derived_unread_after_new_db_session(
    db, test_user, test_customer, test_agent,
):
    row = _session(db, test_user, test_customer, test_agent)
    first = _incoming(db, row, test_customer, test_agent)
    _incoming(db, row, test_customer, test_agent, "Zweite Nachricht")
    assert _overview(db, test_user)[0]["unread_count"] == 2

    owner = SessionToAgentRepository(db)
    updated = owner.update_inbox_state(
        row.session_id, test_user.organization_id,
        followed=True, favourite=True, archived=True, mark_read=True,
    )
    assert updated.last_read_message_id > first

    # A fresh SQLAlchemy Session reads the database, not an in-memory or
    # localStorage mirror; this is restart-rehydration *simulation*, not
    # proof of an actual Windows process restart.
    with TestingSessionLocal() as reopened:
        persisted = reopened.get(SessionToAgent, row.session_id)
        assert (persisted.is_followed, persisted.is_favourite, persisted.is_archived) == (
            True, True, True
        )
        assert persisted.last_read_message_id == updated.last_read_message_id
        overview = _overview(reopened, test_user)[0]
        assert (overview["followed"], overview["favourite"], overview["archived"]) == (
            True, True, True
        )
        assert overview["unread_count"] == 0
        assert ChatRepository(reopened).get_recent_chats(
            organization_id=test_user.organization_id,
            user_id=test_user.id, inbox_filter="all", limit=1,
        ) == []
        archived_page = ChatRepository(reopened).get_recent_chats(
            organization_id=test_user.organization_id,
            user_id=test_user.id, inbox_filter="archived", limit=1,
        )
        assert len(archived_page) == 1
        assert archived_page[0]["session_id"] == row.session_id

    _incoming(db, row, test_customer, test_agent, "Dritte Nachricht")
    with TestingSessionLocal() as reopened:
        assert _overview(reopened, test_user)[0]["unread_count"] == 1

    owner.update_inbox_state(row.session_id, test_user.organization_id, archived=False, mark_read=True)
    with TestingSessionLocal() as reopened:
        persisted = reopened.get(SessionToAgent, row.session_id)
        assert persisted.is_archived is False
        assert persisted.is_followed is True
        assert persisted.is_favourite is True
        assert _overview(reopened, test_user)[0]["unread_count"] == 0
        assert len(ChatRepository(reopened).get_recent_chats(
            organization_id=test_user.organization_id,
            user_id=test_user.id, inbox_filter="all", limit=1,
        )) == 1


def test_s07_api_user_org_and_session_isolation(
    db, test_user, test_customer, test_agent, test_role,
):
    first = _session(db, test_user, test_customer, test_agent)
    other = User(
        id=uuid4(), organization_id=test_user.organization_id,
        email="s07.other@example.test", full_name="Other user",
        hashed_password="test-only", is_active=True, role_id=test_role.id,
    )
    outside_org = Organization(name="Separate S07 org", domain="s07-other.test", timezone="UTC")
    db.add_all([other, outside_org])
    db.flush()
    outside_role = Role(name="S07 Other Role", organization_id=outside_org.id)
    db.add(outside_role)
    db.flush()
    outside_user = User(
        id=uuid4(), organization_id=outside_org.id,
        email="s07.outside@example.test", full_name="Outside organization user",
        hashed_password="test-only", is_active=True, role_id=outside_role.id,
    )
    db.add(outside_user)
    db.commit()
    second = _session(db, other, test_customer, test_agent)
    _incoming(db, first, test_customer, test_agent)
    _incoming(db, second, test_customer, test_agent)

    app = FastAPI()
    app.include_router(chat_api.router, prefix="/api/chats")
    app.dependency_overrides[get_db] = lambda: db
    caller = {"auth_type": "jwt", "organization_id": test_user.organization_id,
              "current_user": test_user, "can_view_all": False,
              "can_view_assigned": True, "can_view_unassigned": False}
    app.dependency_overrides[get_unified_chat_auth] = lambda: caller

    with TestClient(app) as client:
        assert client.patch(
            f"/api/chats/{first.session_id}/inbox-state", json={"favourite": True}
        ).status_code == 200
        assert client.patch(
            f"/api/chats/{second.session_id}/inbox-state", json={"favourite": True}
        ).status_code == 404
        favourites = client.get("/api/chats/recent?inbox_filter=favourite").json()
        assert len(favourites) == 1
        assert favourites[0]["session_id"] == str(first.session_id)
        caller["current_user"] = other
        assert client.patch(
            f"/api/chats/{first.session_id}/inbox-state", json={"archived": True}
        ).status_code == 404

        # No view grants must fail closed, not return every session in the org.
        caller["can_view_assigned"] = False
        assert client.get("/api/chats/recent").json() == []

        # Even a view-all user from a foreign organization cannot mutate a
        # guessed session UUID in this organization.
        caller.update(organization_id=outside_org.id, current_user=outside_user, can_view_all=True)
        assert client.patch(
            f"/api/chats/{first.session_id}/inbox-state", json={"archived": True}
        ).status_code == 404

    with TestingSessionLocal() as reopened:
        assert reopened.get(SessionToAgent, first.session_id).is_favourite is True
        assert reopened.get(SessionToAgent, first.session_id).is_archived is False
        assert reopened.get(SessionToAgent, second.session_id).is_favourite is False


def test_s02_native_sound_setting_persists_for_exact_user_and_org(
    db, test_user, test_role,
):
    other_org = Organization(name="S02 other organization", domain="s02-other.test", timezone="UTC")
    db.add(other_org)
    db.flush()
    other_role = Role(name="S02 Other Role", organization_id=other_org.id)
    db.add(other_role)
    db.flush()
    other_user = User(
        id=uuid4(), organization_id=other_org.id,
        email="s02.other@example.test", full_name="Other organization user",
        hashed_password="test-only", is_active=True, role_id=other_role.id,
    )
    db.add(other_user)
    db.commit()

    app = FastAPI()
    app.include_router(notification_api.router, prefix="/api/notifications")
    app.dependency_overrides[get_db] = lambda: db
    caller = {"user": test_user}
    app.dependency_overrides[get_current_user] = lambda: caller["user"]
    with TestClient(app) as client:
        saved = client.put("/api/notifications/settings", json={"sound_enabled": False})
        assert saved.status_code == 200
        assert saved.json()["sound_enabled"] is False
        caller["user"] = other_user
        assert client.get("/api/notifications/settings").json()["sound_enabled"] is True
        assert client.put("/api/notifications/settings", json={"notify_new_chat": True}).status_code == 200
        caller["user"] = test_user
        assert client.get("/api/notifications/settings").json()["sound_enabled"] is False

    # Fresh ORM session after the API write: exact persisted per-user rows.
    with TestingSessionLocal() as reopened:
        assert reopened.get(UserNotificationSettings, test_user.id).sound_enabled is False
        assert reopened.get(UserNotificationSettings, other_user.id).sound_enabled is True
        assert reopened.get(UserNotificationSettings, test_user.id).user_id == test_user.id
        assert reopened.get(UserNotificationSettings, other_user.id).user_id == other_user.id
