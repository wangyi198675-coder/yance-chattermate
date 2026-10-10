# W373 after W377 independent HOLD — QA-source candidate receipt

2026-10-10 Asia/Phnom_Penh. Role: original W373 test/CI exclusive source owner. Reviewer: W377 **permanent independent READONLY**, not W359. W327 single release controller.

- Fresh pointer rechecked (09:08:22+07); W327 sole active master.
- Original rejected QA candidate: b2c173fe6962d91d896120127f317e3d47275774, original C3 FA1B remains its ancestor.
- W373 branch: work/window373-c3-quality-gate, clean immediately before this scope's edits.
- Official C3 integration branch: integrate/post-c2-controlled-source-20261007, HEAD fa1b2571b40b8d8cee970491a72ad4df56a21d28, CLEAN.
- W377 original attached report SHA256: b5a4c40c1f8bd5e264eaf4ed0254d2380dec9331e58ad54c6c0fce6d917aad80. Directly verified from this chat uploaded material.
- No product source, migrations, secrets, package deps, master pointer, official integration source, production accounts/data or deployments changed.
- New Git candidate exact SHA: run `git rev-parse HEAD` on this branch after commit. W377 must review the exact new SHA and its parent; no source admission claimed.

## P0 — trusted approval
Removed legacy W359 string check and any locally self-granted release-eligible status. `verify-coverage.mjs --mode=release` always exits 1; user-authored `--evidence`, `--review`, forged 'W377', rehashed JSON cannot turn release green.
`verify-independent-trust.mjs` demands W327 master-pointer digest-anchored protected trust root and receipt, independent W377+W327 Ed25519 signatures, exact HEAD/parent/role/decision, authentic protected GitHub run/job/repo/Windows label identity, source-bound Playwright JSON, trace hash per accepted ID, private PostgreSQL customer/auth organization/session/chat history, post-restart owner readback. W373 did not create authority files or signing keys; none currently exist. Local trust verifier EXIT1 `W327_POINTER_HAS_NO_PROTECTED_TRUST_DIGESTS` as required. W327 must independently create/manage these off-branch and verify GitHub API/branch rules; source code alone cannot protect against malicious source author editing its own test logic.

## P1 contract and native
Pinned four contract SHA256 checks including release additions, per-family 152/100/20/23/11/15/11/12, stable GF capability content-hash IDs, strict CSV and unique IDs. Exactly 344 tracked, 15 declared, 329 MISSING_TEST, 0 native real-pass, original final 252 + 20 NOT_RUN.
Native precondition requires loopback true psql read-only query verifying isolated QA-named DB, PostgreSQL startup, cross-owner org/customer/user/session/chat_history join, authenticated ChatDetail read. Health200 + env vars alone fail: deliberately pointed test at 4181 with self-reported fixture and fake UUIDs, got `NATIVE_PG_CLIENT_AND_PRIVATE_SERVICE_REQUIRED`, plus native failure screenshot/video/trace. No actual native positive cases claimed. Browser source assertions now cover actual native state/clipboard/PG readback, Berlin DST and weather provenance, profiles, 0/3/5 candidates, GF owner receipt, one Composer, six route-specific roots; absent product features remain RED.

## Negative validation actually executed
`node e2e/quality/gate-selftest.mjs` -> EXIT0; **24 expected outcomes**, including positive catalog preflight; drop row; stale SHA; same-count content replace; duplicate/unknown ID; GF reorder; malformed row; unknown test; forged reviewer/receipt; self-hash; fictitious passed IDs; missing trace/CI; replay; real same-count CSV mutation; additions mutation; actual malformed CSV; author-supplied approval; no protected CI; removed Windows label/current branch. Every attack scenario returned exit1 with its intended blocker. `node e2e/quality/ci-workflow-contract.mjs` positive PASS *source only*, not proof remote CI active.
`npx playwright test --project=chromium-native --list`: 15 tests found. E2E isolated positive **NOT_RUN** (no approved native PG fixture). Native environment spoof negative produces artifacts under `frontend/test-results/w377-fake-http200-negative/`.
`node node_modules/typescript/bin/tsc -p e2e/tsconfig.json --noEmit`: EXIT0. `npm run type-check`: EXIT0.

## Existing Vitest RED retained
Full `npm run test:unit -- --run --reporter=dot`: **806 PASS / 13 FAIL** across 819, 113 passing and 8 failing files (121 total), plus one post-teardown async exception from WidgetBuilder in this run. Details in `vitest-13-red-owner-triage.json`; no old assertion deleted or product code touched. High-priority owner assignments remain W327-only (Meta Page 4, API login2, Settings2, one each right-click/shell/Persona/Reply-GF/LINE).

## CI and product HOLD
CI trigger/Windows runner/PG variables/required runner trace + runner manifest source added to .github/workflows/test.yml. W373 cannot prove W327 protected GitHub repo, branch-protection, real runner registration, GitHub actions conclusion or secure bootstrap. The source repository only exposes public upstream. 13 Vitest RED + missing native app/DB real fixture + absent W327 trust root keep CI/product release HOLD, even if a source-only workflow guard passes.
NO_CUSTOM_BY_DEFAULT: reused Playwright 1.63.0, Vitest 3.2.7, psql read-only PostgreSQL diagnostic, current GitHub Actions; zero new test dependency or product QA runtime.

**Next: W377 READONLY independent security/source review of new CLEAN SHA; then W327 sole integration authority. No user acceptance, global product PASS, production release or independent CI success asserted.**
