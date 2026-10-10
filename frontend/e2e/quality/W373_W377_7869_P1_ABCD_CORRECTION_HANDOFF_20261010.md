# W373 source correction against W377 second-round 7869e721 HOLD — 2026-10-10
Role: WINDOW373_C3_NATIVE_FIRST_PROACTIVE_QA_RELEASE_GATE_EXCLUSIVE_TEST_SOURCE_OWNER. Reviewer: original W377 PERMANENT INDEPENDENT READONLY. W327 remains the only controller.
Start: branch work/window373-c3-quality-gate, HEAD 7869e72184f9711d08bb5a2cfb1c010fdee91adf, CLEAN. Formal C3 fa1b2571b40b8d8cee970491a72ad4df56a21d28 CLEAN, no changes. New exact descendant SHA must be resolved with `git rev-parse HEAD` after commit; this text is not an acceptance certificate.

## P1-A protected trace content
- Added `playwright-artifact-proof.mjs` as a small pure verifier, not a second QA engine. It reads, hashes and checks **actual** trace ZIP bytes in independently retrieved artifact directory; canonicalizes paths, refuses traversal/symlinks, matches signed SHA, real Playwright JSON `expected/passed` status, native project, unique ID, HEAD SHA, GitHub run/job/attempt/repository identity, attached real trace. Does not trust JSON claim of trace hash without opening the ZIP.
- `capture-ci-provenance.mjs` copies each native test trace to deterministic `test-results/yance-quality/traces/<ID>.zip`, records source/hashes/run/job ID, but labels self-captured file UNVERIFIED. Requires W327 independently resolved numeric GitHub job ID; no real run currently proved. `playwright.config.ts` records CI metadata for independent equality check.
- `verify-independent-trust.mjs` preserves earlier fail-closed W327 protected pointer digests/Ed25519 dual signatures/repo and exact source checks and now invokes the physical ZIP + Playwright result verifier after hash-verifying downloaded artifact JSON files. No W327/W377 signing material or review receipt was created.
- Adversarial test `playwright-artifact-selftest.mjs` physically mutates a temporary ZIP byte, removes an actual ZIP, contradicts JSON status, duplicates test IDs and results, mismatches CI run/job, and rejects unknown/missing paths. Synthetic tiny ZIP used ONLY in validator unit negative tests, not as E2E release evidence.

## P1-B no native PIN fixture pollution
`RUX-10` requires actual `SessionToAgent.is_pinned` recognized by PostgreSQL information_schema and exact organization/session row. Reads original, exercises both PIN and UNPIN via native UI, asserts PostgreSQL readback and browser reload each time, and `finally` restores original through native UI if necessary. No direct DB update. If real canonical pin column or UI action absent, fail BEFORE mutation; actual pin owner is currently **unqualified and remains RED / NOT_RUN**.

## P1-C real adopted Composer value / no fictitious send proof
`GF-INTENT-11` extracts selected native text draft from candidate card, clicks actual adoption and requires exactly matching Composer textarea value; not merely nonempty. `GF-INTENT-15` explicitly states structural one-Composer ONLY, SEND PERMISSION / REAL ACK / RESTART **NOT_RUN** via test title and annotation. No platform SEND or fake delivery receipt.

## P1-D authoritative identifiers and non-fabrication
`RUX-07`: exact `ChatHistory.id` + organization/customer/session from PostgreSQL, authenticated ChatDetail source and message type, matching UI event row ID, persisted event translation ID/status/text and original before Chinese. `RUX-08`: PostgreSQL Customer metadata vs authenticated detail and field-by-field UI equality. Missing/unknown nationality, city, age, occupation must be absent or explicitly `unknown`, never invented. `RUX-11`: two distinct PG Customer+Session+ChatHistory rows, two differently selected UI row IDs and header IDs, API detail and browser reload; no fixture self-comparison. Existing app lacks some identity hooks — tests remain RED, W327 must assign source owner; no production Vue modified.
`native-provenance-selftest.mjs` fault-injects removal of 6 distinct P1 B/C/D test-source assertions, validates that each is rejected, records SOURCE-ONLY not native E2E.

## Non-negotiable HOLD and true coverage
- Four frozen content hashes preserved. 344 obligations, 15 declared Playwright tests, 329 MISSING_TEST, ZERO accepted true native executions, frozen 252+20 formal NOT_RUN; no product PASS.
- Existing 13 Vitest RED remain owned by W327 triage. No test/assertion removed. Real auth PG source, private Windows runner, protected GitHub repo/run/job/branch checks, golden RC3, provider account sends, permission/ACK/restart proof not in W373 authorization and all HOLD.
- No new npm dependencies, business source, migrations, service credentials, master pointer, official C3, production data, or deployment modifications. Reviewer W377 only may independently examine new exact SHA; W327 alone may later admit it.
