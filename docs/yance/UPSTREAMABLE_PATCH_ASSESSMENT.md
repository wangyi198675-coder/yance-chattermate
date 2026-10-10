# Phase 3D Upstreamable Patch Assessment

`SOURCE_IMPLEMENTATION_HEAD = 0ce0285572cd74e6b94f2086f9bdddc63055b21b`

## Verdict

`UPSTREAMABLE_PATCH = PASS_FOR_CANONICAL_PRODUCTION_ENTRYPOINT`

This patch corrects ChatterMate's existing Knowledge Processor lifecycle using only Python/asyncio primitives and the existing `knowledge_queue` authority. It introduces no Yance-branded worker framework and no alternate durable job authority.

## Changed production files

- `backend/app/workers/knowledge_processor.py`
- `backend/app/repositories/knowledge_queue.py`

Test coverage is in `backend/yance_tests/test_knowledge_processor_lifecycle.py`.

## Exact rationale

Before this correction, a KnowledgeQueue row was committed `PROCESSING` before long ingestion work. Python 3.12 `asyncio.CancelledError` is not caught by `except Exception`, so process shutdown could leave the canonical row permanently `PROCESSING`. There was also no stale startup recovery and no cooperative stop/drain contract.

The correction:

1. uses an `asyncio.Event` as the worker-local stop request;
2. stops scheduling new PENDING items after stop;
3. allows current work to drain for a bounded interval;
4. cancels after the bound and explicitly settles the same canonical row to FAILED;
5. recovers stale PROCESSING rows once on service startup, also to FAILED;
6. never blind-requeues because ingestion replay idempotency is not proven;
7. adds no schema/table/queue/scheduler/heartbeat/retry authority.

Machine-readable failure reasons:

- `knowledge_worker_interrupted:cancelled`
- `knowledge_worker_interrupted:stale_processing`

## Entry-point scope

Window 8 production authority already identifies `app.workers.knowledge_processor` as the retained production worker module. This is the lifecycle-qualified entrypoint.

`app.workers.run_knowledge_processor` remains an upstream alternate/legacy runner and is **not** admitted as the Window 8 production entrypoint by this patch. No FAQ/CRM/Ticket refactor was performed merely to normalize alternate launch paths.

## Upstream-removal path

When a future ChatterMate stable release contains equivalent or stronger lifecycle semantics:

1. update the upstream baseline through normal Master Controller admission;
2. run the Phase 3D lifecycle tests against the upstream implementation;
3. remove/revert private patch commits `0ce0285572cd74e6b94f2086f9bdddc63055b21b` then `fe272857a01eeba2d44e60655077167e8b6a8f00` if their behavior is fully superseded;
4. preserve upstream provenance and avoid maintaining parallel lifecycle code.
