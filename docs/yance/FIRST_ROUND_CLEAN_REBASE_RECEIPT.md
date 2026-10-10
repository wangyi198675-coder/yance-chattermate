# FIRST_ROUND_CLEAN_REBASE_RECEIPT

Date: 2026-10-05

## Verdict scope

This receipt covers only the **NEW YANCE SOURCE FOUNDATION** first-round gate. It does not claim Production GREEN, Windows runtime GREEN, personal-social platform GREEN, final HF pixel parity, or final 152 runtime closure.

## 1. CHATTERMATE_UPSTREAM_BASELINE_RECEIPT

- Repository: `https://github.com/chattermate/chattermate.chat.git`
- Default branch at intake: `main`
- Default branch HEAD at intake: `82df312654abfbd146f1b1f3fdc027b143e6a8c0`
- Latest release / latest suitable stable: `v1.0.25`
- Release commit: `eea5d62883c7b2130f3466c9c2aad5b1b2bf904e`
- Annotated tag object: `4b2108b0fd886d5a9031ddf0c1f3926d3d7d3ad8`
- Release date: `2026-09-23`
- License boundary: Apache-2.0 open-source core; optional enterprise modules are not treated as Apache-2.0 core authority.
- `frontend/package-lock.json` SHA-256: `7823efdcd911ff2e4e6b6453797133a3139d9f5768881176778c4ec59059f493`
- `backend/requirements.txt` SHA-256: `b40b4f8afb02d694f0372e3f6145e22760288ff5a66c374dcc707c83e3242e02`
- Both dependency files are unchanged from the selected v1.0.25 baseline.

## 2. NEW_YANCE_GIT_AUTHORITY

- Source root: `D:\YanceRebuild\20261005\yance-chattermate`
- Branch: `yance/clean-rebase-20261005`
- Upstream merge-base: `eea5d62883c7b2130f3466c9c2aad5b1b2bf904e`
- Upstream remote retained as `upstream`.
- Old `C:\YanceController\current-app` was not used as a source base and was not modified by this workstream.
- Frozen authority packages remain external to source history.

## 3. UPSTREAM_KEEP_HIDE_DELETE_MATRIX

Delivered in `docs/yance/UPSTREAM_KEEP_HIDE_DELETE_MATRIX.md`.

Foundation rule: keep mature backend owners, de-present support/SaaS-specific UI, delete no mature backend capability without later dependency proof.

## 4. YANCE_UI_REBASE_SHELL

Delivered:
- `frontend/src/yance/YanceShellView.vue`
- `frontend/src/yance/yance.css`
- `/yance` route in upstream router
- Home / Conversation / Relationship World / Settings shell states
- Conversation frozen structural contract: contact rail, timeline, Reply Brain collapsed by default, Girlfriend Brain off by default, required header order, required composer controls.
- Non-local visible controls emit semantic integration events rather than being dead buttons.
- No internal authority/spec annotations are rendered as product copy.

Important limitation: this is a **structural source foundation**, not a claim of final HF-01..HF-06 pixel parity or 100/100 secondary runtime wiring. Those remain later admission gates against frozen renders and interaction inventory.

## 5. CANONICAL_PERSON_IDENTITY_EXTENSION

Delivered:
- `backend/app/models/person_identity.py`
- `backend/app/repositories/person_identity.py`
- `backend/alembic/versions/yance_person_identity_001.py`

`Customer` remains canonical Person authority. The extension adds organization-scoped/channel-account-scoped identity mapping, provenance, active/stale lifecycle, redirect-to-surviving-identity, fail-closed redirect loop/scope checks, and reuses upstream `PeopleRepository.get_customer()` for canonical Customer merge resolution. `ChannelConversation.customer_id` remains the conversation-to-Person linkage.

Static migration graph verification: 99 revisions, unique head `yance_person_identity_001`, no missing down-revision references, no unresolved revision metadata.

## 6. YANCE_EXCLUSIVE_CAPABILITY_INTEGRATION_PLAN

Delivered in `docs/yance/YANCE_EXCLUSIVE_CAPABILITY_INTEGRATION_PLAN.md`.
Selection rule: `ChatterMate latest native ? mature OSS owner ? thin Yance adapter ? custom last`.

## 7. NEW_YANCE_152_CAPABILITY_DELTA

Delivered:
- `docs/yance/NEW_YANCE_152_CAPABILITY_DELTA.csv` ? exactly 152 Frozen capability IDs.
- `docs/yance/NEW_YANCE_EXTRA_UPSTREAM_CAPABILITIES.csv` ? 12 additional mature ChatterMate capabilities retained for evaluation/reuse.

Initial conservative classification:
- `UPSTREAM_NATIVE`: 14
- `THIN_YANCE_ADDITION`: 11
- `MISSING`: 127
- Runtime GREEN: intentionally `NO` for all 152 until wiring/evidence exists.

The 152 + 12 inventory gives a 164-entry source capability scope, but **164 is not claimed as runtime-GREEN capability count**.

## 8. PERSONAL_SOCIAL_TRANSPORT_ADAPTER_CONTRACT

Delivered:
- `docs/yance/PERSONAL_SOCIAL_TRANSPORT_ADAPTER_CONTRACT.md`
- `backend/app/channels/personal_social/base.py`

