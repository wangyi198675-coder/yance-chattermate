# TRANSLATION_INTEGRITY_RESULT

## Phase 3C result

`INTEGRITY_EXECUTION = NOT_RUN_BLOCKED_BY_PROVIDER_CREDENTIAL`

`FAIL_CLOSED_POLICY = REQUIRED`

No output repair is permitted.

## Mandatory invariants for the next credentialed qualification

Each de/zh/en translation direction must prove:

- exact URL retention
- exact `@mention` retention
- number retention
- currency amount and denomination retention
- date retention
- time retention
- proper-name retention
- emoji retention
- line and paragraph structure retention
- semantic polarity retention
- negation retention
- conversational tail retention
- no added facts/content
- no truncation/empty output
- source/target language correctness

An invariant failure rejects the translation result. The product may validate and fail closed; it may not rewrite the model output to make a failing translation appear valid.

Same-language requests remain a no-op: do not invoke a translation model and do not create translation state.
