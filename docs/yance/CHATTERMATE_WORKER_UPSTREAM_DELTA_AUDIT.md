# CHATTERMATE_WORKER_UPSTREAM_DELTA_AUDIT

## Authority checked

- stable baseline: `v1.0.25` / `eea5d62883c7b2130f3466c9c2aad5b1b2bf904e`
- current upstream main (fresh fetch): `82df312654abfbd146f1b1f3fdc027b143e6a8c0`
- upstream main latest commit date observed: 2026-09-28
- latest stable tag observed: `v1.0.25`

There is no newer formal stable release.

## Delta result

Upstream main is 11 commits ahead of v1.0.25, but none of those commits changes:

- `backend/app/workers/knowledge_processor.py`
- `backend/app/workers/run_knowledge_processor.py`
- `backend/app/workers/faq_processor.py`
- `backend/app/workers/crm_sync.py`
- `backend/app/workers/ticket_investigator.py`
- `backend/app/repositories/knowledge_queue.py`
- `backend/app/repositories/faq_generation_job.py`
- `backend/app/repositories/crm.py`
- `backend/app/repositories/ticket.py`

There is also no local Yance delta in those paths between v1.0.25 and the Phase 3C starting HEAD. The lifecycle behavior below is retained ChatterMate behavior, not a Yance custom implementation.

## Upstream issue / PR freshness

Fresh GitHub API searches covered graceful shutdown, cancellation, worker drain, stale `PROCESSING`, orphan recovery, requeue, knowledge processor, CRM sync, ticket investigator, and FAQ processor.

Observed current open PR set contained only PR #146, an old Coolify deployment change touching Docker files. It is unrelated to worker lifecycle.

No open issue, merged unreleased PR, or current-main commit supplies a Knowledge Processor drain/cancellation/stale-recovery fix.

Therefore:

- `UPSTREAM_BASELINE_UPDATE_CANDIDATE = NONE`
- `SELECTIVE_UPSTREAM_BACKPORT_REQUEST = NONE`

## Native worker lifecycle findings

### Knowledge Processor — HARD GAP

Current flow selects all `PENDING` rows, then each task writes `PROCESSING`, commits, and awaits ingestion. There is no durable claim lease, stale `PROCESSING` recovery, startup orphan recovery, `CancelledError` settlement, SIGTERM/SIGINT application drain hook, or requeue path.

If the process is terminated after the `PROCESSING` commit and before the terminal status write, the row can remain `PROCESSING` indefinitely.

### CRM Sync — mature native semantics already present

The native repository/worker already has:

- atomic batch claim using `FOR UPDATE SKIP LOCKED`
- stale claim reclaim
- retry scheduling with backoff/jitter
- unique/idempotency constraint
- transactional rollback before retry write

No external lifecycle owner is justified for CRM Sync.

### FAQ Processor — crash orphan recovery present, graceful drain still thin

The worker reaps `processing` jobs once at startup via `fail_orphaned_processing(...)`. A crash does not leave the UI/job guard stuck forever, although restart recovery marks the interrupted job failed rather than resuming it.

### Ticket Investigator — crash orphan recovery present

The worker invokes `reap_orphaned_runs()` at startup. Investigation runs therefore have application-native orphan cleanup, although the forever-loop has no separate Windows drain protocol.

## Upstream conclusion

`RETAINED_CHATTERMATE_WORKER_APPLICATION_LIFECYCLE_GAP = KNOWLEDGE_PROCESSOR`

No upstream fix or backport candidate currently closes it.
