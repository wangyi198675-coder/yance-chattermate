# PHASE3C_TEST_RESULTS

## Audited HEAD

`6468eb41ca77cb4f67c668cf0a2f4e88be4c9b71`

Branch: `yance/clean-rebase-20261005`

## Backend focused regression

The five Yance focused files were executed independently to avoid package-stub cross-test contamination.

- `test_person_identity.py`: 3/3 PASS
- `test_personal_social_contract.py`: 2/2 PASS
- `test_persona_history.py`: 2/2 PASS
- `test_deterministic_media_adapter.py`: 4/4 PASS
- `test_yance_owner_contract.py`: 3/3 PASS

Total: **14/14 PASS**.

Environment note: the repo-local ignored `.venv-yance` had drifted to a minimal state missing `pytest-cov` and `psycopg`. The first preflight exited before meaningful test execution. The rerun used `-o addopts=` to bypass unavailable coverage-only pytest options and installed `psycopg[binary]` into that ignored test venv. `backend/requirements.txt` already requires `psycopg[binary]>=3.1.0`; no requirements or production source file was changed. Final focused tests passed.

## Phase 3C static contract assertions

PASS:

- translation owner remains `NO_OWNER_SELECTED`
- no `argos_translate` owner remains
- model catalog keeps provider `custom_allowed=True` behavior
- Knowledge Processor still demonstrates the audited gap: commits `PROCESSING`, has no stale/orphan reclaim, has no `CancelledError` settlement
- CRM Sync has `reclaim_stale + claim_batch + schedule_retry`
- FAQ Processor has `fail_orphaned_processing`
- Ticket Investigator has `reap_orphaned_runs`
- production-source delta from accepted Phase 3B HEAD = **0 files**

## Build / schema gates

- Python `compileall backend/app`: PASS
- Alembic revisions: 100
- Alembic heads: `yance_persona_history_002`
- missing migration references: 0
- migration graph: PASS
- Frozen Yance UI `YanceShellView.spec.ts`: 4/4 PASS
- TypeScript `vue-tsc`: PASS
- production Vite/PWA build: PASS
- `git diff --check`: PASS

The production build retained existing non-blocking warnings: `always-auth` npm config warning, Firebase build-time key absent for background push, and large bundle/chunk warnings.

## External qualification smokes

- PgQueuer `1.5.0` base import on Windows Python 3.12.15: PASS
- PgQueuer `1.5.0` with `asyncpg 0.31.0` import: PASS
- Procrastinate `3.10.0` package install: PASS; bare Windows import: FAIL because no libpq/psycopg binary wrapper was available by default. This is additional evidence only; the candidate is rejected primarily for duplicate job-state authority and upstream Windows-production guidance.
- ChatterMate provider credential presence audit: no supported provider key found in Process/User/Machine environment; no real `.env`; no active local PostgreSQL/DATABASE_URL from which a legitimate AIConfig could be inspected.
- Graphiti current-main source freshness: packaging defect remains present; upstream fix PRs are still open.

## Phase verdicts under test

`TRANSLATION = HOLD_OWNER_PRODUCTION_QUALIFICATION`

`WORKER_LIFECYCLE = HOLD_NO_MATURE_OWNER`

`GRAPHITI_0_30_2 = HOLD_OWNER_PRODUCTION_QUALIFICATION`
