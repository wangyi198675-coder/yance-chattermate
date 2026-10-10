import asyncio
import importlib.util
import sys
import types
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

BACKEND = Path(__file__).resolve().parents[1]
WORKER = BACKEND / "app" / "workers" / "knowledge_processor.py"
REPOSITORY = BACKEND / "app" / "repositories" / "knowledge_queue.py"


def _install(name, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


def _load_worker():
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]

    app = _install("app")
    app.__path__ = []
    workers = _install("app.workers")
    workers.__path__ = []
    repos = _install("app.repositories")
    repos.__path__ = []
    knowledge_pkg = _install("app.knowledge")
    knowledge_pkg.__path__ = []
    services = _install("app.services")
    services.__path__ = []
    models = _install("app.models")
    models.__path__ = []
    core = _install("app.core")
    core.__path__ = []

    class QueueStatus(str, Enum):
        PENDING = "pending"
        PROCESSING = "processing"
        COMPLETED = "completed"
        FAILED = "failed"

    class ProcessingStage(str, Enum):
        NOT_STARTED = "not_started"
        CRAWLING = "crawling"
        EMBEDDING = "embedding"
        COMPLETED = "completed"

    class KnowledgeQueue:
        status = MagicMock()
        updated_at = MagicMock()
        created_at = MagicMock()

    class Notification:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class NotificationType:
        KNOWLEDGE_PROCESSED = "knowledge_processed"
        KNOWLEDGE_FAILED = "knowledge_failed"

    page_editor = _install("app.knowledge.page_editor", agent_ids_for=lambda _: [])
    knowledge_pkg.page_editor = page_editor
    vector_links = _install("app.services.knowledge_vector_links", sync_agent_ids=lambda *a, **k: None)
    services.knowledge_vector_links = vector_links

    _install("app.database", SessionLocal=MagicMock())
    _install("app.repositories.knowledge_queue", KnowledgeQueueRepository=MagicMock)
    _install("app.repositories.knowledge", KnowledgeRepository=MagicMock)
    _install("app.knowledge.knowledge_base", KnowledgeManager=MagicMock)
    _install(
        "app.models.knowledge_queue",
        KnowledgeQueue=KnowledgeQueue,
        QueueStatus=QueueStatus,
        ProcessingStage=ProcessingStage,
    )
    _install("app.core.logger", get_logger=lambda _: MagicMock())
    _install("app.core.processor", PROCESSOR_STATUS={"is_running": False, "error": None, "last_run": None})
    _install("app.models.notification", Notification=Notification, NotificationType=NotificationType)
    _install("app.services.user", send_fcm_notification=AsyncMock())

    spec = importlib.util.spec_from_file_location("app.workers.knowledge_processor", WORKER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module, QueueStatus, ProcessingStage, KnowledgeQueue


def _session_local(db):
    cm = MagicMock()
    cm.__enter__.return_value = db
    cm.__exit__.return_value = False
    return MagicMock(return_value=cm)


def _queue_item(status):
    return SimpleNamespace(
        id=7,
        organization_id="org",
        agent_id=None,
        user_id="user",
        source="https://example.com/doc",
        source_type="website",
        status=status,
        processing_stage=None,
        progress_percentage=0.0,
        error=None,
    )


@pytest.mark.asyncio
async def test_normal_processing_completes_existing_canonical_row():
    worker, QueueStatus, _, _ = _load_worker()
    db = MagicMock()
    item = _queue_item(QueueStatus.PENDING)
    repo = MagicMock()
    repo.get_by_id.return_value = item
    manager = MagicMock()
    manager.process_knowledge = AsyncMock()
    worker.SessionLocal = _session_local(db)
    worker.KnowledgeQueueRepository = MagicMock(return_value=repo)
    worker.KnowledgeManager = MagicMock(return_value=manager)
    worker.KnowledgeRepository = MagicMock(return_value=MagicMock(get_by_sources=MagicMock(return_value=[])))
    worker.send_fcm_notification = AsyncMock()

    await worker.process_queue_item(item.id)

    assert item.status is QueueStatus.COMPLETED
    assert item.id == 7
    manager.process_knowledge.assert_awaited_once_with(item)


@pytest.mark.asyncio
async def test_cancelled_processing_fails_closed_and_reraises_cancel():
    worker, QueueStatus, _, _ = _load_worker()
    db = MagicMock()
    item = _queue_item(QueueStatus.PENDING)
    repo = MagicMock()
    repo.get_by_id.return_value = item
    manager = MagicMock()
    manager.process_knowledge = AsyncMock(side_effect=asyncio.CancelledError())
    worker.SessionLocal = _session_local(db)
    worker.KnowledgeQueueRepository = MagicMock(return_value=repo)
    worker.KnowledgeManager = MagicMock(return_value=manager)
    worker.send_fcm_notification = AsyncMock()

    with pytest.raises(asyncio.CancelledError):
        await worker.process_queue_item(item.id)

    assert item.status is QueueStatus.FAILED
    assert item.processing_stage != "COMPLETED"
    assert item.error == worker.INTERRUPTED_CANCELLED_REASON
    assert item.id == 7
    db.rollback.assert_called()
    db.commit.assert_called()


def test_repository_marks_stale_processing_failed_without_creating_job():
    worker, QueueStatus, _, KnowledgeQueue = _load_worker()
    sys.modules.pop("app.repositories.knowledge_queue", None)
    repo_spec = importlib.util.spec_from_file_location("app.repositories.knowledge_queue", REPOSITORY)
    repo_module = importlib.util.module_from_spec(repo_spec)
    sys.modules[repo_spec.name] = repo_module
    repo_spec.loader.exec_module(repo_module)

    db = MagicMock()
    item = _queue_item(QueueStatus.PROCESSING)
    query = db.query.return_value
    query.filter.return_value.all.return_value = [item]
    repo = repo_module.KnowledgeQueueRepository(db)

    count = repo.fail_stale_processing(older_than_seconds=30, reason="machine:interrupted")

    assert count == 1
    assert item.status is QueueStatus.FAILED
    assert item.error == "machine:interrupted"
    assert item.id == 7
    db.add.assert_not_called()
    db.commit.assert_called_once()


def test_startup_recovery_delegates_to_existing_queue_authority():
    worker, _, _, _ = _load_worker()
    db = MagicMock()
    repo = MagicMock()
    repo.fail_stale_processing.return_value = 2
    worker.SessionLocal = _session_local(db)
    worker.KnowledgeQueueRepository = MagicMock(return_value=repo)

    recovered = worker.recover_stale_processing(older_than_seconds=45)

    assert recovered == 2
    repo.fail_stale_processing.assert_called_once_with(
        older_than_seconds=45,
        reason=worker.INTERRUPTED_STALE_REASON,
    )


@pytest.mark.asyncio
async def test_stop_request_prevents_new_pending_claims():
    worker, _, _, _ = _load_worker()
    stop_event = asyncio.Event()
    stop_event.set()
    worker.SessionLocal = MagicMock()

    await worker.run_processor(stop_event=stop_event)

    worker.SessionLocal.assert_not_called()


@pytest.mark.asyncio
async def test_bounded_drain_allows_current_work_to_finish_cleanly():
    worker, _, _, _ = _load_worker()
    started = asyncio.Event()
    release = asyncio.Event()
    cancelled = False

    async def current_pass(stop_event=None):
        nonlocal cancelled
        started.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled = True
            raise

    worker.run_processor = current_pass
    worker.recover_stale_processing = MagicMock(return_value=0)
    stop_event = asyncio.Event()
    task = asyncio.create_task(worker.run_processor_loop(stop_event, poll_interval=60, drain_timeout=0.25))
    await started.wait()
    stop_event.set()
    release.set()
    await task

    assert cancelled is False


@pytest.mark.asyncio
async def test_bounded_drain_timeout_cancels_current_work_and_exits():
    worker, _, _, _ = _load_worker()
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def never_finishes(stop_event=None):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    worker.run_processor = never_finishes
    worker.recover_stale_processing = MagicMock(return_value=0)
    stop_event = asyncio.Event()
    task = asyncio.create_task(worker.run_processor_loop(stop_event, poll_interval=60, drain_timeout=0.01))
    await started.wait()
    stop_event.set()
    await task

    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_service_loop_recovers_stale_processing_once_at_startup():
    worker, _, _, _ = _load_worker()
    calls = 0
    pass_started = asyncio.Event()
    stop_event = asyncio.Event()

    def recover(older_than_seconds=worker.DEFAULT_STALE_PROCESSING_SECONDS):
        nonlocal calls
        calls += 1
        return 0

    async def one_pass(stop_event=None):
        pass_started.set()
        stop_event.set()

    worker.recover_stale_processing = recover
    worker.run_processor = one_pass

    await worker.run_processor_loop(stop_event, poll_interval=60, drain_timeout=0.1)

    assert pass_started.is_set()
    assert calls == 1


@pytest.mark.asyncio
async def test_bounded_drain_success_completes_the_current_canonical_row():
    worker, QueueStatus, _, _ = _load_worker()
    db = MagicMock()
    item = _queue_item(QueueStatus.PENDING)
    repo = MagicMock()
    repo.get_pending.return_value = [item]
    repo.get_by_id.return_value = item
    repo.fail_stale_processing.return_value = 0
    started = asyncio.Event()
    release = asyncio.Event()

    async def process(_item):
        started.set()
        await release.wait()

    manager = MagicMock()
    manager.process_knowledge = AsyncMock(side_effect=process)
    worker.SessionLocal = _session_local(db)
    worker.KnowledgeQueueRepository = MagicMock(return_value=repo)
    worker.KnowledgeManager = MagicMock(return_value=manager)
    worker._sync_vector_agent_links = MagicMock()
    worker.send_fcm_notification = AsyncMock()

    stop_event = asyncio.Event()
    loop_task = asyncio.create_task(
        worker.run_processor_loop(stop_event, poll_interval=60, drain_timeout=0.25)
    )
    await started.wait()
    stop_event.set()
    release.set()
    await loop_task

    assert item.status is QueueStatus.COMPLETED
    assert item.id == 7


@pytest.mark.asyncio
async def test_bounded_drain_timeout_settles_processing_failed_closed():
    worker, QueueStatus, _, _ = _load_worker()
    db = MagicMock()
    item = _queue_item(QueueStatus.PENDING)
    repo = MagicMock()
    repo.get_pending.return_value = [item]
    repo.get_by_id.return_value = item
    repo.fail_stale_processing.return_value = 0
    started = asyncio.Event()

    async def process(_item):
        started.set()
        await asyncio.Event().wait()

    manager = MagicMock()
    manager.process_knowledge = AsyncMock(side_effect=process)
    worker.SessionLocal = _session_local(db)
    worker.KnowledgeQueueRepository = MagicMock(return_value=repo)
    worker.KnowledgeManager = MagicMock(return_value=manager)
    worker.send_fcm_notification = AsyncMock()

    stop_event = asyncio.Event()
    loop_task = asyncio.create_task(
        worker.run_processor_loop(stop_event, poll_interval=60, drain_timeout=0.01)
    )
    await started.wait()
    stop_event.set()
    await loop_task

    assert item.status is QueueStatus.FAILED
    assert item.error == worker.INTERRUPTED_CANCELLED_REASON
    assert item.id == 7
    db.rollback.assert_called()
