"""Mock-safe SIWC plan model/Responses wire contracts, not an API client.

Caller MUST use a validated plan authorization, explicit approved native tools,
and the existing ChatterMate/Agno execution owner. This module opens no socket,
does not persist any token, cannot instantiate paid API-key providers and never
commits a native message/delivery from SSE deltas.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from app.core.siwc_protocol import GrantedAuthorization, PLAN_SCOPE, RESOURCE, SIWCError

MODELS_URL = RESOURCE + "/models"
RESPONSES_URL = RESOURCE + "/responses"
USAGE_URL = "https://chatgpt.com/#settings/usage"
_BLOCKED_FIELDS = frozenset({
    "background", "conversation", "max_output_tokens", "max_tool_calls",
    "metadata", "moderation", "multi_agent", "prompt", "prompt_cache_retention",
    "safety_identifier", "temperature", "top_logprobs", "top_p", "truncation",
    "user", "previous_response_id",
})
_ALLOWED_FIELDS = frozenset({"model", "input", "instructions", "tools"})
_REQUEST_ID = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")
_MAX_FRAME = 2 * 1024 * 1024


def require_plan_permission(grant: GrantedAuthorization) -> None:
    if not isinstance(grant, GrantedAuthorization) or grant.state != "plan_authorized_unverified":
        raise SIWCError("plan_permission_required")
    if PLAN_SCOPE not in grant.scopes or "resource.invoke" not in grant.scopes:
        raise SIWCError("plan_permission_required")


@dataclass(frozen=True)
class PlanModel:
    slug: str
    display_name: str


def listed_models(payload: Mapping[str, object], grant: GrantedAuthorization) -> tuple[PlanModel, ...]:
    """Only account-returned visibility=list models, no static API-key catalog.

    Phase-2 trust HOLD: caller-supplied grant and models are mockable values.
    The approved native owner must bind signed sub, issued client, protected
    bearer, actual same-account GET /models, model policy and current tenant.
    This helper does NOT authenticate those sources or access real accounts.
    """
    require_plan_permission(grant)
    if not isinstance(payload, Mapping) or not isinstance(payload.get("models"), list):
        raise SIWCError("models_invalid")
    result: list[PlanModel] = []
    seen: set[str] = set()
    for entry in payload["models"]:
        if not isinstance(entry, Mapping) or entry.get("visibility") != "list":
            continue
        slug, name = entry.get("slug"), entry.get("display_name")
        if (not isinstance(slug, str) or not slug or len(slug) > 200
                or not isinstance(name, str) or not name.strip() or len(name) > 200):
            raise SIWCError("model_entry_invalid")
        if slug in seen:
            raise SIWCError("model_duplicate_slug")
        seen.add(slug)
        result.append(PlanModel(slug, name))
    return tuple(result)


def make_responses_body(
    candidate: Mapping[str, object],
    *,
    grant: GrantedAuthorization,
    available_models: Sequence[PlanModel],
    approved_native_tools: Mapping[str, Mapping[str, object]] | None = None,
    allow_web_search: bool = False,
    approved_modalities: frozenset[str] = frozenset({"text"}),
) -> dict:
    """Strict wire mapper: strip preview-prohibited known Agno fields, reject unknowns.

    Input must come from canonical ChatterMate ChatHistory and approved persona
    in the later authorized integration, never from an independent history DB.
    Phase-2 trust HOLD: grant/model/catalog/tool policy are caller-supplied.
    Only a native authenticated account/tenant/turn owner may supply them;
    frontend values or this synthetic dataclass never establish real consent.
    """
    require_plan_permission(grant)
    if not isinstance(candidate, Mapping):
        raise SIWCError("responses_request_invalid")
    unknown = set(candidate) - (_ALLOWED_FIELDS | _BLOCKED_FIELDS | {"stream", "store"})
    if unknown:
        raise SIWCError("responses_field_not_qualified")
    if candidate.get("store", False) is not False or candidate.get("stream", True) is not True:
        raise SIWCError("mandatory_stream_privacy_flags")
    model = candidate.get("model")
    if not isinstance(model, str) or model not in {m.slug for m in available_models}:
        raise SIWCError("model_not_authorized_for_account")
    inputs = candidate.get("input")
    if not isinstance(inputs, list) or not inputs:
        raise SIWCError("canonical_history_required")
    _validate_preview_input(inputs, approved_modalities)
    body: dict = {"model": model, "input": inputs, "store": False, "stream": True}
    if "instructions" in candidate:
        if not isinstance(candidate["instructions"], str) or not candidate["instructions"].strip():
            raise SIWCError("invalid_instructions")
        body["instructions"] = candidate["instructions"]
    if "tools" in candidate:
        tools = candidate["tools"]
        _validate_native_tools(tools, approved_native_tools, allow_web_search)
        body["tools"] = tools
    return body


@dataclass(frozen=True)
class ResponseReceipt:
    """Only constructed after a real response.completed event, never from delta."""

    response_id: str
    output_text: str
    output: tuple[dict, ...]


def _extract_final_text(response: Mapping[str, object]) -> str:
    pieces: list[str] = []
    for item in response.get("output", []) or []:
        if not isinstance(item, Mapping) or item.get("type") != "message":
            continue
        for part in item.get("content", []) or []:
            if isinstance(part, Mapping) and part.get("type") == "output_text":
                pieces.append(str(part.get("text", "")))
    return "".join(pieces)


def parse_responses_sse(lines: Iterable[str]) -> ResponseReceipt:
    """Only emit a completed receipt; any interruption/errors fail closed.

    A native delivery caller must not use output_text.delta as a send trigger.
    Frames must be separated by empty SSE lines; [DONE] is not success.
    """
    event_name = ""
    data_lines: list[str] = []
    final: ResponseReceipt | None = None
    finished = False
    # Delta frames are NEVER authoritative and never used as a fallback.
    # Only the final response.completed.output may yield a receipt.

    def process_frame(name: str, parts: list[str]) -> tuple[ResponseReceipt | None, bool]:
        if not parts:
            return None, False
        raw = "\n".join(parts)
        if raw == "[DONE]":
            return None, True
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError) as exc:
            raise SIWCError("stream_invalid_json") from exc
        if not isinstance(payload, dict):
            raise SIWCError("stream_invalid_payload")
        declared_type = payload.get("type")
        if not isinstance(declared_type, str) or not declared_type:
            raise SIWCError("stream_invalid_event")
        if name and name != declared_type:
            raise SIWCError("stream_event_type_mismatch")
        event_type = declared_type
        frame_response = payload.get("response")
        response_status = frame_response.get("status") if isinstance(frame_response, Mapping) else None
        if response_status is not None and not isinstance(response_status, str):
            raise SIWCError("stream_invalid_response_status")
        if (response_status in {"failed", "incomplete", "error"}
                and event_type not in {"response.failed", "response.incomplete", "error", "response.error"}):
            raise SIWCError("stream_response_status_mismatch")
        if event_type in {"response.failed", "response.incomplete", "error", "response.error"}:
            err = payload.get("response") or payload.get("error")
            code = None
            if isinstance(err, dict):
                nested = err.get("error")
                code = nested.get("code") if isinstance(nested, dict) else err.get("code")
            mapped = map_plan_error(400, code if isinstance(code, str) else None)
            if mapped != "plan_bad_request":
                raise SIWCError(mapped)
            raise SIWCError("plan_stream_incomplete" if event_type == "response.incomplete" else "plan_stream_failed")
        if event_type == "response.output_text.delta":
            delta = payload.get("delta")
            if not isinstance(delta, str) or len(delta.encode("utf-8")) > _MAX_FRAME:
                raise SIWCError("stream_invalid_delta")
        if event_type == "response.completed":
            response = payload.get("response")
            if (not isinstance(response, Mapping)
                    or response.get("status") != "completed"
                    or response.get("error") is not None
                    or response.get("incomplete_details") is not None):
                raise SIWCError("stream_not_completed")
            identifier = response.get("id")
            if not isinstance(identifier, str) or not identifier.strip():
                raise SIWCError("stream_missing_response_id")
            output = response.get("output") or []
            if not isinstance(output, list) or not all(isinstance(x, dict) for x in output):
                raise SIWCError("stream_output_invalid")
            authoritative = _extract_final_text(response)
            final_text = authoritative
            has_function = any(
                item.get("type") == "function_call"
                and isinstance(item.get("name"), str) and item.get("name")
                and isinstance(item.get("call_id"), str) and item.get("call_id")
                for item in output
            )
            if not final_text.strip() and not has_function:
                raise SIWCError("stream_empty_completed")
            return ResponseReceipt(identifier, final_text, tuple(output)), False
        return None, False

    for line in lines:
        if not isinstance(line, str):
            raise SIWCError("stream_non_text")
        if len(line.encode("utf-8")) > _MAX_FRAME:
            raise SIWCError("stream_frame_too_large")
        stripped = line.rstrip("\r\n")
        if not stripped:
            result, done = process_frame(event_name, data_lines)
            if result is not None:
                if final is not None:
                    raise SIWCError("stream_duplicate_completion")
                final = result
            if done:
                finished = True
                event_name, data_lines = "", []
                break
            event_name, data_lines = "", []
            continue
        if stripped.startswith(":"):
            continue
        if stripped.startswith("event:"):
            event_name = stripped[6:].strip()
        elif stripped.startswith("data:"):
            data_lines.append(stripped[5:].lstrip())
            if sum(len(v.encode("utf-8")) for v in data_lines) > _MAX_FRAME:
                raise SIWCError("stream_frame_too_large")
    if data_lines:
        # A frame without its terminating blank line is a truncated transfer.
        raise SIWCError("stream_interrupted")
    if final is None:
        raise SIWCError("stream_interrupted" if not finished else "stream_not_completed")
    return final


def map_plan_error(status: int, error_code: str | None = None) -> str:
    """No secret-bearing provider messages; no retry or paid provider fallback."""
    known = {
        "subscription_sharing_usage_limit_exceeded": "plan_usage_limit_exceeded",
        "subscription_sharing_usage_unavailable": "plan_usage_unavailable",
        "subscription_sharing_user_not_eligible": "plan_account_not_eligible",
        "subscription_sharing_unsupported_capability": "plan_unsupported_capability",
        "subscription_sharing_route_not_supported": "plan_route_not_supported",
        "subscription_sharing_invalid_user": "plan_invalid_user",
        "subscription_sharing_user_unavailable": "plan_user_unavailable",
        "chatpass_v2_scope_not_authorized": "plan_scope_not_authorized",
        "chatpass_v2_invalid_authorization_context": "plan_authorization_context_invalid",
        "invalid_refresh_token": "reauthorization_required",
        "refresh_token_reused": "refresh_token_reuse_detected",
        "invalid_client": "client_registration_invalid",
        "invalid_grant": "reauthorization_required",
    }
    if isinstance(error_code, str) and error_code in known:
        return known[error_code]
    return {
        400: "plan_bad_request", 401: "plan_auth_expired",
        403: "plan_not_permitted", 429: "plan_usage_limit_or_rate_limited",
        503: "plan_usage_unavailable",
    }.get(status, "plan_service_error")


def safe_request_id(value: str | None) -> str | None:
    """Keep only opaque bounded IDs from provider headers for diagnostics."""
    return value if isinstance(value, str) and _REQUEST_ID.fullmatch(value) else None


def _validate_preview_input(
    inputs: list,
    approved_modalities: frozenset[str],
) -> None:
    """Only qualified text/image/file parts; no audio/video or opaque payloads.

    approved_modalities is provided by a *trusted native provider owner*, not
    from a frontend request. Without a Phase-2 account/model policy, only
    text is enabled by default. Tool-result and specialized item formats are
    postponed until their native contract is independently approved.
    """
    if (not isinstance(approved_modalities, frozenset)
            or not approved_modalities
            or not approved_modalities.issubset({"text", "image", "file"})):
        raise SIWCError("modality_policy_invalid")
    for item in inputs:
        if not isinstance(item, Mapping):
            raise SIWCError("invalid_input_item")
        if item.get("role") == "system":
            raise SIWCError("explicit_system_item_unsupported")
        if item.get("type", "message") != "message":
            raise SIWCError("unsupported_input_item")
        role = item.get("role")
        if not isinstance(role, str) or role not in {"developer", "user", "assistant"}:
            raise SIWCError("unsupported_input_role")
        content = item.get("content")
        if isinstance(content, str):
            if not content.strip() or "text" not in approved_modalities:
                raise SIWCError("invalid_text_input")
            continue
        if not isinstance(content, list) or not content:
            raise SIWCError("invalid_input_content")
        for part in content:
            if not isinstance(part, Mapping) or not isinstance(part.get("type"), str):
                raise SIWCError("unsupported_input_modality")
            part_type = part["type"]
            if part_type in {"input_text", "output_text"}:
                if ("text" not in approved_modalities
                        or not isinstance(part.get("text"), str)
                        or not part["text"].strip()):
                    raise SIWCError("invalid_text_input")
            elif part_type == "input_image":
                if "image" not in approved_modalities:
                    raise SIWCError("unsupported_input_modality")
                if not isinstance(part.get("image_url"), str) or not part["image_url"]:
                    raise SIWCError("invalid_image_input")
            elif part_type == "input_file":
                if "file" not in approved_modalities:
                    raise SIWCError("unsupported_input_modality")
                if not any(isinstance(part.get(k), str) and part[k] for k in ("file_id", "file_data")):
                    raise SIWCError("invalid_file_input")
            else:
                # Includes input_audio, input_video, and unknown future modes.
                raise SIWCError("unsupported_input_modality")


def _validate_native_tools(
    tools: list,
    approved_native_tools: Mapping[str, Mapping[str, object]] | None,
    allow_web_search: bool,
) -> None:
    """Exactly match trusted native declarations; no arbitrary function injection.

    Phase 1 never executes a tool. The Phase-2 ChatterMate/Agno owner must
    establish RBAC, per-current-turn consent and native tool policy *before*
    passing approved_native_tools, then separately authorize function results.
    """
    if not isinstance(tools, list):
        raise SIWCError("invalid_tools")
    if approved_native_tools is not None and not isinstance(approved_native_tools, Mapping):
        raise SIWCError("invalid_native_tool_policy")
    for tool in tools:
        if not isinstance(tool, Mapping):
            raise SIWCError("unsupported_hosted_tool")
        if tool.get("type") == "web_search":
            if not allow_web_search or dict(tool) != {"type": "web_search"}:
                raise SIWCError("web_search_not_authorized")
        elif tool.get("type") == "function":
            name = tool.get("name")
            if not isinstance(name, str) or re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]{0,63}", name) is None:
                raise SIWCError("native_function_not_authorized")
            spec = (approved_native_tools or {}).get(name)
            if not isinstance(spec, Mapping) or dict(spec) != dict(tool):
                raise SIWCError("native_function_not_authorized")
            schema = tool.get("parameters")
            if (not isinstance(schema, Mapping) or schema.get("type") != "object"
                    or not isinstance(schema.get("properties", {}), Mapping)):
                raise SIWCError("native_function_schema_invalid")
        else:
            raise SIWCError("unsupported_hosted_tool")
