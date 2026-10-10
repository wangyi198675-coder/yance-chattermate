# Yance Phase 3 Native-First Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Qualify and wire the low-risk Wave A + Wave B owners without creating any new Yance subsystem or duplicate authority.

**Architecture:** ChatterMate remains the owner of people, messages, conversations, channels, agents, workflow, models, attachments and send. External owners are admitted only behind narrow adapters after version/license/Windows/install/API checks. Yance code is limited to Frozen-UI presentation glue, product-semantic routing metadata and thin external-owner adapters.

**Tech Stack:** ChatterMate v1.0.25, Python 3.12, SQLAlchemy 2.1.x, Vue 3, SQLAlchemy-Continuum 1.8.0, Lingua 2.2.0, Argos Translate 1.11.0 candidate, ImageMagick 7.1.2-32, FFmpeg 9.0.2 branch build candidate.

**Spec:** Master Controller Phase 3 execution instruction supplied 2026-10-05; Phase 2 owner matrices under `docs/yance/`.

## Global Constraints

- `YANCE_REBUILD_DOCTRINE = NO_CUSTOM_BY_DEFAULT`.
- No external owner may be wired before `PASS_OWNER_PRODUCTION_ADMISSION`.
- No custom memory/graph/persona/translation/voice/media/workflow/queue/scheduler/social protocol subsystem.
- Frozen Primary + Secondary UI remains locked; no new engineering-designed buttons/pages.
- ChatterMate `Customer`, `ChatHistory`, `Agent`, `Workflow`, `AIConfig`, `FileAttachment`, `ChannelConversation` and `ChannelAdapter` remain canonical owners.
- One independently reviewable commit per integration wave; exact provenance and rollback recorded.

## Review Focus

- External dependency passes clean Windows install but adds hidden runtime/license surface.
- Persona history accidentally becomes current Persona authority rather than history-only.
- Translation failure must fail closed and never silently send untranslated/invalid output.
- Media adapters must execute independent binaries without importing/copyleft source into Apache core.
- Owner routing must remain declarative thin glue and never become a generic event bus/executor.

### Task 1: Production admission and native preservation authority
- [ ] Re-verify exact versions/provenance/license/Windows/security for Wave B candidates.
- [ ] Run isolated clean-install/import/start smoke checks.
- [ ] Create production admission, license boundary, native wiring and 44-capability preservation ledgers.
- [ ] Record HOLD owners without implementing them.
- [ ] Commit documentation-only authority.

### Task 2: Persona history narrow integration
- [ ] Write failing tests proving `Agent.instructions` stays current state and Continuum is history-only.
- [ ] Verify RED.
- [ ] Add exact Continuum dependency and minimal model versioning hook/migration.
- [ ] Verify GREEN with project SQLAlchemy version and rollback/history smoke.
- [ ] Commit independently.

### Task 3: Translation admission/integration
- [ ] Admission gate Argos 1.11.0 + Lingua 2.2.0 against Windows/runtime/license constraints.
- [ ] If either required owner is HOLD, write result and do not create a replacement engine.
- [ ] Only if PASS: write RED tests for detect/translate/preview/integrity/fail-closed/native-send boundary, then minimal adapter and GREEN.
- [ ] Commit independently if implementation is admitted.

### Task 4: Deterministic media boundary
- [ ] Qualify exact ImageMagick and FFmpeg Windows artifacts, including license/build boundary.
- [ ] Write RED tests for availability and fixed narrow commands only.
- [ ] Add minimal CLI adapters for resize/crop/convert and trim/transcode/mux only after PASS.
- [ ] Verify missing-binary fail-closed behavior and output artifact path handoff to ChatterMate FileAttachment.
- [ ] Commit independently.

### Task 5: Native-first semantic routing and Frozen UI wiring
- [ ] Write RED tests for declarative Girlfriend/Reply owner routes and unavailable-owner behavior.
- [ ] Add static owner-routing registry only; no generic executor or event bus.
- [ ] Wire existing YanceShell semantic emits to the registry/native owner facade without changing Frozen layout.
- [ ] Verify frontend focused tests/type-check/build and backend Yance tests.
- [ ] Produce final Phase 3 Wave A+B reports, exact changed files, hashes and no-custom gate.
- [ ] Commit independently and run exact-HEAD verification.
