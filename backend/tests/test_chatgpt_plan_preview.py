"""Synthetic contract/error injection for subscription preview. Never egress."""
import json

import pytest

from app.core.siwc_protocol import GrantedAuthorization, SIWCError, VerifiedIdentity, PLAN_SCOPE
from app.services.chatgpt_plan_preview import (
    MODELS_URL, RESPONSES_URL, ResponseReceipt, listed_models, make_responses_body,
    map_plan_error, parse_responses_sse, require_plan_permission, safe_request_id,
)


@pytest.fixture
def grant():
    return GrantedAuthorization(
        VerifiedIdentity("fake-subject", "oaiapp_synthetic123"),
        frozenset({"openid", "resource.invoke", PLAN_SCOPE}),
        "plan_authorized_unverified",
        3600,
    )


@pytest.fixture
def models(grant):
    return listed_models({"models": [
        {"slug": "synthetic-model-A", "display_name": "Model A", "visibility": "list"},
        {"slug": "hidden-model", "display_name": "Hidden", "visibility": "hidden"},
        {"slug": "synthetic-model-B", "display_name": "Model B", "visibility": "list"},
    ]}, grant)


def sse(event, payload):
    return ["event: " + event + "\n", "data: " + json.dumps(payload) + "\n", "\n"]


def completion(*, status="completed", output=None):
    return {
        "type": "response.completed",
        "response": {
            "id": "resp_SYNTHETIC", "status": status,
            "output": output if output is not None else [
                {"type": "message", "content": [
                    {"type": "output_text", "text": "Finished answer"}]}],
        },
    }


def test_account_models_only_listed_in_returned_order(grant, models):
    assert MODELS_URL.endswith("/v1/models")
    assert RESPONSES_URL.endswith("/v1/responses")
    assert [m.slug for m in models] == ["synthetic-model-A", "synthetic-model-B"]
    assert models[0].display_name == "Model A"


@pytest.mark.parametrize("payload", [
    {}, {"models": {}},
    {"models": [{"slug": "bad", "visibility": "list"}]},
    {"models": [{"slug": "dupe", "display_name": "One", "visibility": "list"},
                {"slug": "dupe", "display_name": "Two", "visibility": "list"}]},
])
def test_bad_model_list_fails(grant, payload):
    with pytest.raises(SIWCError):
        listed_models(payload, grant)


def test_identity_only_blocks_catalog_and_inference(grant, models):
    identity_only = GrantedAuthorization(grant.identity, frozenset({"openid"}),
                                         "identity_only", 3600)
    with pytest.raises(SIWCError, match="plan_permission_required"):
        listed_models({"models": []}, identity_only)
    with pytest.raises(SIWCError, match="plan_permission_required"):
        make_responses_body({"model": "synthetic-model-A", "input": [{"role": "user", "content": "x"}]},
                            grant=identity_only, available_models=models)


def test_plan_request_drops_unsupported_agno_fields_and_fixes_flags(grant, models):
    body = make_responses_body({
        "model": "synthetic-model-A",
        "input": [{"role": "developer", "content": "scope"},
                  {"role": "user", "content": "hello"}],
        "instructions": "You are the approved persona.",
        "tools": [{"type": "function", "name": "safe_lookup", "parameters": {"type": "object"}}],
        "max_output_tokens": 500,
        "temperature": 0.8,
        "metadata": {"source": "unapproved"},
        "previous_response_id": "DO_NOT_REUSE",
        "stream": True,
        "store": False,
    }, grant=grant, available_models=models, approved_native_tools={
        "safe_lookup": {"type": "function", "name": "safe_lookup",
                        "parameters": {"type": "object"}}
    })
    assert body["model"] == "synthetic-model-A"
    assert body["stream"] is True and body["store"] is False
    assert "metadata" not in body and "temperature" not in body
    assert "max_output_tokens" not in body
    assert "previous_response_id" not in body
    assert body["instructions"] == "You are the approved persona."
    assert body["tools"][0]["name"] == "safe_lookup"


