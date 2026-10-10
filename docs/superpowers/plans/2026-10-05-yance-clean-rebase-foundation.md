# Yance Clean Rebase Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce the first auditable, runnable Yance clean-rebase source foundation on ChatterMate v1.0.25 without porting retired Yance implementation.

**Architecture:** Keep ChatterMate mature backend owners intact, add a thin Customer-linked identity extension and a separate Vue Yance presentation layer, then define personal-social/runtime boundaries as contracts. Frozen UI/interaction authority remains external and immutable.

**Tech Stack:** Vue 3 + TypeScript + Vite/Vitest; FastAPI + SQLAlchemy + Alembic + PostgreSQL; ChatterMate channel abstractions.

**Spec:** `docs/superpowers/specs/2026-10-05-yance-chattermate-clean-rebase-design.md`

## Global Constraints

- Upstream baseline: v1.0.25 / `eea5d62883c7b2130f3466c9c2aad5b1b2bf904e`.
- Do not modify `C:\YanceController\current-app` or retired Yance runtime/source.
- Primary registry SHA-256 must remain `5be68b72e1afc027590cdef271e2cf10cd09140aaff6fee5aca9c1b9c1a50213`.
- Secondary registry SHA-256 must remain `fb64957cb15ec0ceefc9b35e3b2af9b86de8cb8faf91017c0a3535133fac58d6`.
- `Customer` is canonical Person; no second Yance contact database.
- Hide/de-present before deleting mature upstream capabilities.
- No product UI may display internal authority/spec/governance annotation.
- Personal social transports are adapters only and are not falsely marked GREEN.
- No production deploy or Windows runtime packaging in this workstream.
- `NO_CUSTOM_BY_DEFAULT` is a hard admission gate for all non-UI subsystem work.
- Before any non-UI subsystem code beyond thin adapters, record fresh alternatives, latest versions, maintenance, license, Windows compatibility and extension/API fit; custom code is forbidden unless `NO_MATURE_UPSTREAM_OWNER_FOUND` is proven.
- The Yance-exclusive sections in this plan define product semantics only; they do not authorize Yance-owned memory/persona/learning/translation/media/voice/scheduler/queue/routing/send/runtime engines.

## Review Focus

- Stale identity lookup must resolve to the surviving Customer without identity loops.
- Cross-organization identity lookup must never collide or leak.
- Channel-account-scoped identities must coexist with global email/phone identities.
- Yance shell must not render internal design-authority language or fake capability status.
- Upstream routes/services remain available internally while enterprise/support presentation is only de-presented.

### Task 1: Baseline receipts and authority ledger

**Files:** `docs/yance/*`, `docs/superpowers/*`

- [ ] Record upstream repository/tag/commit/license/release/lock hashes and clean state.
- [ ] Record new Git authority and provenance.
- [ ] Write KEEP/HIDE/DELETE presentation matrix.
- [ ] Generate all-152 delta ledger plus extra upstream capability ledger without runtime-GREEN inflation.
- [ ] Record personal-social and Windows runtime handoff contracts.
- [ ] Commit documentation foundation.

### Task 2: Canonical PersonIdentity thin extension

**Files:**
- Create: `backend/app/models/person_identity.py`
- Create: `backend/app/repositories/person_identity.py`
- Create: `backend/alembic/versions/yance_person_identity_001.py`
- Create: `backend/tests/yance/test_person_identity.py`
- Modify: model registration only where required by upstream conventions.

**Interfaces:**
- Produces `PersonIdentity` linked to canonical `Customer` and optional `ChannelAccount`.
- Produces repository methods to normalize lookup scope, resolve active/stale identity to surviving Customer, and redirect stale identities.

- [ ] Write failing identity model/repository tests.
- [ ] Run focused tests and verify RED for missing module/model.
- [ ] Implement minimal model/repository/migration.
- [ ] Run focused tests GREEN, then adjacent backend tests available in the isolated dev environment.
- [ ] Commit PersonIdentity extension.

### Task 3: Personal social transport interface

**Files:**
- Create: `backend/app/channels/personal_social/base.py`
- Create: `backend/tests/yance/test_personal_social_contract.py`

**Interfaces:** Transport-only abstract contract for connection lifecycle, messages, receipts, media, backfill, identity, routing, error and health. No Person/Relationship/Persona/Memory/Brain persistence API.

- [ ] Write failing contract-shape tests.
- [ ] Verify RED.
- [ ] Implement the minimal typed interface/data contracts.
- [ ] Verify GREEN.
- [ ] Commit transport boundary.

### Task 4: Yance presentation shell

**Files:**
- Create: `frontend/src/yance/YanceShellView.vue`
- Create: `frontend/src/yance/components/*`
- Create: `frontend/src/yance/yance.css`
- Create: `frontend/src/__tests__/yance/YanceShellView.spec.ts`
- Modify: `frontend/src/router/index.ts`

**Interfaces:** New Yance presentation route and shell; uses no second backend authority and exposes no fake status/data.

- [ ] Write failing shell contract test for frozen header/composer order and default collapsed/off states.
- [ ] Verify RED.
- [ ] Implement minimal shell layout and route.
- [ ] Run focused test GREEN, full frontend unit suite, type-check and build.
- [ ] Commit shell.

### Task 5: First-round verification receipt

**Files:** `docs/yance/FIRST_ROUND_CLEAN_REBASE_RECEIPT.md`

- [ ] Re-run registry hashes, git provenance and clean-state checks.
- [ ] Record every test/build command and exact result.
- [ ] Record commit hashes and unresolved blockers without upgrading them to GREEN.
- [ ] Return only `PASS_CLEAN_REBASE_FOUNDATION`, `HOLD_CLEAN_REBASE_BLOCKER`, or `RED_UPSTREAM_REBASE_FAILURE`, followed by `READY_FOR_MASTER_CONTROLLER_REVIEW`.
