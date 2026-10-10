# CHATTERMATE_MODEL_PROVIDER_TRANSLATION_AUDIT

## Phase 3C verdict

`CHATTERMATE_EXISTING_MODEL_EXECUTION_AS_TRANSLATION_OWNER = QUALIFICATION_BLOCKED_BY_PROVIDER_CREDENTIAL`

`TRANSLATION_EXECUTION_OWNER = NO_OWNER_SELECTED`

`CUSTOM_SUBSYSTEM_EXCEPTION_APPROVED = 0`

This audit does not re-open Argos Translate or OPUS-MT. It audits only ChatterMate's existing AIConfig/model-provider execution boundary.

## Existing provider contract in v1.0.25

The production source already has one model/provider authority:

- `backend/app/models/ai_config.py` — `AIConfig`, `AIModelType`, encrypted provider credential, model name, settings, active selection.
- `backend/app/repositories/ai_config.py` — encrypted-key persistence and one-active-config-per-organization behavior.
- `backend/app/core/model_catalog.py` — BYO-key provider catalog and model suggestions.
- `backend/app/utils/agno_utils.py:create_model(...)` — the single model construction choke point.
- `backend/app/agents/chat_agent.py` — Agno execution and existing retry/error surface.

Supported source interfaces include OPENAI, ANTHROPIC, GOOGLE, GOOGLEVERTEX, GROQ, MISTRAL, DEEPSEEK, HUGGINGFACE, OLLAMA, XAI, OPENAI_COMPATIBLE, and the managed CHATTERMATE special case.

The catalog explicitly states that suggested models are not a hard allowlist. `custom_allowed=True` means a current provider model ID can be selected without creating a Yance translation provider registry.

## Current-model freshness shortlist

Fresh public-provider review on 2026-10-05 identified these current production candidates that fit an already-existing ChatterMate provider interface:

| Priority | Existing ChatterMate provider | Exact current model ID | Freshness / reason to qualify | Admission |
| --- | --- | --- | --- | --- |
| 1 | OPENAI | `gpt-6-astra` | OpenAI documents it as its most capable current model and as multilingual; strongest general first candidate. | NOT RUN — credential/runtime blocked |
| 2 | ANTHROPIC | `claude-opus-5-5` | Anthropic documents it as current strongest Opus and gives this exact Claude API ID. | NOT RUN — credential/runtime blocked |
| 3 | GOOGLE | `gemini-3.8-flash` | Stable GA since 2026-09-02; no shutdown announced. | NOT RUN — credential/runtime blocked |
| 4 | XAI | `grok-4.7` | Current frontier xAI API model, updated 2026-09-21. | NOT RUN — credential/runtime blocked |
| 5 | DEEPSEEK | `deepseek-flash` | Current DeepSeek V4.1 Flash API slug; predecessor V4 Flash retired. | NOT RUN — credential/runtime blocked |
| 6 | MISTRAL | `mistral-medium-latest` | Existing ChatterMate Mistral provider alias; current Medium 3.5 family is GA. | NOT RUN — credential/runtime blocked |

Freshness sources:

- https://developers.openai.com/api/docs/models/gpt-6-astra
- https://www.anthropic.com/claude/opus
- https://ai.google.dev/gemini-api/docs/deprecations
- https://docs.x.ai/developers/grok-4-7
- https://api-docs.deepseek.com/news/news260910/
- https://docs.mistral.ai/models/mistral-medium-3-5-26-04

This shortlist is not a quality claim for Yance translation. The required de/zh/en matrix and integrity invariants are the qualification authority.

## Credential/runtime qualification gate

Fresh machine inspection found:

- `OPENAI_API_KEY = UNSET`
- `ANTHROPIC_API_KEY = UNSET`
- `GROQ_API_KEY = UNSET`
- `GOOGLE_API_KEY = UNSET`
- `GEMINI_API_KEY = UNSET`
- `MISTRAL_API_KEY = UNSET`
- `DEEPSEEK_API_KEY = UNSET`
- `OPENROUTER_API_KEY = UNSET`
- no real project `.env` file; only `.env.example` files exist.
- `DATABASE_URL = UNSET` at Process/User/Machine scope.
- no local listener was present on TCP 5432, so there was no active rebuild PostgreSQL from which an `AIConfig` could be safely inspected.
- the repo `.venv-yance` is a focused test environment, not a full application provider runtime; importing the application stack there stops at missing `socketio` before a provider constructor can be meaningfully qualified.

No credential was printed, copied, decrypted, or fabricated.

## Ruling

ChatterMate's existing provider framework is the correct future execution boundary. No second provider framework is justified.

However, without an existing legitimate provider credential and a runnable provider environment, no exact model can be production-qualified in this phase.

`QUALIFICATION_BLOCKED_BY_PROVIDER_CREDENTIAL = TRUE`

`TRANSLATION = HOLD_OWNER_PRODUCTION_QUALIFICATION`