@pytest.mark.parametrize("change,code", [
    ({"store": True}, "mandatory_stream_privacy_flags"),
    ({"stream": False}, "mandatory_stream_privacy_flags"),
    ({"model": "not-on-account"}, "model_not_authorized_for_account"),
    ({"input": []}, "canonical_history_required"),
    ({"input": [{"type": "message", "role": "system", "content": "x"}]},
     "explicit_system_item_unsupported"),
    ({"tools": [{"type": "computer_use_preview"}]}, "unsupported_hosted_tool"),
    ({"tools": [{"type": "file_search"}]}, "unsupported_hosted_tool"),
    ({"tools": [{"type": "code_interpreter"}]}, "unsupported_hosted_tool"),
    ({"tools": [{"type": "mcp"}]}, "unsupported_hosted_tool"),
    ({"tools": [{"type": "tool_search"}]}, "unsupported_hosted_tool"),
    ({"unsupported_new_field": "x"}, "responses_field_not_qualified"),
])
def test_responses_security_failures(grant, models, change, code):
    values = {"model": "synthetic-model-A", "input": [{"role": "user", "content": "Hi"}]}
    values.update(change)
    with pytest.raises(SIWCError) as exc:
        make_responses_body(values, grant=grant, available_models=models)
    assert exc.value.code == code


def test_sse_delta_never_counts_as_completed():
    frames = sse("response.output_text.delta",
                 {"type": "response.output_text.delta", "delta": "provisional"})
    with pytest.raises(SIWCError, match="stream_interrupted"):
        parse_responses_sse(frames)


def test_sse_completed_returns_verified_receipt():
    frames = sse("response.output_text.delta",
                 {"type": "response.output_text.delta", "delta": "provisional"})
    frames += sse("response.completed", completion())
    frames += ["data: [DONE]\n", "\n"]
    receipt = parse_responses_sse(frames)
    assert isinstance(receipt, ResponseReceipt)
    assert receipt.response_id == "resp_SYNTHETIC"
    assert receipt.output_text == "Finished answer"
    assert len(receipt.output) == 1


def test_sse_completed_without_text_but_custom_tool_output(grant):
    tool = {"type": "function_call", "name": "lookup", "call_id": "fake-call-id",
            "arguments": "{}"}
    receipt = parse_responses_sse(sse("response.completed", completion(output=[tool])))
    assert receipt.output_text == ""
    assert receipt.output[0]["type"] == "function_call"


@pytest.mark.parametrize("frames", [
    sse("response.failed", {"type": "response.failed", "response": {
        "error": {"code": "subscription_sharing_usage_limit_exceeded"}}}),
    sse("response.incomplete", {"type": "response.incomplete", "response": {}}),
    sse("error", {"type": "error", "error": {"code": "invalid_grant"}}),
])
def test_failed_or_incomplete_sse_never_returns_receipt(frames):
    with pytest.raises(SIWCError):
        parse_responses_sse(frames)


def test_sse_partial_json_or_done_without_completion_fail():
    for frames in [
        ["data: {not-json}\n", "\n"],
        ["data: [DONE]\n", "\n"],
        ["event: response.completed\n", "data: {\"type\":\"response.completed\"}\n"],
        ["event: response.completed\n", "data: {\"type\":\"response.completed\",\"response\":{}}\n", "\n"],
    ]:
        with pytest.raises(SIWCError):
            parse_responses_sse(frames)


def test_no_double_completion():
    frames = sse("response.completed", completion()) + sse("response.completed", completion())
    with pytest.raises(SIWCError, match="stream_duplicate_completion"):
        parse_responses_sse(frames)


def test_oversized_stream_is_rejected_before_receipt():
    with pytest.raises(SIWCError, match="stream_frame_too_large"):
        parse_responses_sse(["data: " + "x" * (2 * 1024 * 1024 + 10), "\n"])


@pytest.mark.parametrize("status,provider_code,expected", [
    (429, "subscription_sharing_usage_limit_exceeded", "plan_usage_limit_exceeded"),
    (503, "subscription_sharing_usage_unavailable", "plan_usage_unavailable"),
    (403, "subscription_sharing_user_not_eligible", "plan_account_not_eligible"),
    (400, "subscription_sharing_unsupported_capability", "plan_unsupported_capability"),
    (401, None, "plan_auth_expired"),
    (403, None, "plan_not_permitted"),
    (429, None, "plan_usage_limit_or_rate_limited"),
    (503, None, "plan_usage_unavailable"),
])
def test_status_error_mapping_never_falls_back_to_paid_provider(status, provider_code, expected):
    assert map_plan_error(status, provider_code) == expected
    assert "OPENAI" not in expected and "fallback" not in expected


def test_request_id_redaction():
    assert safe_request_id("req_FAKE_abc-123") == "req_FAKE_abc-123"
    assert safe_request_id("Bearer secret-token\n") is None
    assert safe_request_id("x" * 129) is None


def test_no_paid_provider_egress_path_in_phase1_source():
    import inspect
    import app.core.siwc_protocol as protocol
    import app.services.chatgpt_plan_preview as preview
    combined = inspect.getsource(protocol) + inspect.getsource(preview)
    assert "requests.post(" not in combined
    assert "httpx.post(" not in combined
    assert "ChatAgent.create_async(" not in combined
    assert "OpenAIChat(" not in combined
    assert "localStorage" not in combined


