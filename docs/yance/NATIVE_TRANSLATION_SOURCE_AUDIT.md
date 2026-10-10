# NATIVE_TRANSLATION_SOURCE_AUDIT

## Verdict

`CHATTERMATE_V1_0_25_DEFAULT_LANGUAGE_RUNTIME_OWNER = NO`

`CHATTERMATE_EXISTING_MODEL_PROVIDER_TRANSLATION_PRIMITIVE = PRESENT_BUT_NOT_PRODUCTION_QUALIFIED_IN_THIS_ENVIRONMENT`

The README claim `Auto Translation` is not sufficient evidence. Source tracing shows `workflow.default_language` is persisted and returned by schema/API, but v1.0.25 does not consume it in workflow execution, prompt assembly, model invocation, conversation state, or send routing.

## Source trace

- `backend/app/models/workflow.py`: `Workflow.default_language` is a stored column with default `en`.
- `backend/app/models/schemas/workflow.py`: create/update schema exposes the field.
- `backend/app/api/workflow.py`: API serializes/returns the field.
- migration `7fd0447b3d45_workflow_tables_added.py`: creates the column.
- No tracked execution-side reference to `default_language` exists in `backend/app` outside model/schema/API/migration/tests.
- `backend/app/services/workflow_execution.py` stores inbound `user_message` in workflow state, obtains `node.config.system_prompt`, and passes that prompt plus the existing AI config into `ChatAgent.create_async`.
- The LLM node then calls `chat_agent._get_llm_response_only(message=processed_user_message, ...)`.
- `backend/app/agents/chat_agent.py` uses the existing `create_model(model_type, api_key, model_name, max_tokens, base_url)` provider path and Agno Agent execution. No target-language instruction is injected from `workflow.default_language`.
- `backend/app/services/workflow_chat.py` stores the canonical inbound user message and the generated workflow response in `ChatHistory`.
- `backend/app/api/widget_chat.py` preserves the existing workflow/non-workflow ChatAgent paths and canonical send behavior.

## Language detection / explicit translation owner

No explicit native translation function/tool/prompt connected to `workflow.default_language` was found in the v1.0.25 execution chain. Lingua remains an admitted language-detection / integrity signal, not a translation owner.

## Existing model-provider path

ChatterMate's existing provider framework is a valid mature execution primitive and MUST be reused if a configured production provider is later selected. However this machine currently has no configured local model available for a real de/zh/en translation matrix (`ollama list` returned no models, and no production provider configuration was available in the clean source environment). Framework existence alone is not a production-admission result.

## Authority boundary

- `ChatHistory` remains message truth.
- `AIConfig` / existing ChatterMate model plumbing remains model/provider authority.
- `ChannelAdapter` / native message delivery remains physical send authority.
- No Translation DB, translation model registry, provider registry, or custom translator is introduced.
