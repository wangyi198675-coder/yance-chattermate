# Window220 — W202 Identity Metadata Bounded-Schema Correction

Role: `WINDOW220_W202_IDENTITY_METADATA_BOUNDED_SCHEMA_CORRECTION_WORKER`

- Base: Window192 `3398fca7e2d9c4b27b9a4511dd1a4cd25ec34677`
- Review blocker: `HOLD_WINDOW202_W192_IDENTITY_METADATA_REPOSITORY_BYPASSES_BOUNDED_SCHEMA_AND_CAN_PERSIST_PROVIDER_CREDENTIALS`
- Owned isolated worktree: `D:\YanceRebuild\20261005\yance-chattermate-window220-w202-bounded-schema`
- Branch: `fix/window220-w202-bounded-metadata-20261008`
- Main production branch and canonical HEAD were NOT changed.

## Scope of correction

1. Moved existing API identity models into the single shared schema at `backend/app/schemas/file_attachment_identity.py`, imported from both API and repository.
2. `extra="forbid"` rejects unknown fields and credential keys recursively, including nested provenance, consent, eligibility, quality, and provider profile reference.
3. `provider_profile_ref` admits only `provider` + bounded non-secret `profile_id` with rejection of credential-shaped references, URLs, and JWT-like ids.
4. Repository `update_identity_metadata` validates **before** assigning the JSON field; only bounded model dumps can be committed.
5. Repository revoke validates stored metadata **before** persisting the bounded terminal revoke receipt, and refuses to copy existing malformed/unbounded data.
6. Existing same-table FileAttachment JSON, organization scope, explicit consent/approval, provenance, eligibility, terminal revoke and delete remain. No new DB, table, asset manager, scheduler, or provider registry.

## Tests and evidence (2026-10-08)

- **PASS**: isolated verifier using actual production repository code and SQLite same-table test model, `C:\Users\1\AppData\Local\Temp\window220_verify.py`:
  - 10 forbidden top-level / credential keys rejected with no persisted change
  - 6 nested credentials rejected
  - 5 secret-shaped provider IDs rejected
  - valid bounded metadata persisted and validated
  - organization isolation
  - revoke, re-update rejection, re-revoke rejection, and delete
  - API GET/PUT/revoke/delete handler source extracted from actual `file_upload.py`: PASS
- **PASS**: `git diff --check`; Python bytecode compile check.
- **Added**: full repository regression tests in `backend/tests/repo/test_file_attachment_identity_metadata.py`: direct repository unknown key, each credential, nested fields, provider profile refs, consent/approval, valid storage, org isolation, terminal revoke and delete.
- **BLOCKED**: full `pytest -q tests/repo/test_file_attachment_identity_metadata.py` cannot collect in this workstation's `backend/.venv-yance`: `app.__init__ -> app.main` fails with `ModuleNotFoundError: No module named 'socketio'`. The isolated handler verifier is **not** a substitute for full FastAPI transport / middleware integration.
- **MISSING SOURCE**: requested dispatch `C:\YanceController\MasterController\WINDOW220_W202_IDENTITY_METADATA_BOUNDED_SCHEMA_CORRECTION_DISPATCH.md` is absent because `C:\YanceController` does not exist on the connected host; scoped work followed the user's provided dispatch verbatim.

## Verdict

`HOLD_WINDOW220_FULL_PYTEST_DEPENDENCY_AND_DISPATCH_EVIDENCE_GAP`

The bounded persistence correction is implemented with isolated checks passing. Independent review should verify this patch after the complete application test environment and canonical dispatch are available. Do **not** admit it to the main production branch on isolated verification alone.
