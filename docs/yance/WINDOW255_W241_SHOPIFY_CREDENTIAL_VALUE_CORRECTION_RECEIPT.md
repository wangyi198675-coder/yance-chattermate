# Window255 — Window241 / Window237 Shopify Credential-Value Correction

Role: `WINDOW255_W241_W237_SHOPIFY_CREDENTIAL_VALUE_CORRECTION_WORKER`

## Custody and authorization

- Dispatch: `MasterController/WINDOW255_W241_W237_SHOPIFY_CREDENTIAL_VALUE_CORRECTION_DISPATCH.md` (fresh-read).
- Reviewer source-defect receipt: `MasterController/WINDOW241_W237_IDENTITY_METADATA_CREDENTIAL_VALUE_INDEPENDENT_REVIEW_RECEIPT.md` (fresh-read).
- Original Window237 candidate / exact Window255 parent: `a273631155e25dd74dceac1bd485fa4156be03b8`.
- Earlier Window237 parent lineage: `da656616b43e750a9a058c3cb6abe48b379c38a9`.
- Isolated worktree: `C:\Users\1\YanceWorktrees\yance-chattermate-window255`.
- Branch: `fix/window255-w241-shopify-credential-values-20261008`.
- Bounded correction only. No merge, deployment, canonical promotion, live provider token, secret store, second scanner or provider registry.

## Source correction

- Modified **only** existing `IdentityProviderProfileRef.non_secret_identifier` support policy in `backend/app/schemas/file_attachment_identity.py`: authentication prefix family `shp(?:at|ss|pa|ua)_` now rejects Shopify `shpat_`, `shpss_`, `shppa_` and `shpua_`, case-insensitively and independently of suffix value.
- All pre-existing Slack, OpenAI, GitHub, GitLab, AWS, Google, Stripe, webhook, marker, URL, JWT and bounded-format negatives remain in place.
- No change to `FileAttachmentRepository`, `FileAttachmentIdentityMetadataUpdate` fields, JSON schema, API, DB, consent/provenance/approval, org isolation, revoke or delete.
- Repository continues to invoke shared schema validation *before* assignment to `FileAttachment.identity_metadata` and before commit. Rejected profile references leave already approved metadata semantically identical.

## Fresh source-matching verification

- Private source-compatible Python 3.12.15 environment: `C:\Users\1\AppData\Local\Temp\yance-window245-c3-backend\Scripts\python.exe`; Pydantic 2.13.5, pytest 9.1.1, SQLAlchemy 2.1.4. Not global Python.
- Fresh complete focused `backend/tests/repo/test_file_attachment_identity_metadata.py`: **112 passed, 138 warnings** (exit 0), up from Window241's prior 82; warnings are upstream deprecations and other unmodified modules.
- New repository regression matrix: four Shopify credential namespaces × three non-secret-marker suffixes × approved/empty prior state = **24** tests; schema rejects, repository commit is prohibited, row remains unmodified, and existing metadata is equal after reload. The existing schema/repository parametrized negative suites also include the three formerly missing namespaces.
- Independent adversarial verifier executes this candidate's actual schema, ORM and repository via SQLAlchemy, checks same-API source wiring, prior credential families, five legitimate ElevenLabs/HeyGen/LiveAvatar reference shapes, nested/top-level extra-key rejection, org isolation, revoke/delete, and **48** mixed-case Shopify matrix variants: **88 passed** (exit 0).
- `py_compile`: PASS. Pre-commit `git diff --check`: PASS.
- Raw logs, independent verifier, SHA manifest and machine-readable evidence: `MasterController/WINDOW255_VERIFICATION_EVIDENCE` and related Window255 authority receipts, outside Git source.

## Bounded verdict

`PASS_WINDOW255_W241_SHOPIFY_CREDENTIAL_VALUE_CORRECTION_READY_FOR_INDEPENDENT_REVIEW`

Worker readiness only; **Window258 independent READ-ONLY review is mandatory**. No controlled integration or admission authorized by this worker receipt.
