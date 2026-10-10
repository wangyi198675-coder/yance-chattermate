from __future__ import annotations

import sys
import types
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if "app" not in sys.modules:
    _app = types.ModuleType("app")
    _app.__path__ = [str(_BACKEND / "app")]
    sys.modules["app"] = _app
if "app.models" not in sys.modules:
    _models = types.ModuleType("app.models")
    _models.__path__ = [str(_BACKEND / "app" / "models")]
    sys.modules["app.models"] = _models

import pytest

from app.services.browser_profile_enrichment_schema import (
    BrowserProfilePayloadError,
    CANONICAL_PROVIDER_MESSAGE,
    DIRECT_PROVIDER_USER,
    PROVENANCE,
    validate_browser_profile_payload,
)


def direct_payload(**updates):
    value = {
        "schema_version": 1,
        "binding_mode": DIRECT_PROVIDER_USER,
        "page_account_id": "1203748086150141",
        "thread_id": "61594960173176",
        "provider_user_id": "61594960173176",
        "display_name": "Visible Person",
        "avatar_url": "https://scontent.example.net/avatar.jpg",
        "origin": "https://www.facebook.com",
        "page_kind": "facebook_messages",
    }
    value.update(updates)
    return value


def message_payload(**updates):
    value = {
        "schema_version": 1,
        "binding_mode": CANONICAL_PROVIDER_MESSAGE,
        "page_account_id": "1203748086150141",
        "provider_message_ids": ["mid.$cAA.live-1"],
        "display_name": "Visible Person",
        "avatar_url": "https://scontent.example.net/avatar.jpg",
        "origin": "https://www.facebook.com",
        "page_kind": "facebook_messages",
    }
    value.update(updates)
    return value


def rejected(code: str, value: dict):
    with pytest.raises(BrowserProfilePayloadError) as exc:
        validate_browser_profile_payload(value)
    assert exc.value.code == code


def test_direct_payload_is_normalized_without_extra_state():
    result = validate_browser_profile_payload(direct_payload())
    assert result["binding_mode"] == DIRECT_PROVIDER_USER
    assert result["provider_message_ids"] == []
    assert result["provider_user_id"] == "61594960173176"
    assert PROVENANCE == "browser_assisted_user_visible"


def test_canonical_message_payload_is_normalized_without_direct_identity():
    result = validate_browser_profile_payload(message_payload())
    assert result["binding_mode"] == CANONICAL_PROVIDER_MESSAGE
    assert result["provider_message_ids"] == ["mid.$cAA.live-1"]
    assert result["thread_id"] is None
    assert result["provider_user_id"] is None


@pytest.mark.parametrize("secret_key", [
    "cookies", "password", "access_token", "localStorage", "sessionStorage",
    "outerHTML", "message_history", "message_body", "message_text",
    "browser_profile", "dom_dump",
])
def test_secret_or_message_content_fields_are_rejected_as_unknown(secret_key):
    rejected("UNKNOWN_FIELDS", message_payload(**{secret_key: "must-not-cross"}))


@pytest.mark.parametrize("avatar", [
    "data:image/png;base64,AA==",
    "blob:https://www.facebook.com/x",
    "file:///C:/secret.png",
    "javascript:alert(1)",
    "http://example.com/a.png",
    "https://user:pass@example.com/a.png",
])
def test_avatar_must_be_absolute_secret_free_https(avatar):
    rejected("INVALID_AVATAR_URL", direct_payload(avatar_url=avatar))


def test_profile_payload_cannot_be_empty():
    rejected("NO_PROFILE_FIELDS", message_payload(display_name=None, avatar_url=None))


@pytest.mark.parametrize("origin", [
    "https://business.facebook.com",
    "https://evil.facebook.com",
    "https://example.com",
    "http://www.facebook.com",
])
def test_disallowed_origin_fails_closed(origin):
    rejected("DISALLOWED_ORIGIN", direct_payload(origin=origin))


def test_origin_and_page_kind_must_match():
    rejected(
        "PAGE_KIND_MISMATCH",
        direct_payload(origin="https://www.messenger.com", page_kind="facebook_messages"),
    )


def test_thread_and_provider_user_must_be_same_canonical_psid():
    rejected("NON_CANONICAL_THREAD_IDENTITY", direct_payload(provider_user_id="999"))


@pytest.mark.parametrize("field", ["page_account_id", "thread_id", "provider_user_id"])
def test_direct_identity_must_be_bounded_decimal(field):
    rejected("INVALID_IDENTITY", direct_payload(**{field: "not-a-provider-id"}))


def test_direct_mode_rejects_provider_message_ids():
    rejected(
        "CONFLICTING_PROVIDER_IDENTITY",
        direct_payload(provider_message_ids=["mid.1"]),
    )


@pytest.mark.parametrize("updates", [
    {"thread_id": "123"},
    {"provider_user_id": "123"},
])
def test_canonical_message_mode_rejects_direct_identity_fields(updates):
    rejected("CONFLICTING_PROVIDER_IDENTITY", message_payload(**updates))


@pytest.mark.parametrize("ids", [
    [],
    ["mid.1", "mid.2", "mid.3", "mid.4", "mid.5", "mid.6"],
])
def test_provider_message_id_count_is_bounded(ids):
    rejected("INVALID_IDENTITY", message_payload(provider_message_ids=ids))


def test_duplicate_provider_message_ids_are_rejected():
    rejected(
        "CONFLICTING_PROVIDER_IDENTITY",
        message_payload(provider_message_ids=["mid.1", "mid.1"]),
    )


@pytest.mark.parametrize("mid", [
    "not-mid",
    "wamid.1",
    "mid.",
    "mid.bad/value",
])
def test_invalid_messenger_mid_format_is_rejected(mid):
    rejected("INVALID_IDENTITY", message_payload(provider_message_ids=[mid]))


def test_provider_message_id_length_is_bounded():
    rejected(
        "FIELD_TOO_LONG",
        message_payload(provider_message_ids=["mid." + "x" * 512]),
    )


def test_five_valid_mids_are_accepted():
    ids = [f"mid.{i}" for i in range(5)]
    result = validate_browser_profile_payload(message_payload(provider_message_ids=ids))
    assert result["provider_message_ids"] == ids


def test_bounded_display_name():
    rejected("FIELD_TOO_LONG", direct_payload(display_name="x" * 257))


def test_bounded_avatar_url():
    rejected("FIELD_TOO_LONG", direct_payload(avatar_url="https://example.com/" + "a" * 2030))
