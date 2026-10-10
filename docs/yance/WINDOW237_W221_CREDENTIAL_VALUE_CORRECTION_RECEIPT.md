# Window237 — Window221 Provider Profile Ref Credential-Value Correction

Role: `WINDOW237_W221_W220_IDENTITY_METADATA_CREDENTIAL_VALUE_CORRECTION_WORKER`

## Source authority and boundaries

- Dispatch: `C:\Users\1\Documents\YanceAuthority\20261005\MasterController\WINDOW237_W221_PROVIDER_PROFILE_REF_CREDENTIAL_VALUE_CORRECTION_DISPATCH.md` (fresh-read)
- Original Window220 lineage/base candidate: `da656616b43e750a9a058c3cb6abe48b379c38a9`
- Isolated worker worktree: `C:\Users\1\YanceWorktrees\yance-chattermate-window237`
- Worker branch: `fix/window237-w221-credential-value-20261008`
- Canonical C3 was read-only: `c094cd8c0a5f091e30f3880436173ae9bb479a14`
- No merge, deploy, canonical promotion, provider credential access, additional DB/table/service or provider registry.

## Bounded correction

- Existing single shared schema: `backend/app/schemas/file_attachment_identity.py`.
- The pre-existing validator already rejects unknown/nested credential-named keys, URLs, JWT-like triplets, marker strings and unbounded IDs. These checks were preserved.
- Added a bounded `profile_id` **value** prefix check for synthetic Slack (`xox*`), OpenAI/Stripe secret (`sk-*`, `sk_*`, `rk_live_*`), GitHub (`gh*_*`, `github_pat_*`), GitLab (`glpat-*`), AWS (`AKIA*`, `ASIA*`), Google (`AIza*`, `ya29.*`), and webhook/Shopify secret-prefix shapes.
- Added `api-key`, `apikey`, `access-key`, `accesskey`, `private_key`, `private-key` value markers; previously existing token/secret/password/credential/api_key/access_key/bearer markers and JWT/shape validation stay in force.
- Repository `update_identity_metadata` already validates through this same shared schema before JSON field assignment or commit; no repository production-code change was needed. It still persists the exact bounded `FileAttachment.identity_metadata` JSON.

## Fresh consumer inspection

- Actual current backend consumer: `app/services/voice_runtime.py` and `app/api/voice.py` use ElevenLabs `voice_id`; provider key is obtained from `settings.ELEVENLABS_API_KEY`, not `identity_metadata`.
- A repo-wide backend/frontend source grep found no HeyGen or LiveAvatar runtime consumer in this **Window220-derived** candidate (only test references to HeyGen). Therefore no live provider-ID truth or runtime-compatibility PASS is claimed for those two; representative opaque UUID/prefixed IDs are covered in positive shape tests.
- Positive tests preserve Twenty-character ElevenLabs-like opaque IDs, HeyGen UUID/hyphenated refs, and LiveAvatar UUID/prefixed refs. The validator is provider-independent and is not a provider ID registry.

## Focused evidence

- Source-matching private Python: `D:\YanceRebuild\20261005\yance-chattermate\backend\.venv-yance\Scripts\python.exe` (Python 3.12.15, Pydantic 2.13.5, SQLAlchemy 2.1.3).
- Isolated, source-executing verifier: `C:\Users\1\AppData\Local\Temp\window237_verify.py`. Imports **actual** schema and repository source from Window237, runs on SQLite test table matching the canonical `FileAttachment.identity_metadata` column, plus source-extracted API handlers. This is narrower than the complete real-model/HTTP pytest suite.
- Output: existing 10 top-level, 6 nested and 5 original malformed profile-ID rejections PASS; org isolation, exact bounded JSON, terminal revoke/delete and source-handler checks PASS.
- Window237: **22** value-level credential shapes fail at both direct schema and repository boundaries with **NO WRITE**; **5** legitimate provider-reference forms roundtrip unchanged as exact bounded JSON; failed update does not replace existing metadata. All PASS.
- Python compile and `git diff --check`: PASS.
- Full shared `pytest -q tests/repo/test_file_attachment_identity_metadata.py`: blocked at `tests/conftest.py -> app.__init__ -> app.main` by `ModuleNotFoundError: No module named 'socketio'`. This is `HOLD_FULL_SHARED_PYTEST_ENVIRONMENT_EVIDENCE_GAP`, **not** a new source regression, and is **not** a full pytest PASS.
- All test credentials are explicitly synthetic; no real tokens/keys stored.

## Verdict and handoff

`PASS_WINDOW237_W221_CREDENTIAL_VALUE_CORRECTION_READY_FOR_INDEPENDENT_REVIEW`

Bounded source repair is candidate-ready; **independent review remains mandatory** before any integration/admission. The unrelated full-shared-pytest bootstrap gap remains separately recorded as `ENVIRONMENT_EVIDENCE_GAP`. This does not establish production source/UAT GREEN. Existing metadata free-form fields outside `provider_profile_ref.profile_id` are not redefined by this narrowly authorized correction; opaque secret strings without recognizable credential markers cannot be classified with certainty by a bounded syntactic validator. No second secret-scanning service was added.
