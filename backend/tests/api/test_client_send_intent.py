import asyncio
import importlib.util
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.api import widget_chat
from app.database import Base
from app.models.chat_history import ChatHistory
from app.models.file_attachment import FileAttachment
from app.repositories import chat as chat_repository_module
from app.repositories.chat import ChatRepository, ClientSendIntentConflict
from app.repositories.file_attachment import FileAttachmentRepository
from app.repositories.session_to_agent import SessionToAgentRepository
from app.services.message_delivery import DeliveryResult


def _message_data(*, organization_id, session_id, user_id=None,
                  customer_id=None, agent_id=None, message="hello"):
    return {
        "message": message,
        "message_type": "agent",
        "organization_id": str(organization_id),
        "session_id": str(session_id),
        "user_id": str(user_id) if user_id else None,
        "customer_id": str(customer_id) if customer_id else None,
        "agent_id": str(agent_id) if agent_id else None,
        "attributes": {"end_chat": False},
    }


def test_claim_single_sequential_duplicate_and_distinct_actions(db):
    org_id = __import__("uuid").uuid4()
    session_id = __import__("uuid").uuid4()
    repo = ChatRepository(db)
    intent_id = __import__("uuid").uuid4()

    first, claimed = repo.claim_or_get_client_send_intent(
        _message_data(organization_id=org_id, session_id=session_id),
        intent_id,
        "message",
    )
    duplicate, duplicate_claimed = repo.claim_or_get_client_send_intent(
        _message_data(organization_id=org_id, session_id=session_id),
        intent_id,
        "message",
    )

    assert claimed is True
    assert duplicate_claimed is False
    assert duplicate.id == first.id
    assert db.query(ChatHistory).filter(
        ChatHistory.organization_id == org_id,
        ChatHistory.client_send_intent_id == intent_id,
    ).count() == 1

    # Same content but a genuinely new Send action has a new intent and row.
    second, second_claimed = repo.claim_or_get_client_send_intent(
        _message_data(organization_id=org_id, session_id=session_id),
        __import__("uuid").uuid4(),
        "message",
    )
    assert second_claimed is True
    assert second.id != first.id


def test_claim_rejects_wrong_session_and_action_kind_but_allows_cross_org(db):
    uuid = __import__("uuid")
    intent_id = uuid.uuid4()
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    session_a = uuid.uuid4()
    repo = ChatRepository(db)

    original, claimed = repo.claim_or_get_client_send_intent(
        _message_data(organization_id=org_a, session_id=session_a),
        intent_id,
        "message",
    )
    assert claimed is True

    with pytest.raises(ClientSendIntentConflict):
        repo.claim_or_get_client_send_intent(
            _message_data(organization_id=org_a, session_id=uuid.uuid4()),
            intent_id,
            "message",
        )

    with pytest.raises(ClientSendIntentConflict):
        repo.claim_or_get_client_send_intent(
            _message_data(organization_id=org_a, session_id=session_a),
            intent_id,
            "end_chat",
        )

    cross_org, cross_org_claimed = repo.claim_or_get_client_send_intent(
        _message_data(organization_id=org_b, session_id=uuid.uuid4()),
        intent_id,
        "message",
    )
    assert cross_org_claimed is True
    assert cross_org.id != original.id


def test_nullable_client_intent_preserves_legacy_rows(db):
    uuid = __import__("uuid")
    org_id = uuid.uuid4()
    rows = [
        ChatHistory(
            organization_id=org_id,
            session_id=uuid.uuid4(),
            message=f"legacy-{index}",
            message_type="agent",
            client_send_intent_id=None,
        )
        for index in range(2)
    ]
    db.add_all(rows)
    db.commit()
    assert all(row.client_send_intent_id is None for row in rows)


