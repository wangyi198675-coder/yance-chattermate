from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.repositories import chat as chat_repository
from app.repositories.chat import ChatRepository


class FakeQuery:
    def __init__(self, rows):
        self.rows = list(rows)
        self.filters = []
        self.ordering = []
        self.limit_value = None

    def options(self, *args):
        return self

    def filter(self, *criteria):
        self.filters.extend(criteria)
        return self

    def order_by(self, *clauses):
        self.ordering = [str(clause) for clause in clauses]
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def all(self):
        rows = self.rows
        if self.limit_value is not None:
            rows = rows[: self.limit_value]
        return rows


class FakeDb:
    def __init__(self, rows):
        self.query_object = FakeQuery(rows)

    def query(self, *args):
        return self.query_object


def row(row_id, created_at, *, intent=None):
    return SimpleNamespace(
        id=row_id,
        client_send_intent_id=intent,
        session_id=uuid4(),
        message=f"message-{row_id}",
        message_type="agent",
        created_at=created_at,
        attributes={},
        attachments=[],
        agent=None,
        user=None,
    )


@pytest.mark.asyncio
async def test_latest_page_is_bounded_and_oldest_returned_row_is_cursor(monkeypatch):
    monkeypatch.setattr(chat_repository.settings, "S3_FILE_STORAGE", False)
    timestamp = datetime(2026, 10, 7, 8, 0, tzinfo=timezone.utc)
    rows = [row(5, timestamp), row(4, timestamp), row(3, timestamp), row(2, timestamp)]
    db = FakeDb(rows)

    page = await ChatRepository(db).get_session_history_page(
        uuid4(),
        limit=3,
        direction="latest",
    )

    assert [message.id for message in page["messages"]] == [3, 4, 5]
    assert page["has_more"] is True
    assert page["next_cursor"] == {"created_at": timestamp, "id": 3}
    assert db.query_object.limit_value == 4
    assert "created_at DESC" in db.query_object.ordering[0]
    assert "id DESC" in db.query_object.ordering[1]


@pytest.mark.asyncio
async def test_older_and_newer_pages_use_strict_created_at_id_keysets(monkeypatch):
    monkeypatch.setattr(chat_repository.settings, "S3_FILE_STORAGE", False)
    timestamp = datetime(2026, 10, 7, 8, 30, tzinfo=timezone.utc)

    older_db = FakeDb([row(2, timestamp), row(1, timestamp)])
    older = await ChatRepository(older_db).get_session_history_page(
        uuid4(),
        limit=50,
        direction="older",
        cursor_created_at=timestamp,
        cursor_id=3,
    )
    older_keyset = str(older_db.query_object.filters[-1])

    assert [message.id for message in older["messages"]] == [1, 2]
    assert older["has_more"] is False
    assert older["next_cursor"] is None
    assert "created_at <" in older_keyset
    assert "chat_history.id <" in older_keyset
    assert "created_at DESC" in older_db.query_object.ordering[0]
    assert "id DESC" in older_db.query_object.ordering[1]

    newer_db = FakeDb([row(4, timestamp), row(5, timestamp), row(6, timestamp)])
    newer = await ChatRepository(newer_db).get_session_history_page(
        uuid4(),
        limit=2,
        direction="newer",
        cursor_created_at=timestamp,
        cursor_id=3,
    )
    newer_keyset = str(newer_db.query_object.filters[-1])

    assert [message.id for message in newer["messages"]] == [4, 5]
    assert newer["has_more"] is True
    assert newer["next_cursor"] == {"created_at": timestamp, "id": 5}
    assert "created_at >" in newer_keyset
    assert "chat_history.id >" in newer_keyset
    assert "created_at ASC" in newer_db.query_object.ordering[0]
    assert "id ASC" in newer_db.query_object.ordering[1]


