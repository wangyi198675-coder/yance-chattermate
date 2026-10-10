"""Strict boundary schema for user-invoked browser profile enrichment.

This module is intentionally stdlib-only so the Native Messaging host can
validate a message before importing the application/database stack.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse


SCHEMA_VERSION = 1
PROVENANCE = "browser_assisted_user_visible"
DIRECT_PROVIDER_USER = "DIRECT_PROVIDER_USER"
CANONICAL_PROVIDER_MESSAGE = "CANONICAL_PROVIDER_MESSAGE"

ALLOWED_KEYS = frozenset({
    "schema_version",
    "binding_mode",
    "page_account_id",
    "thread_id",
    "provider_user_id",
    "provider_message_ids",
    "display_name",
    "avatar_url",
    "origin",
    "page_kind",
})
REQUIRED_KEYS = frozenset({
    "schema_version",
    "binding_mode",
    "page_account_id",
    "origin",
    "page_kind",
})
ALLOWED_ORIGINS = frozenset({
    "https://facebook.com",
    "https://www.facebook.com",
    "https://messenger.com",
    "https://www.messenger.com",
})
PAGE_KIND_BY_ORIGIN = {
    "https://facebook.com": "facebook_messages",
    "https://www.facebook.com": "facebook_messages",
    "https://messenger.com": "messenger_thread",
    "https://www.messenger.com": "messenger_thread",
}
_ID_RE = re.compile(r"^[0-9]{1,64}$")
_MID_RE = re.compile(r"^mid\.[A-Za-z0-9_$.:=-]{1,511}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


class BrowserProfilePayloadError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _bounded_text(value: Any, *, field: str, max_len: int, required: bool) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise BrowserProfilePayloadError("INVALID_FIELD_TYPE", f"{field} must be a string")
    value = value.strip()
    if not value:
        if required:
            raise BrowserProfilePayloadError("MISSING_IDENTITY", f"{field} is required")
        return None
    if len(value) > max_len:
        raise BrowserProfilePayloadError("FIELD_TOO_LONG", f"{field} exceeds {max_len} characters")
    if _CONTROL_RE.search(value):
        raise BrowserProfilePayloadError("CONTROL_CHARACTER_REJECTED", f"{field} contains control characters")
    return value


def _identity(value: Any, field: str) -> str:
    value = _bounded_text(value, field=field, max_len=64, required=True)
    assert value is not None
    if not _ID_RE.fullmatch(value):
        raise BrowserProfilePayloadError("INVALID_IDENTITY", f"{field} must be a decimal provider identifier")
    return value


def _provider_message_ids(value: Any) -> list[str]:
    if type(value) is not list:
        raise BrowserProfilePayloadError(
            "INVALID_FIELD_TYPE", "provider_message_ids must be a list"
        )
    if not 1 <= len(value) <= 5:
        raise BrowserProfilePayloadError(
            "INVALID_IDENTITY", "provider_message_ids must contain between 1 and 5 items"
        )
    normalized: list[str] = []
    for raw in value:
        item = _bounded_text(
            raw, field="provider_message_ids", max_len=515, required=True
        )
        assert item is not None
        if not _MID_RE.fullmatch(item):
            raise BrowserProfilePayloadError(
                "INVALID_IDENTITY", "provider_message_ids must contain exact Messenger MID values"
            )
        normalized.append(item)
    if len(set(normalized)) != len(normalized):
        raise BrowserProfilePayloadError(
            "CONFLICTING_PROVIDER_IDENTITY", "duplicate provider message ids are rejected"
        )
    return normalized


def validate_browser_profile_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise BrowserProfilePayloadError("INVALID_PAYLOAD", "payload must be an object")

    unknown = set(payload) - ALLOWED_KEYS
    if unknown:
        raise BrowserProfilePayloadError(
            "UNKNOWN_FIELDS",
            "unknown payload fields rejected: " + ", ".join(sorted(unknown)),
        )

    missing = REQUIRED_KEYS - set(payload)
    if missing:
        raise BrowserProfilePayloadError(
            "MISSING_FIELDS",
            "missing required payload fields: " + ", ".join(sorted(missing)),
        )

    if type(payload.get("schema_version")) is not int or payload["schema_version"] != SCHEMA_VERSION:
        raise BrowserProfilePayloadError("UNSUPPORTED_SCHEMA", "unsupported schema_version")

    origin = _bounded_text(payload.get("origin"), field="origin", max_len=64, required=True)
    if origin not in ALLOWED_ORIGINS:
        raise BrowserProfilePayloadError("DISALLOWED_ORIGIN", "origin is not admitted")

    page_kind = _bounded_text(payload.get("page_kind"), field="page_kind", max_len=32, required=True)
    if PAGE_KIND_BY_ORIGIN.get(origin) != page_kind:
        raise BrowserProfilePayloadError("PAGE_KIND_MISMATCH", "page_kind does not match origin")

    page_account_id = _identity(payload.get("page_account_id"), "page_account_id")
    binding_mode = _bounded_text(
        payload.get("binding_mode"), field="binding_mode", max_len=32, required=True
    )
    if binding_mode not in {DIRECT_PROVIDER_USER, CANONICAL_PROVIDER_MESSAGE}:
        raise BrowserProfilePayloadError("INVALID_IDENTITY", "binding_mode is not admitted")

    thread_id = None
    provider_user_id = None
    provider_message_ids: list[str] = []

    if binding_mode == DIRECT_PROVIDER_USER:
        if "provider_message_ids" in payload:
            raise BrowserProfilePayloadError(
                "CONFLICTING_PROVIDER_IDENTITY",
                "provider_message_ids are not allowed in direct-provider-user mode",
            )
        thread_id = _identity(payload.get("thread_id"), "thread_id")
        provider_user_id = _identity(payload.get("provider_user_id"), "provider_user_id")
        if thread_id != provider_user_id:
            raise BrowserProfilePayloadError(
                "NON_CANONICAL_THREAD_IDENTITY",
                "thread_id and provider_user_id must be the same Page-scoped Messenger identity",
            )
    else:
        if payload.get("thread_id") is not None or payload.get("provider_user_id") is not None:
            raise BrowserProfilePayloadError(
                "CONFLICTING_PROVIDER_IDENTITY",
                "direct-provider-user fields are not allowed in canonical-message mode",
            )
        provider_message_ids = _provider_message_ids(payload.get("provider_message_ids"))

    display_name = _bounded_text(
        payload.get("display_name"), field="display_name", max_len=256, required=False
    )

    avatar_url = _bounded_text(payload.get("avatar_url"), field="avatar_url", max_len=2048, required=False)
    if avatar_url is not None:
        parsed = urlparse(avatar_url)
        if parsed.scheme.lower() != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise BrowserProfilePayloadError("INVALID_AVATAR_URL", "avatar_url must be an absolute https URL")
        if parsed.scheme.lower() in {"data", "blob", "file", "javascript"}:
            raise BrowserProfilePayloadError("INVALID_AVATAR_URL", "avatar_url scheme is forbidden")

    if display_name is None and avatar_url is None:
        raise BrowserProfilePayloadError("NO_PROFILE_FIELDS", "no display name or avatar is present")

    return {
        "schema_version": SCHEMA_VERSION,
        "binding_mode": binding_mode,
        "page_account_id": page_account_id,
        "thread_id": thread_id,
        "provider_user_id": provider_user_id,
        "provider_message_ids": provider_message_ids,
        "display_name": display_name,
        "avatar_url": avatar_url,
        "origin": origin,
        "page_kind": page_kind,
    }