def test_empty_completed_message_not_success():
    empty_message = {"type": "message", "content": []}
    with pytest.raises(SIWCError, match="stream_empty_completed"):
        parse_responses_sse(sse("response.completed", completion(output=[empty_message])))


def test_provider_error_code_mapping_in_stream():
    failures = [
        ("subscription_sharing_usage_limit_exceeded", "plan_usage_limit_exceeded"),
        ("subscription_sharing_usage_unavailable", "plan_usage_unavailable"),
        ("subscription_sharing_user_not_eligible", "plan_account_not_eligible"),
        ("subscription_sharing_unsupported_capability", "plan_unsupported_capability"),
        ("invalid_grant", "reauthorization_required"),
    ]
    for provider_code, expected in failures:
        frames = sse("response.failed", {"type": "response.failed",
                                           "response": {"error": {"code": provider_code}}})
        with pytest.raises(SIWCError) as exc:
            parse_responses_sse(frames)
        assert exc.value.code == expected


def test_completed_then_failed_stream_fails_closed():
    frames = sse("response.completed", completion()) + sse("response.failed", {
        "type": "response.failed", "response": {"error": {"code": "subscription_sharing_usage_limit_exceeded"}}})
    with pytest.raises(SIWCError, match="plan_usage_limit_exceeded"):
        parse_responses_sse(frames)


def test_explicit_system_item_must_not_be_mapped(grant, models):
    with pytest.raises(SIWCError, match="explicit_system_item_unsupported"):
        make_responses_body({"model": "synthetic-model-A",
                             "input": [{"role": "system", "content": "bad"}]},
                            grant=grant, available_models=models)


# W378 P0-2: contradictory event header, JSON type, response.status
@pytest.mark.parametrize("header,json_type,status", [
    ("response.completed", "response.failed", "completed"),
    ("response.completed", "response.incomplete", "completed"),
    ("response.completed", "error", "completed"),
    ("response.failed", "response.completed", "completed"),
    ("response.incomplete", "response.completed", "completed"),
    ("error", "response.completed", "completed"),
    ("response.completed", "response.completed", "failed"),
    ("response.completed", "response.completed", "incomplete"),
    ("response.completed", "response.completed", "error"),
    ("response.created", "response.created", "failed"),
    ("response.completed", "response.output_text.delta", "completed"),
])
def test_sse_forged_completion_mismatched_status_never_receipt(header, json_type, status):
    fake = completion(status=status)
    fake["type"] = json_type
    with pytest.raises(SIWCError):
        parse_responses_sse(sse(header, fake))


def test_sse_failure_then_completed_and_done_only_never_succeeds():
    failed = sse("response.failed", {"type": "response.failed", "response": {
        "status": "failed", "error": {"code": "subscription_sharing_usage_limit_exceeded"}}})
    with pytest.raises(SIWCError):
        parse_responses_sse(failed + sse("response.completed", completion()))
    for lines in (["data: [DONE]\n", "\n"],
                  sse("response.output_text.delta",
                      {"type": "response.output_text.delta", "delta": "not final"}) +
                  ["data: [DONE]\n", "\n"],
                  sse("response.completed", completion())[:-1],
                  sse("response.completed", {"type": "response.completed", "response": {
                      "id": "resp_fake", "status": "completed", "output": [],
                      "error": {"code": "some_error"}}})):
        with pytest.raises(SIWCError):
            parse_responses_sse(lines)


def test_no_provisional_delta_recovery_after_completed_empty_output():
    frames = sse("response.output_text.delta",
                 {"type": "response.output_text.delta", "delta": "untrusted draft"})
    frames += sse("response.completed", completion(output=[]))
    with pytest.raises(SIWCError, match="stream_empty_completed"):
        parse_responses_sse(frames)


def _native_tool(name="safe_lookup", parameters=None):
    return {"type": "function", "name": name,
            "parameters": parameters or {"type": "object", "properties": {"term": {"type": "string"}}}}


@pytest.mark.parametrize("name", ["unapproved_sensitive_action", "send_message", "payment", "safe_lookup!"])
def test_unapproved_functions_rejected_even_if_schemas_look_valid(grant, models, name):
    candidate = {"model": models[0].slug, "input": [{"role": "user", "content": "hi"}],
                 "tools": [_native_tool(name)]}
    with pytest.raises(SIWCError, match="native_function_not_authorized"):
        make_responses_body(candidate, grant=grant, available_models=models)


