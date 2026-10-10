# APPLICATION_WORKER_LIFECYCLE_AUDIT_RESULT

## Final Phase 3C decision

`WORKER_LIFECYCLE = HOLD_NO_MATURE_OWNER`

`NO_MATURE_APPLICATION_WORKER_OWNER_FOUND = TRUE`

`CUSTOM_EXCEPTION_CANDIDATE = KNOWLEDGE_PROCESSOR_MINIMAL_APPLICATION_NATIVE_LIFECYCLE`

`CUSTOM_SUBSYSTEM_EXCEPTION_APPROVED = 0`

No custom lifecycle implementation was performed.

## Why mature queue frameworks were not selected

A mature queue can solve heartbeat, retry, stale work, and graceful shutdown only by owning job lifecycle state. ChatterMate already has domain-specific canonical job records and UI/API contracts:

- `knowledge_queue`
- FAQ generation jobs
- CRM sync jobs
- ticket investigation runs

The strongest external candidates create their own queue/job/status/retry/heartbeat state. Using them merely as wrappers would create two authorities for whether a business job is queued, running, failed, retrying, or complete. Replacing ChatterMate's existing job tables would be a broad architecture rewrite rather than a thin lifecycle owner.

The current doctrine therefore rejects those frameworks despite their maturity.

## Minimal custom-exception candidate — NOT IMPLEMENTED

Only if Master Controller separately approves an exception, the unavoidable Knowledge Processor semantics should remain application-native and narrow:

1. stop claiming new `PENDING` knowledge work when application shutdown/cancellation begins;
2. bounded drain of already-started tasks;
3. deterministic settlement of an interrupted `PROCESSING` row on `asyncio.CancelledError` / process shutdown, using the existing `knowledge_queue` authority rather than another job database;
4. startup/stale recovery for an old `PROCESSING` row, using existing timestamps/status and a conservative threshold;
5. idempotency proof before any automatic requeue; if the ingestion operation cannot be proven safe to repeat, fail closed instead of blind replay;
6. no new scheduler, queue DB, retry DB, or worker framework.

This is a candidate semantic boundary only. `CUSTOM_SUBSYSTEM_EXCEPTION_APPROVED = 0`, so no source changes are authorized in Phase 3C.
