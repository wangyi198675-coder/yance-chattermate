# PHASE3_WAVE_AB_TEST_RESULTS

Fresh verification target before this docs-only evidence update: `98bd683abe9b89fbaea00cce6f3d5a3b132ce820`.

## Backend focused regression

All five Yance contract files were run in **separate pytest processes** with `DATABASE_URL=sqlite:///:memory:` where DB import is needed, preventing package-stub cross-test contamination.

- `test_person_identity.py`: **3/3 PASS** (one inherited SQLAlchemy `declarative_base` deprecation warning)
- `test_personal_social_contract.py`: **2/2 PASS**
- `test_persona_history.py`: **2/2 PASS**
- `test_deterministic_media_adapter.py`: **4/4 PASS**
- `test_yance_owner_contract.py`: **3/3 PASS**
- total focused backend assertions: **14/14 PASS**
- `py_compile` for new production Python/migration modules: **PASS**

## Migration graph

- revisions parsed: **100**
- unique head: `yance_persona_history_002`
- missing down-revision references: **0**

## Frontend / Frozen UI

- `YanceShellView.spec.ts`: **4/4 PASS**
- `npm run type-check`: **PASS**
- `npm run build-only`: **PASS**
- build retains only existing warnings (chunk-size / optional Firebase build-time configuration); no Phase-3 compile error.

## Owner functional qualification

- SQLAlchemy-Continuum 1.8.0 clean import + history/revert smoke: **PASS**
- Lingua 2.2.0 Windows cp312 detector smoke: **PASS**
- ImageMagick 7.1.2-32 portable version/resize/crop: **PASS**
- FFmpeg n9.0.2-22 LGPL Windows build version/scale/transcode/trim: **PASS**
- Argos Translate 1.11.0: **HOLD before wiring** due transitive license/runtime-surface admission failure.

## No-custom / diff hygiene

- production source files changed since Phase 2: **8** (plus migrations/requirements/tests/UI tests)
- prohibited production subsystem scan: **0 hits**
- `git diff ... --check`: **PASS**
- worktree at evidence capture: **CLEAN**

This test set is the Phase-3 Wave-A+B scoped admission/regression gate. It does not claim the entire upstream test suite is clean; the previously attributed upstream `WidgetBuilder.vue` jsdom teardown hygiene issue is outside this source diff.

## Phase 3B translation/Graphiti qualification

- Translation native source trace: `workflow.default_language` runtime consumption = **NO**.
- CTranslate2 4.8.2 Windows clean install/import = **PASS**.
- OPUS-MT en->zh conversion/inference = **PASS runtime / FAIL mandatory integrity**.
- Translation owner admission = **HOLD** (`NO_OWNER_SELECTED`).
- Graphiti 0.30.2 clean install = **PASS**; bare import = **FAIL** (`ModuleNotFoundError: httpx` after package installs `httpx2`).
- Graphiti wiring = **NOT PERFORMED**.
- No custom translator / Graphiti patch = **PASS**.

A fresh exact-HEAD source/test/build gate is required after the Phase 3B evidence commit and will be appended only from observed results.

## Phase 3B fresh exact-head gate

Gate head: `cd690d596f1b9bb60a3ec624db3e737d7e48ff1d`

- Backend Yance focused tests: **14/14 PASS** across five isolated pytest processes.
  - PersonIdentity: 3/3 PASS (SQLite isolated test path; one upstream SQLAlchemy deprecation warning).
  - Personal Social contract: 2/2 PASS.
  - Persona history: 2/2 PASS.
  - deterministic media boundary: 4/4 PASS.
  - mature owner contract: 3/3 PASS.
- Python compile for touched Yance source: **PASS**.
- Migration graph: **100 revisions / unique head `yance_persona_history_002` / 0 missing refs**.
- Frozen Yance UI focused tests: **4/4 PASS**.
- TypeScript `vue-tsc`: **PASS**.
- Production Vite/PWA build: **PASS**. Existing warnings: unset build-time Firebase key and upstream chunk/dynamic-import warnings; no build failure.
- `git diff --check`: **PASS**.
- Phase 3B production-source diff since `72ff3d9`: only `backend/app/core/yance_owner_contract.py`; the paired owner-contract test changed separately.
- No custom translation/provider/DB/tokenizer/sentence-splitter/NMT implementation was introduced.
- Worktree before evidence update: **CLEAN**.

Translation owner remains HOLD because mandatory integrity failed; passing regression does not promote it to Runtime GREEN.