def test_exact_native_function_schema_and_name_approval_required(grant, models):
    approved = _native_tool()
    candidate = {"model": models[0].slug, "input": [{"role": "user", "content": "hi"}],
                 "tools": [approved]}
    body = make_responses_body(candidate, grant=grant, available_models=models,
                               approved_native_tools={"safe_lookup": approved})
    assert body["tools"] == [approved]
    tampered = _native_tool(parameters={"type": "object", "properties": {"secret": {"type": "string"}}})
    candidate["tools"] = [tampered]
    with pytest.raises(SIWCError, match="native_function_not_authorized"):
        make_responses_body(candidate, grant=grant, available_models=models,
                            approved_native_tools={"safe_lookup": approved})
    invalid_spec = _native_tool(parameters={"type": "array"})
    candidate["tools"] = [invalid_spec]
    with pytest.raises(SIWCError, match="native_function_schema_invalid"):
        make_responses_body(candidate, grant=grant, available_models=models,
                            approved_native_tools={"safe_lookup": invalid_spec})


def test_web_search_requires_explicit_native_policy(grant, models):
    candidate = {"model": models[0].slug, "input": [{"role": "user", "content": "hi"}],
                 "tools": [{"type": "web_search"}]}
    with pytest.raises(SIWCError, match="web_search_not_authorized"):
        make_responses_body(candidate, grant=grant, available_models=models)
    body = make_responses_body(candidate, grant=grant, available_models=models, allow_web_search=True)
    assert body["tools"] == [{"type": "web_search"}]
    candidate["tools"] = [{"type": "web_search", "external_url": "https://attacker.example"}]
    with pytest.raises(SIWCError, match="web_search_not_authorized"):
        make_responses_body(candidate, grant=grant, available_models=models, allow_web_search=True)


@pytest.mark.parametrize("part_type", ["input_audio", "input_video", "audio", "video", "input_audio_buffer", "unqualified_future_media"])
def test_unsupported_nested_media_rejected(grant, models, part_type):
    candidate = {"model": models[0].slug, "input": [{
        "role": "user", "content": [{"type": part_type, "data": "FAKE-BYTES"}]}]}
    with pytest.raises(SIWCError, match="unsupported_input_modality"):
        make_responses_body(candidate, grant=grant, available_models=models,
                            approved_modalities=frozenset({"text", "image", "file"}))


@pytest.mark.parametrize("part,modality", [
    ({"type": "input_image", "image_url": "data:image/png;base64,ZmFrZQ=="}, "image"),
    ({"type": "input_file", "file_id": "file_synthetic"}, "file"),
])
def test_text_image_file_requires_explicit_model_policy(grant, models, part, modality):
    candidate = {"model": models[0].slug, "input": [{"role": "user",
                 "content": [{"type": "input_text", "text": "sample"}, part]}]}
    with pytest.raises(SIWCError, match="unsupported_input_modality"):
        make_responses_body(candidate, grant=grant, available_models=models)
    body = make_responses_body(candidate, grant=grant, available_models=models,
            approved_modalities=frozenset({"text", modality}))
    assert body["input"][0]["content"][-1] == part


@pytest.mark.parametrize("provider_code,expected", [
    ("subscription_sharing_route_not_supported", "plan_route_not_supported"),
    ("subscription_sharing_invalid_user", "plan_invalid_user"),
    ("subscription_sharing_user_unavailable", "plan_user_unavailable"),
    ("chatpass_v2_scope_not_authorized", "plan_scope_not_authorized"),
    ("chatpass_v2_invalid_authorization_context", "plan_authorization_context_invalid"),
    ("invalid_refresh_token", "reauthorization_required"),
    ("refresh_token_reused", "refresh_token_reuse_detected"),
    ("invalid_client", "client_registration_invalid"),
])
def test_typed_membership_and_refresh_errors_fail_closed(provider_code, expected):
    assert map_plan_error(400, provider_code) == expected
    with pytest.raises(SIWCError) as exc:
        parse_responses_sse(sse("response.failed", {"type": "response.failed",
            "response": {"status": "failed", "error": {"code": provider_code}}}))
    assert exc.value.code == expected


def test_unstructured_unknown_error_no_fallback_or_typeerror():
    assert map_plan_error(503, ["bad-list"]) == "plan_usage_unavailable"
    with pytest.raises(SIWCError):
        parse_responses_sse(sse("response.completed", {
            "type": "response.completed", "response": {"id": "fake", "status": [],
            "output": [{"type": "message", "content": [
                {"type": "output_text", "text": "must_not_send"}]}]}}))
