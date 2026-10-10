# Translation Semantic Authority Rebuild Mapping

Source authority:

`C:\Users\1\Documents\YanceAuthority\20261005\MasterController\TRANSLATION_SEMANTIC_AUTHORITY.md`

`SOURCE_AUTHORITY_SHA256 = BDA33370C3E05A1BEEB2F0A3B632EDDB0FC0AFC6686D9F9544866BA34C5A1B1D`

## Locked status split

`TRANSLATION_SEMANTIC_AUTHORITY = PASS_LOCKED`

`TRANSLATION_MESSAGE_IDENTITY_CONTRACT = PASS_LOCKED`

`TRANSLATION_UI_PROJECTION_CONTRACT = PASS_LOCKED`

`TRANSLATION_FAIL_CLOSED_CONTRACT = PASS_LOCKED`

`TRANSLATION_FACT_EXTRACTION_CONTRACT = PASS_LOCKED`

`TRANSLATION_EXECUTION_OWNER = HOLD_NO_OWNER_SELECTED`

Execution-owner HOLD does not reopen or invalidate the already-proven product semantics.

## ChatterMate rebuild identity mapping

Legacy semantic provenance used exact Matrix event identity. The rebuild canonical mapping is:

`derived translation -> exact canonical ChatHistory.id`

Platform external message identity is provenance/dedupe assistance only and is never the sole canonical translation projection key.

## Truth hierarchy

- original text = primary truth
- Chinese translation = weak secondary projection
- failed/stale/invalid translation never enters Chinese last-message projection
- failed/stale/invalid translation never feeds fact extraction
- failed/stale/invalid translation never masquerades as success

Profile/place localization is projection only and must not mutate canonical facts.

## Fact extraction

Only successful, validated translation revisions may feed translation-aware fact extraction. Identity/revision must be deterministic so recovery is idempotent and exactly-once per successful translation revision.

## Execution boundary

Do not port the legacy Matrix/custom translation implementation. If future translation output validation fails, first use a mature execution provider's native glossary/constraint/retry/regenerate capability where qualified; if it still fails, FAIL CLOSED.

Still forbidden:

- Translation DB
- Translation cache authority
- Translation scheduler
- Translation provider registry
- URL/entity repair engine
- custom terminology engine