Contract includes connect/disconnect/reconnect/session status/inbound/outbound/receipt/media/backfill/account identity/route/error/health. It intentionally exposes no Person/Relationship/Persona/Memory/Brain persistence owner.

No Personal WhatsApp / Telegram User / Personal Messenger / Personal Instagram implementation is marked GREEN.

## 9. WINDOWS_RUNTIME_REQUIREMENTS_HANDOFF

Delivered in `docs/yance/WINDOWS_RUNTIME_REQUIREMENTS_HANDOFF.md`.
This source branch does not design or modify Memurai/PostgreSQL Windows packaging, service supervision, installer, `Yance.exe`, crash restart, credential migration, or production deployment.

## 10. Tests and commits

Commits:
- `5c6999ed9f8806ae77ac88c1354ad93506be9c32` ? source authority/spec/plan/ledgers
- `bc4f8e77774d4ba52b1dbc157d1ab70156ccdef2` ? canonical Customer PersonIdentity thin extension
- `3a055de7644132fa2eb3b55c4b17dcdf9aae8857` ? personal-social transport boundary
- `a5628ce561c553c5ee51942930d5258fa2609cbd` ? initial Yance shell
- `793c82628b85ba4f56ba8b98bcce6c17dcc1f9ec` ? interaction-event closure and router source-drift correction

Fresh evidence before this receipt:
- Backend Yance focused suite: `5 passed`.
- PersonIdentity TDD RED: missing target model/repository modules; GREEN: 3/3.
- Personal-social TDD RED: missing target adapter package; GREEN: 2/2.
- Yance shell TDD RED: missing target Vue component; GREEN: 2/2.
- Dead-control review finding TDD RED: semantic events absent; GREEN: Yance shell 3/3.
- Frontend TypeScript type-check: PASS.
- Vite production build + PWA service worker build: PASS.
- Primary registry SHA-256 exact match: `5be68b72e1afc027590cdef271e2cf10cd09140aaff6fee5aca9c1b9c1a50213`.
- Secondary registry SHA-256 exact match: `fb64957cb15ec0ceefc9b35e3b2af9b86de8cb8faf91017c0a3535133fac58d6`.
- Python compile for added model/repository/transport/migration: PASS.

### Non-GREEN evidence retained

1. Full upstream frontend unit run produced `69 files / 552 assertions passed`, but Vitest returned nonzero because one asynchronous teardown error from unchanged upstream `src/webclient/WidgetBuilder.vue` fired after environment teardown (`document is not defined`). The affected source and test have zero diff against v1.0.25. Focused `widgetComposer.spec.ts` runs 5/5 assertions PASS but still emits upstream jsdom `Node is not defined` stderr. **The full upstream unit suite is not claimed GREEN.**
2. `alembic heads` cannot be used in the intentionally minimal isolated development venv because historical upstream migration `hc_article_image_paths.py` imports application runtime code and reaches missing `python-socketio`. Independent non-executing graph validation reports 99 revisions, exactly one head (`yance_person_identity_001`), zero missing refs, zero unresolved refs. Runtime integration must install upstream runtime requirements before dynamic Alembic upgrade/downgrade is accepted.
3. Build warnings for absent build-time Firebase push key and existing large chunks remain upstream/runtime concerns; no Production claim is made.

## Global Doctrine Override Admission

The 2026-10-05 `NO_CUSTOM_BY_DEFAULT` override has been applied to this foundation after implementation and before Master Controller handoff. Current code was re-audited:

- PersonIdentity remains a thin extension around canonical upstream Customer authority.
- Personal-social code remains an interface/contract only, with no platform owner or duplicate state.
- Yance shell remains UI glue.
- All future non-UI Yance-exclusive subsystem implementation is paused pending mature-owner search/reuse evidence.

See `docs/yance/GLOBAL_ENGINEERING_DOCTRINE_NO_CUSTOM_BY_DEFAULT.md` and `docs/yance/CURRENT_FOUNDATION_DOCTRINE_AUDIT.md`.

## Self-review / rulings

No fresh subagent reviewer is available in this harness, so final branch review is a self-review by the author and is weaker than an independent reviewer. Master Controller review remains mandatory before integration.

- Ruling: focused backend tests live in `backend/yance_tests` instead of `backend/tests/yance` to avoid importing unrelated full application/runtime dependencies in the isolated source-foundation TDD loop. Cost if wrong: later full backend CI can expose integration issues not exercised here.
- Ruling: the unchanged upstream WidgetBuilder teardown error does not block this **source-foundation** verdict, but remains non-GREEN evidence. Cost if wrong: suite scheduling could conceal an interaction regression; Master Controller/global regression must retain this issue until full-runtime CI closes it.
- Ruling: static migration graph verification is accepted for this source-foundation gate because dynamic Alembic import is blocked by intentionally absent upstream runtime dependencies, not by the Yance migration. Cost if wrong: a migration body runtime failure can still appear once full backend dependencies/PostgreSQL are present; runtime integration must execute real upgrade/downgrade validation.
- Ruling: the Yance shell is admitted only as structural/frozen-contract foundation; it is **not** final HF pixel parity and is **not** 100/100 interaction runtime closure. Cost if wrong: treating this receipt as final UI acceptance would bypass frozen visual/interaction admission gates.

## First-round source verdict

`PASS_CLEAN_REBASE_FOUNDATION`

`READY_FOR_MASTER_CONTROLLER_REVIEW`
