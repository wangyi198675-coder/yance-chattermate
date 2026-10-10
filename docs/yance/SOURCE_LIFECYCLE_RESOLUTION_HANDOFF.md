# SOURCE_LIFECYCLE_RESOLUTION_HANDOFF

## Source authority

`SOURCE_HEAD = 0ce0285572cd74e6b94f2086f9bdddc63055b21b`

`BRANCH = yance/clean-rebase-20261005`

Changed production files:

- `backend/app/workers/knowledge_processor.py`
- `backend/app/repositories/knowledge_queue.py`

No migration/schema file changed.

## Lifecycle contract

`stop request -> no new claims -> bounded drain current pass -> if timeout cancel -> current PROCESSING row FAILED -> worker exits`

Startup contract:

`service start -> fail stale PROCESSING rows in existing knowledge_queue -> FAILED -> begin polling`

There is no automatic stale requeue.

## Stop invocation contract for Window 8

Canonical retained production entrypoint:

`python -m app.workers.knowledge_processor`

Application stop primitive:

- native process signal handler maps `SIGINT` / `SIGTERM` (and `SIGBREAK` where available) into the worker-local `asyncio.Event`;
- Window 8's existing Process Compose `shutdown.signal: 2` (SIGINT) is the intended stop trigger;
- `shutdown.command = OMIT / NOT REQUIRED`;
- do **not** create a signal relay, stop daemon, helper service, or custom supervisor command.

Window 8 must set the knowledge-worker supervisor timeout greater than the application drain bound. Default application bound:

`KNOWLEDGE_DRAIN_TIMEOUT_SECONDS = 30`

Recommended Process Compose knowledge-worker `shutdown.timeout_seconds >= 35` (or another admitted margin above the configured drain value). The current 10-second smoke value is insufficient for the default 30-second application drain and should be adjusted by Window 8 during runtime verification.

## Drain timeout semantics

If active knowledge work completes before the drain bound, its existing normal completion path persists `COMPLETED` and the worker exits cleanly.

If the bound expires, the active asyncio task is cancelled. `process_queue_item` explicitly catches `asyncio.CancelledError`, rolls back transient session state, reloads the existing canonical queue row, and if it is still `PROCESSING` persists:

- `status = FAILED`
- `error = knowledge_worker_interrupted:cancelled`

Then cancellation is re-raised so shutdown completes.

## Stale recovery semantics

On canonical service-loop startup only, existing rows where:

`status = PROCESSING`

and:

`coalesce(updated_at, created_at) < now - KNOWLEDGE_STALE_PROCESSING_SECONDS`

(default 900 seconds) are settled in place to:

- `status = FAILED`
- `error = knowledge_worker_interrupted:stale_processing`

No new job row is created.

## Replay decision

`AUTOMATIC_REQUEUE = FORBIDDEN`

Knowledge ingestion can persist database/vector/file side effects before the queue row reaches COMPLETED. End-to-end replay idempotency was not proven for every interruption point, therefore stale/cancelled work fails closed instead of blind replay.

## Test evidence

- Phase 3D lifecycle tests: 10/10 PASS
- Existing ChatterMate Knowledge Processor tests: 12/12 PASS using a temporary test bootstrap only to avoid unrelated eager FastAPI/model imports
- Existing Yance focused tests: 14/14 PASS
- compileall: PASS
- migration graph: 100 revisions / one head `yance_persona_history_002` / 0 missing
- schema expansion: 0

## Rollback

If this patch must be rolled back before an upstream replacement is admitted, revert source commits in reverse order:

1. `0ce0285572cd74e6b94f2086f9bdddc63055b21b`
2. `fe272857a01eeba2d44e60655077167e8b6a8f00`

Do not delete or mutate user knowledge data as part of rollback.