def test_concurrent_duplicate_claim_collapses_to_one_row(tmp_path):
    uuid = __import__("uuid")
    engine = create_engine(
        f"sqlite:///{tmp_path / 'client-intent.sqlite'}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    org_id = uuid.uuid4()
    session_id = uuid.uuid4()
    intent_id = uuid.uuid4()
    barrier = threading.Barrier(2)

    def worker():
        session = SessionLocal()
        try:
            barrier.wait(timeout=5)
            row, claimed = ChatRepository(session).claim_or_get_client_send_intent(
                _message_data(organization_id=org_id, session_id=session_id),
                intent_id,
                "message",
            )
            return row.id, claimed
        finally:
            session.close()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [future.result(timeout=15) for future in [pool.submit(worker), pool.submit(worker)]]
        assert sum(1 for _, claimed in results if claimed) == 1
        assert len({row_id for row_id, _ in results}) == 1

        verify = SessionLocal()
        try:
            assert verify.query(ChatHistory).filter(
                ChatHistory.organization_id == org_id,
                ChatHistory.client_send_intent_id == intent_id,
            ).count() == 1
        finally:
            verify.close()
    finally:
        engine.dispose()


async def _make_handler_context(db, test_widget, test_customer, test_user, monkeypatch):
    session_id = __import__("uuid").uuid4()
    SessionToAgentRepository(db).create_session(
        session_id=session_id,
        agent_id=test_widget.agent_id,
        customer_id=test_customer.id,
        user_id=test_user.id,
        organization_id=test_widget.organization_id,
    )

    sio = AsyncMock()
    sio.get_session.return_value = {
        "user_id": str(test_user.id),
        "organization_id": str(test_widget.organization_id),
    }
    monkeypatch.setattr(widget_chat, "sio", sio)
    monkeypatch.setattr(widget_chat, "get_db", lambda: iter([db]))
    delivery = AsyncMock(return_value=DeliveryResult(ok=True))
    monkeypatch.setattr(widget_chat, "deliver_to_customer", delivery)
    return session_id, sio, delivery


@pytest.mark.asyncio
async def test_handler_lost_ack_and_reconnect_replay_return_same_canonical_message(
    db, test_widget, test_customer, test_user, monkeypatch
):
    uuid = __import__("uuid")
    session_id, _sio, delivery = await _make_handler_context(
        db, test_widget, test_customer, test_user, monkeypatch
    )
    intent_id = uuid.uuid4()
    data = {
        "message": "same transport action",
        "session_id": str(session_id),
        "client_send_intent_id": str(intent_id),
    }

    first = await widget_chat.handle_agent_message("sid-a", dict(data))
    # Lost ACK / reconnect replay is the same transport action and same UUID.
    replay = await widget_chat.handle_agent_message("sid-b", dict(data))

    assert first["status"] == "accepted"
    assert replay["status"] == "accepted"
    assert replay["duplicate"] is True
    assert replay["message_id"] == first["message_id"]
    assert replay["client_send_intent_id"] == str(intent_id)
    assert delivery.await_count == 1
    assert db.query(ChatHistory).filter(
        ChatHistory.organization_id == test_widget.organization_id,
        ChatHistory.client_send_intent_id == intent_id,
    ).count() == 1


@pytest.mark.asyncio
async def test_handler_duplicate_ordinary_file_materializes_once(
    db, test_widget, test_customer, test_user, monkeypatch
):
    uuid = __import__("uuid")
    session_id, _sio, delivery = await _make_handler_context(
        db, test_widget, test_customer, test_user, monkeypatch
    )
    upload = AsyncMock(return_value={
        "file_url": "/api/v1/uploads/test/file.txt",
        "filename": "file.txt",
        "content_type": "text/plain",
        "size": 5,
    })
    monkeypatch.setattr(widget_chat.FileUploadService, "upload_file", upload)

    intent_id = uuid.uuid4()
    data = {
        "message": "file",
        "session_id": str(session_id),
        "client_send_intent_id": str(intent_id),
        "files": [{
            "content": "aGVsbG8=",
            "filename": "file.txt",
            "content_type": "text/plain",
            "size": 5,
        }],
    }
    first = await widget_chat.handle_agent_message("sid-a", dict(data))
    replay = await widget_chat.handle_agent_message("sid-b", dict(data))

    assert replay["message_id"] == first["message_id"]
    assert upload.await_count == 1
    assert delivery.await_count == 1
    attachments = db.query(FileAttachment).filter(
        FileAttachment.chat_history_id == first["message_id"]
    ).all()
    assert len(attachments) == 1


@pytest.mark.asyncio
async def test_handler_duplicate_existing_attachment_adopts_once(
    db, test_widget, test_customer, test_user, monkeypatch
):
    uuid = __import__("uuid")
    session_id, _sio, delivery = await _make_handler_context(
        db, test_widget, test_customer, test_user, monkeypatch
    )
    attachment = FileAttachmentRepository(db).create_attachment(
        file_url="/api/v1/uploads/generated/audio.mp3",
        filename="audio.mp3",
        content_type="audio/mpeg",
        file_size=10,
        organization_id=test_widget.organization_id,
        uploaded_by_user_id=test_user.id,
    )

    intent_id = uuid.uuid4()
    data = {
        "message": "",
        "session_id": str(session_id),
        "client_send_intent_id": str(intent_id),
        "attachment_ids": [attachment.id],
    }
    first = await widget_chat.handle_agent_message("sid-a", dict(data))
    replay = await widget_chat.handle_agent_message("sid-b", dict(data))

    db.refresh(attachment)
    assert replay["message_id"] == first["message_id"]
    assert attachment.chat_history_id == first["message_id"]
    assert db.query(FileAttachment).filter(FileAttachment.id == attachment.id).count() == 1
    assert delivery.await_count == 1


@pytest.mark.asyncio
async def test_handler_duplicate_end_chat_is_one_canonical_action(
    db, test_widget, test_customer, test_user, monkeypatch
):
    uuid = __import__("uuid")
    session_id, _sio, delivery = await _make_handler_context(
        db, test_widget, test_customer, test_user, monkeypatch
    )
    update_status = MagicMock()
    monkeypatch.setattr(
        widget_chat.SessionToAgentRepository,
        "update_session_status",
        update_status,
    )

    intent_id = uuid.uuid4()
    data = {
        "message": "chat closed",
        "session_id": str(session_id),
        "client_send_intent_id": str(intent_id),
        "message_type": "system",
        "end_chat": True,
        "request_rating": False,
        "end_chat_reason": "AGENT_REQUEST",
    }
    first = await widget_chat.handle_agent_message("sid-a", dict(data))
    replay = await widget_chat.handle_agent_message("sid-b", dict(data))

    assert replay["message_id"] == first["message_id"]
    assert update_status.call_count == 1
    assert delivery.await_count == 1
    assert db.query(ChatHistory).filter(
        ChatHistory.client_send_intent_id == intent_id
    ).count() == 1


def test_client_send_intent_migration_preserves_existing_rows_and_null_semantics(tmp_path):
    migration_path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "client_send_intent_001.py"
    )
    spec = importlib.util.spec_from_file_location("client_send_intent_001", migration_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)

    engine = create_engine(f"sqlite:///{tmp_path / 'migration.sqlite'}")
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE chat_history (
                id INTEGER PRIMARY KEY,
                organization_id CHAR(36) NULL,
                message TEXT NOT NULL
            )
        """))
        connection.execute(text(
            "INSERT INTO chat_history (id, organization_id, message) "
            "VALUES (1, 'org-a', 'existing')"
        ))

        context = MigrationContext.configure(connection)
        module.op = Operations(context)
        module.upgrade()

        preserved = connection.execute(text(
            "SELECT message, client_send_intent_id FROM chat_history WHERE id = 1"
        )).one()
        assert preserved == ("existing", None)

        # Multiple historical NULL intents are legal.
        connection.execute(text(
            "INSERT INTO chat_history (id, organization_id, message, client_send_intent_id) "
            "VALUES (2, 'org-a', 'legacy-2', NULL)"
        ))
        connection.execute(text(
            "INSERT INTO chat_history (id, organization_id, message, client_send_intent_id) "
            "VALUES (3, 'org-a', 'first', '11111111-1111-1111-1111-111111111111')"
        ))
        with pytest.raises(IntegrityError):
            connection.execute(text(
                "INSERT INTO chat_history (id, organization_id, message, client_send_intent_id) "
                "VALUES (4, 'org-a', 'duplicate', '11111111-1111-1111-1111-111111111111')"
            ))
        # Same UUID in another organization remains independent.
        connection.execute(text(
            "INSERT INTO chat_history (id, organization_id, message, client_send_intent_id) "
            "VALUES (5, 'org-b', 'other-org', '11111111-1111-1111-1111-111111111111')"
        ))

@pytest.mark.asyncio
async def test_post_claim_crash_before_delivery_replay_resumes_same_message(
    db, test_widget, test_customer, test_user, monkeypatch
):
    uuid = __import__("uuid")
    session_id, _sio, delivery = await _make_handler_context(
        db, test_widget, test_customer, test_user, monkeypatch
    )
    delivery.side_effect = [SystemExit("crash-before-delivery"), DeliveryResult(ok=True)]
    intent_id = uuid.uuid4()
    data = {
        "message": "recover me",
        "session_id": str(session_id),
        "client_send_intent_id": str(intent_id),
    }

    with pytest.raises(SystemExit, match="crash-before-delivery"):
        await widget_chat.handle_agent_message("sid-first", dict(data))

    replay = await widget_chat.handle_agent_message("sid-replay", dict(data))
    rows = db.query(ChatHistory).filter(
        ChatHistory.organization_id == test_widget.organization_id,
        ChatHistory.client_send_intent_id == intent_id,
    ).all()

    assert len(rows) == 1
    assert replay["status"] == "accepted"
    assert replay["message_id"] == rows[0].id
    assert replay["client_send_intent_id"] == str(intent_id)
    assert replay["delivery_ok"] is True
    assert delivery.await_count == 2


@pytest.mark.asyncio
async def test_two_concurrent_recovery_replays_have_one_effective_delivery_contender(
    db, test_widget, test_customer, test_user, monkeypatch
):
    uuid = __import__("uuid")
    session_id, _sio, delivery = await _make_handler_context(
        db, test_widget, test_customer, test_user, monkeypatch
    )
    intent_id = uuid.uuid4()
    data = {
        "message": "one recovery contender",
        "session_id": str(session_id),
        "client_send_intent_id": str(intent_id),
    }
    delivery.side_effect = SystemExit("crash-before-delivery")
    with pytest.raises(SystemExit, match="crash-before-delivery"):
        await widget_chat.handle_agent_message("sid-first", dict(data))

    delivery.side_effect = None
    gate = asyncio.Event()
    release = asyncio.Event()
    effective_deliveries = 0

    async def recovered_delivery(*args, **kwargs):
        nonlocal effective_deliveries
        effective_deliveries += 1
        gate.set()
        await release.wait()
        return DeliveryResult(ok=True)

    delivery.side_effect = recovered_delivery
    first_replay = asyncio.create_task(
        widget_chat.handle_agent_message("sid-recovery-a", dict(data))
    )
    await asyncio.wait_for(gate.wait(), timeout=2)
    second_replay = asyncio.create_task(
        widget_chat.handle_agent_message("sid-recovery-b", dict(data))
    )
    await asyncio.sleep(0)
    release.set()
    results = await asyncio.gather(first_replay, second_replay)

    assert effective_deliveries == 1
    assert {result["message_id"] for result in results} == {
        db.query(ChatHistory).filter(
            ChatHistory.client_send_intent_id == intent_id
        ).one().id
    }


@pytest.mark.asyncio
async def test_ordinary_file_post_materialization_pre_attachment_commit_crash_replay_has_one_physical_object(
    db, test_widget, test_customer, test_user, monkeypatch, tmp_path
):
    uuid = __import__("uuid")
    session_id, _sio, delivery = await _make_handler_context(
        db, test_widget, test_customer, test_user, monkeypatch
    )
    file_upload_settings = __import__(
        "app.services.file_upload_service", fromlist=["settings"]
    ).settings
    monkeypatch.setattr(file_upload_settings, "S3_FILE_STORAGE", False)
    monkeypatch.setattr(file_upload_settings, "YANCE_DATA_ROOT", str(tmp_path))

    original_create = FileAttachmentRepository.create_attachment
    create_calls = 0

    def crash_after_materialization_before_commit(self, *args, **kwargs):
        nonlocal create_calls
        create_calls += 1
        if create_calls == 1:
            raise SystemExit("crash-after-materialization-before-attachment-commit")
        return original_create(self, *args, **kwargs)

    monkeypatch.setattr(
        FileAttachmentRepository,
        "create_attachment",
        crash_after_materialization_before_commit,
    )

    intent_id = uuid.uuid4()
    data = {
        "message": "file recovery",
        "session_id": str(session_id),
        "client_send_intent_id": str(intent_id),
        "files": [{
            "content": "aGVsbG8=",
            "filename": "recovered.txt",
            "content_type": "text/plain",
            "size": 5,
        }],
    }
    expected_name = f"client-send-{intent_id.hex}-0.txt"
    storage_dir = (
        tmp_path
        / "media"
        / "chat_attachments"
        / str(test_widget.organization_id)
    )
    expected_path = storage_dir / expected_name

    with pytest.raises(
        SystemExit,
        match="crash-after-materialization-before-attachment-commit",
    ):
        await widget_chat.handle_agent_message("sid-first", dict(data))

    assert expected_path.read_bytes() == b"hello"
    assert [path.name for path in storage_dir.iterdir()] == [expected_name]
    assert db.query(FileAttachment).count() == 0

    replay = await widget_chat.handle_agent_message("sid-replay", dict(data))

    assert replay["status"] == "accepted"
    assert create_calls == 2
    assert delivery.await_count == 1
    assert expected_path.read_bytes() == b"hello"
    assert [path.name for path in storage_dir.iterdir()] == [expected_name]
    attachments = db.query(FileAttachment).filter(
        FileAttachment.chat_history_id == replay["message_id"]
    ).all()
    assert len(attachments) == 1
    assert attachments[0].file_url.endswith(f"/{expected_name}")


@pytest.mark.asyncio
async def test_existing_attachment_post_claim_crash_replay_adopts_once(
    db, test_widget, test_customer, test_user, monkeypatch
):
    uuid = __import__("uuid")
    session_id, _sio, delivery = await _make_handler_context(
        db, test_widget, test_customer, test_user, monkeypatch
    )
    attachment = FileAttachmentRepository(db).create_attachment(
        file_url="/api/v1/uploads/generated/recover.mp3",
        filename="recover.mp3",
        content_type="audio/mpeg",
        file_size=10,
        organization_id=test_widget.organization_id,
        uploaded_by_user_id=test_user.id,
    )
    original = FileAttachmentRepository.adopt_attachments
    calls = 0
    successful_adoptions = 0

    def crash_then_adopt(self, *args, **kwargs):
        nonlocal calls, successful_adoptions
        calls += 1
        if calls == 1:
            raise SystemExit("crash-before-adoption")
        successful_adoptions += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(FileAttachmentRepository, "adopt_attachments", crash_then_adopt)
    intent_id = uuid.uuid4()
    data = {
        "message": "",
        "session_id": str(session_id),
        "client_send_intent_id": str(intent_id),
        "attachment_ids": [attachment.id],
    }

    with pytest.raises(SystemExit, match="crash-before-adoption"):
        await widget_chat.handle_agent_message("sid-first", dict(data))
    replay = await widget_chat.handle_agent_message("sid-replay", dict(data))

    db.refresh(attachment)
    assert replay["status"] == "accepted"
    assert successful_adoptions == 1
    assert attachment.chat_history_id == replay["message_id"]
    assert delivery.await_count == 1


@pytest.mark.asyncio
async def test_end_chat_post_claim_crash_replay_mutates_once(
    db, test_widget, test_customer, test_user, monkeypatch
):
    uuid = __import__("uuid")
    session_id, _sio, delivery = await _make_handler_context(
        db, test_widget, test_customer, test_user, monkeypatch
    )
    original = SessionToAgentRepository.update_session_status
    calls = 0
    successful_mutations = 0

    def crash_then_close(self, *args, **kwargs):
        nonlocal calls, successful_mutations
        calls += 1
        if calls == 1:
            raise SystemExit("crash-before-end-chat-mutation")
        successful_mutations += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(SessionToAgentRepository, "update_session_status", crash_then_close)
    intent_id = uuid.uuid4()
    data = {
        "message": "chat closed",
        "session_id": str(session_id),
        "client_send_intent_id": str(intent_id),
        "message_type": "system",
        "end_chat": True,
        "request_rating": False,
        "end_chat_reason": "AGENT_REQUEST",
    }

    with pytest.raises(SystemExit, match="crash-before-end-chat-mutation"):
        await widget_chat.handle_agent_message("sid-first", dict(data))
    replay = await widget_chat.handle_agent_message("sid-replay", dict(data))

    assert replay["status"] == "accepted"
    assert successful_mutations == 1
    assert SessionToAgentRepository(db).get_session(session_id).status.name == "CLOSED"
    assert delivery.await_count == 1


@pytest.mark.asyncio
async def test_postgres_execution_guard_uses_nonblocking_advisory_claim(monkeypatch):
    class Result:
        def __init__(self, value):
            self.value = value

        def scalar_one(self):
            return self.value

    class Connection:
        def __init__(self):
            self.sql = []
            self.try_results = iter([False, True])
            self.closed = False

        def execute(self, statement, params):
            rendered = str(statement)
            self.sql.append((rendered, dict(params)))
            if "pg_try_advisory_lock" in rendered:
                return Result(next(self.try_results))
            return Result(True)

        def close(self):
            self.closed = True

    connection = Connection()
    bind = MagicMock()
    bind.dialect.name = "postgresql"
    bind.connect.return_value = connection
    fake_db = MagicMock()
    fake_db.get_bind.return_value = bind
    sleep = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", sleep)

    repo = ChatRepository(fake_db)
    async with repo.client_send_execution_guard(42):
        pass

    statements = [sql for sql, _params in connection.sql]
    assert statements.count("SELECT pg_try_advisory_lock(:lock_id)") == 2
    assert "SELECT pg_advisory_unlock(:lock_id)" in statements
    assert all("SELECT pg_advisory_lock(:lock_id)" != sql for sql in statements)
    sleep.assert_awaited_once()
    assert connection.closed is True

@pytest.mark.asyncio
async def test_postgres_execution_guard_keeps_event_loop_live_during_all_db_io():
    class Result:
        def scalar_one(self):
            return True

    io_thread_ids = []
    event_loop_thread_id = threading.get_ident()

    class Connection:
        def __init__(self):
            self.closed = False

        def execute(self, statement, params):
            io_thread_ids.append(threading.get_ident())
            time.sleep(0.08)
            return Result()

        def close(self):
            io_thread_ids.append(threading.get_ident())
            time.sleep(0.08)
            self.closed = True

    connection = Connection()

    class Dialect:
        name = "postgresql"

    class Bind:
        dialect = Dialect()

        def connect(self):
            io_thread_ids.append(threading.get_ident())
            time.sleep(0.08)
            return connection

    fake_db = MagicMock()
    fake_db.get_bind.return_value = Bind()
    repo = ChatRepository(fake_db)

    ticks = 0
    stop = asyncio.Event()

    async def ticker():
        nonlocal ticks
        while not stop.is_set():
            ticks += 1
            await asyncio.sleep(0.005)

    ticker_task = asyncio.create_task(ticker())
    started = time.perf_counter()
    try:
        async with repo.client_send_execution_guard(42):
            await asyncio.sleep(0.02)
    finally:
        stop.set()
        await ticker_task
    elapsed = time.perf_counter() - started

    assert elapsed >= 0.32
    assert ticks >= 20
    assert connection.closed is True
    assert io_thread_ids
    assert event_loop_thread_id not in io_thread_ids
    assert len(set(io_thread_ids)) == 1


class _AdversarialGuardResult:
    def __init__(self, value):
        self.value = value

    def scalar_one(self):
        return self.value


class _AdversarialGuardConnection:
    def __init__(
        self,
        owner,
        *,
        acquire_delay=0.0,
        unlock_delay=0.0,
        close_delay=0.0,
    ):
        self.owner = owner
        self.acquire_delay = acquire_delay
        self.unlock_delay = unlock_delay
        self.close_delay = close_delay
        self.closed = False
        self.thread_ids = []
        self.operations = []
        self.acquire_started = threading.Event()
        self.unlock_started = threading.Event()
        self.close_started = threading.Event()

    def execute(self, statement, params):
        rendered = str(statement)
        self.thread_ids.append(threading.get_ident())
        self.operations.append(rendered)
        if "pg_try_advisory_lock" in rendered:
            self.acquire_started.set()
            if self.acquire_delay:
                time.sleep(self.acquire_delay)
            with self.owner.state_lock:
                acquired = not self.owner.lock_held
                if acquired:
                    self.owner.lock_held = True
            return _AdversarialGuardResult(acquired)
        if "pg_advisory_unlock" in rendered:
            self.unlock_started.set()
            if self.unlock_delay:
                time.sleep(self.unlock_delay)
            with self.owner.state_lock:
                was_locked = self.owner.lock_held
                self.owner.lock_held = False
            return _AdversarialGuardResult(was_locked)
        raise AssertionError(f"unexpected guard SQL: {rendered}")

    def close(self):
        self.thread_ids.append(threading.get_ident())
        self.operations.append("close")
        self.close_started.set()
        if self.close_delay:
            time.sleep(self.close_delay)
        self.closed = True


class _AdversarialGuardBind:
    class Dialect:
        name = "postgresql"

    dialect = Dialect()

    def __init__(
        self,
        *,
        first_connect_delay=0.0,
        first_acquire_delay=0.0,
        first_unlock_delay=0.0,
        first_close_delay=0.0,
    ):
        self.first_connect_delay = first_connect_delay
        self.first_acquire_delay = first_acquire_delay
        self.first_unlock_delay = first_unlock_delay
        self.first_close_delay = first_close_delay
        self.connect_started = threading.Event()
        self.state_lock = threading.Lock()
        self.lock_held = False
        self.connections = []

    def connect(self):
        index = len(self.connections)
        connection = _AdversarialGuardConnection(
            self,
            acquire_delay=self.first_acquire_delay if index == 0 else 0.0,
            unlock_delay=self.first_unlock_delay if index == 0 else 0.0,
            close_delay=self.first_close_delay if index == 0 else 0.0,
        )
        self.connections.append(connection)
        if index == 0:
            self.connect_started.set()
            if self.first_connect_delay:
                time.sleep(self.first_connect_delay)
        return connection


class _TrackingGuardExecutor(ThreadPoolExecutor):
    shutdown_thread_ids = []

    def shutdown(self, wait=True, *, cancel_futures=False):
        type(self).shutdown_thread_ids.append(threading.get_ident())
        return super().shutdown(wait=wait, cancel_futures=cancel_futures)


async def _wait_thread_event(event, timeout=2.0):
    deadline = time.perf_counter() + timeout
    while not event.is_set():
        assert time.perf_counter() < deadline, "timed out waiting for worker phase"
        await asyncio.sleep(0.001)


async def _start_guard_ticker():
    state = {"ticks": 0}
    stop = asyncio.Event()

    async def ticker():
        while not stop.is_set():
            state["ticks"] += 1
            await asyncio.sleep(0.005)

    task = asyncio.create_task(ticker())
    return state, stop, task


def _assert_guard_worker_retired():
    assert not any(
        thread.name.startswith("client-send-pg-guard")
        for thread in threading.enumerate()
    )


@pytest.mark.asyncio
async def test_postgres_execution_guard_slow_connect_cancel_keeps_loop_live_and_recovers(
    monkeypatch,
):
    _TrackingGuardExecutor.shutdown_thread_ids = []
    monkeypatch.setattr(
        chat_repository_module, "ThreadPoolExecutor", _TrackingGuardExecutor
    )
    event_loop_thread_id = threading.get_ident()
    bind = _AdversarialGuardBind(first_connect_delay=0.20)
    fake_db = MagicMock()
    fake_db.get_bind.return_value = bind
    repo = ChatRepository(fake_db)

    entered_body = False

    async def holder():
        nonlocal entered_body
        async with repo.client_send_execution_guard(42):
            entered_body = True

    ticker_state, ticker_stop, ticker_task = await _start_guard_ticker()
    task = asyncio.create_task(holder())
    await _wait_thread_event(bind.connect_started)
    await asyncio.sleep(0.02)
    ticks_at_cancel = ticker_state["ticks"]
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    ticks_after_cancel = ticker_state["ticks"]

    assert entered_body is False
    assert ticks_after_cancel - ticks_at_cancel >= 10
    assert len(bind.connections) == 1
    first = bind.connections[0]
    assert first.closed is True
    assert first.operations == ["close"]
    assert bind.lock_held is False
    assert first.thread_ids
    assert len(set(first.thread_ids)) == 1
    assert event_loop_thread_id not in first.thread_ids
    assert _TrackingGuardExecutor.shutdown_thread_ids
    assert event_loop_thread_id not in _TrackingGuardExecutor.shutdown_thread_ids
    _assert_guard_worker_retired()

    # A same-intent contender must recover after the cancelled guard settles.
    async with repo.client_send_execution_guard(42):
        assert bind.lock_held is True
    second = bind.connections[1]
    assert second.closed is True
    assert bind.lock_held is False
    assert "SELECT pg_try_advisory_lock(:lock_id)" in second.operations
    assert "SELECT pg_advisory_unlock(:lock_id)" in second.operations
    assert len(set(second.thread_ids)) == 1
    _assert_guard_worker_retired()

    ticker_stop.set()
    await ticker_task


@pytest.mark.asyncio
async def test_postgres_execution_guard_slow_acquire_cancel_settles_lock_without_leak(
    monkeypatch,
):
    _TrackingGuardExecutor.shutdown_thread_ids = []
    monkeypatch.setattr(
        chat_repository_module, "ThreadPoolExecutor", _TrackingGuardExecutor
    )
    event_loop_thread_id = threading.get_ident()
    bind = _AdversarialGuardBind(first_acquire_delay=0.20)
    fake_db = MagicMock()
    fake_db.get_bind.return_value = bind
    repo = ChatRepository(fake_db)

    async def holder():
        async with repo.client_send_execution_guard(42):
            raise AssertionError("cancelled acquire must not enter guarded body")

    ticker_state, ticker_stop, ticker_task = await _start_guard_ticker()
    task = asyncio.create_task(holder())
    while not bind.connections:
        await asyncio.sleep(0.001)
    await _wait_thread_event(bind.connections[0].acquire_started)
    await asyncio.sleep(0.02)
    ticks_at_cancel = ticker_state["ticks"]
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    ticks_after_cancel = ticker_state["ticks"]

    first = bind.connections[0]
    assert ticks_after_cancel - ticks_at_cancel >= 10
    assert first.closed is True
    assert bind.lock_held is False
    assert first.operations == [
        "SELECT pg_try_advisory_lock(:lock_id)",
        "SELECT pg_advisory_unlock(:lock_id)",
        "close",
    ]
    assert len(set(first.thread_ids)) == 1
    assert event_loop_thread_id not in first.thread_ids
    assert event_loop_thread_id not in _TrackingGuardExecutor.shutdown_thread_ids
    _assert_guard_worker_retired()

    async with repo.client_send_execution_guard(42):
        assert bind.lock_held is True
    assert bind.lock_held is False
    _assert_guard_worker_retired()

    ticker_stop.set()
    await ticker_task


@pytest.mark.asyncio
async def test_postgres_execution_guard_cancel_during_unlock_close_settlement_is_shielded(
    monkeypatch,
):
    _TrackingGuardExecutor.shutdown_thread_ids = []
    monkeypatch.setattr(
        chat_repository_module, "ThreadPoolExecutor", _TrackingGuardExecutor
    )
    event_loop_thread_id = threading.get_ident()
    bind = _AdversarialGuardBind(
        first_unlock_delay=0.12,
        first_close_delay=0.12,
    )
    fake_db = MagicMock()
    fake_db.get_bind.return_value = bind
    repo = ChatRepository(fake_db)

    async def holder():
        async with repo.client_send_execution_guard(42):
            assert bind.lock_held is True

    ticker_state, ticker_stop, ticker_task = await _start_guard_ticker()
    task = asyncio.create_task(holder())
    while not bind.connections:
        await asyncio.sleep(0.001)
    first = bind.connections[0]
    await _wait_thread_event(first.unlock_started)
    ticks_at_cancel = ticker_state["ticks"]
    task.cancel()

    # Repeated cancellation while close is outstanding must not abort settlement.
    await _wait_thread_event(first.close_started)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    ticks_after_cancel = ticker_state["ticks"]

    assert ticks_after_cancel - ticks_at_cancel >= 15
    assert first.closed is True
    assert bind.lock_held is False
    assert first.operations == [
        "SELECT pg_try_advisory_lock(:lock_id)",
        "SELECT pg_advisory_unlock(:lock_id)",
        "close",
    ]
    assert len(set(first.thread_ids)) == 1
    assert event_loop_thread_id not in first.thread_ids
    assert len(_TrackingGuardExecutor.shutdown_thread_ids) == 1
    assert event_loop_thread_id not in _TrackingGuardExecutor.shutdown_thread_ids
    _assert_guard_worker_retired()

    # The released advisory lock must be immediately usable by the next contender.
    async with repo.client_send_execution_guard(42):
        assert bind.lock_held is True
    assert bind.lock_held is False
    _assert_guard_worker_retired()

    ticker_stop.set()
    await ticker_task