def test_projection_exposes_canonical_identity_and_existing_fileattachment_rows():
    timestamp = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)
    session_id = uuid4()
    intent_id = uuid4()
    attachment = SimpleNamespace(
        id=91,
        filename="voice.webm",
        file_url="/api/v1/files/download/voice.webm",
        content_type="audio/webm",
        file_size=1234,
    )
    message = SimpleNamespace(
        id=77,
        client_send_intent_id=intent_id,
        session_id=session_id,
        message="hello",
        message_type="agent",
        created_at=timestamp,
        attributes={},
        attachments=[attachment],
        agent=None,
        user=None,
    )

    projected = ChatRepository(SimpleNamespace())._project_history_message(message)

    assert projected["id"] == 77
    assert projected["client_send_intent_id"] == intent_id
    assert projected["session_id"] == session_id
    assert projected["created_at"] == timestamp
    assert projected["attachments"] == [
        {
            "id": 91,
            "filename": "voice.webm",
            "file_url": "/api/v1/files/download/voice.webm",
            "content_type": "audio/webm",
            "file_size": 1234,
        }
    ]


@pytest.mark.asyncio
async def test_message_page_endpoint_forwards_keyset_cursor_and_canonical_projection(monkeypatch):
    from app.api import chat as chat_api

    session_id = uuid4()
    organization_id = uuid4()
    timestamp = datetime(2026, 10, 7, 9, 30, tzinfo=timezone.utc)
    canonical = row(12, timestamp)
    canonical.session_id = session_id

    class EndpointRepo:
        def __init__(self, db):
            assert db is fake_db

        def session_belongs_to_organization(self, received_session_id, received_org_id):
            assert received_session_id == session_id
            assert received_org_id == organization_id
            return True

        async def get_session_history_page(self, received_session_id, **kwargs):
            assert received_session_id == session_id
            assert kwargs == {
                "limit": 25,
                "direction": "newer",
                "cursor_created_at": timestamp,
                "cursor_id": 11,
            }
            return {
                "messages": [canonical],
                "has_more": False,
                "next_cursor": None,
            }

        def _project_history_message(self, message):
            assert message is canonical
            return {
                "id": message.id,
                "client_send_intent_id": message.client_send_intent_id,
                "session_id": message.session_id,
                "message": message.message,
                "message_type": message.message_type,
                "created_at": message.created_at,
                "attributes": message.attributes,
            }

    fake_db = object()
    monkeypatch.setattr(chat_api, "ChatRepository", EndpointRepo)

    result = await chat_api.get_chat_messages(
        str(session_id),
        direction="newer",
        cursor_created_at=timestamp,
        cursor_id=11,
        limit=25,
        auth_info={
            "auth_type": "shopify",
            "organization_id": organization_id,
        },
        db=fake_db,
    )

    assert result["has_more"] is False
    assert result["next_cursor"] is None
    assert result["messages"][0]["id"] == 12
    assert result["messages"][0]["session_id"] == session_id


@pytest.mark.asyncio
async def test_message_page_endpoint_fails_closed_on_cross_org_session(monkeypatch):
    from fastapi import HTTPException
    from app.api import chat as chat_api

    session_id = uuid4()
    organization_id = uuid4()
    timestamp = datetime(2026, 10, 7, 10, 0, tzinfo=timezone.utc)

    class DeniedRepo:
        def __init__(self, db):
            pass

        def session_belongs_to_organization(self, received_session_id, received_org_id):
            assert received_session_id == session_id
            assert received_org_id == organization_id
            return False

    monkeypatch.setattr(chat_api, "ChatRepository", DeniedRepo)

    with pytest.raises(HTTPException) as error:
        await chat_api.get_chat_messages(
            str(session_id),
            direction="older",
            cursor_created_at=timestamp,
            cursor_id=88,
            limit=50,
            auth_info={
                "auth_type": "shopify",
                "organization_id": organization_id,
            },
            db=object(),
        )

    assert error.value.status_code == 404
    assert error.value.detail == "Chat session not found"
