#!/usr/bin/env python3
"""One-shot Native Messaging host for Window56 browser profile enrichment."""

from __future__ import annotations

import json
import os
import struct
import sys
from pathlib import Path


HOST_NAME = "com.yance.browser_profile_enrichment"
EXTENSION_ID = "hfcmihknnigilcafmalchjopmhhkihjf"
EXTENSION_ORIGIN = f"chrome-extension://{EXTENSION_ID}/"
MAX_MESSAGE_BYTES = 16 * 1024


def _binary_stdio() -> None:
    if sys.platform != "win32":
        return
    import msvcrt

    msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
    msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)


def _read_message():
    header = sys.stdin.buffer.read(4)
    if len(header) != 4:
        raise ValueError("missing native message header")
    length = struct.unpack("=I", header)[0]
    if length == 0 or length > MAX_MESSAGE_BYTES:
        raise ValueError("native message size rejected")
    body = sys.stdin.buffer.read(length)
    if len(body) != length:
        raise ValueError("truncated native message")
    return json.loads(body.decode("utf-8"))


def _write_message(message: dict) -> None:
    body = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("=I", len(body)))
    sys.stdout.buffer.write(body)
    sys.stdout.buffer.flush()


def _backend_root() -> Path:
    raw = os.environ.get("YANCE_BACKEND_ROOT", "")
    root = Path(raw).resolve() if raw else None
    if root is None or not (root / "app" / "database.py").is_file():
        raise RuntimeError("backend root is not configured")
    return root


def main() -> int:
    _binary_stdio()

    # Chromium supplies the calling extension origin as argv[1]. The manifest
    # also pins allowed_origins; this is defense in depth and blocks direct use
    # of the installed host from a different extension.
    if len(sys.argv) < 2 or sys.argv[1] != EXTENSION_ORIGIN:
        _write_message({"ok": False, "code": "CALLER_ORIGIN_REJECTED"})
        return 2

    try:
        raw = _read_message()
        backend_root = _backend_root()
        sys.path.insert(0, str(backend_root))

        # Importing app normally executes the web application's app/__init__.py,
        # which imports FastAPI/main and turns this one-shot host into a full
        # application bootstrap. Create only the package namespace needed for
        # direct service imports; no API/runtime owner is started here.
        import types
        if "app" not in sys.modules:
            app_package = types.ModuleType("app")
            app_package.__path__ = [str(backend_root / "app")]
            sys.modules["app"] = app_package
        if "app.models" not in sys.modules:
            models_package = types.ModuleType("app.models")
            models_package.__path__ = [str(backend_root / "app" / "models")]
            sys.modules["app.models"] = models_package

        # Validate before importing the DB/service stack.
        from app.services.browser_profile_enrichment_schema import (
            BrowserProfilePayloadError,
            validate_browser_profile_payload,
        )

        payload = validate_browser_profile_payload(raw)

        from app.database import SessionLocal
        from app.services.browser_profile_enrichment import (
            BrowserProfileBindingError,
            apply_browser_profile_enrichment,
        )

        db = SessionLocal()
        try:
            result = apply_browser_profile_enrichment(db, payload)
        finally:
            db.close()
        _write_message(result)
        return 0
    except Exception as exc:
        # Never reflect payload/HTML/secrets. Only bounded error classes/codes
        # cross back to the extension.
        code = getattr(exc, "code", None) or "HOST_REJECTED"
        if code not in {
            "INVALID_PAYLOAD", "UNKNOWN_FIELDS", "MISSING_FIELDS", "UNSUPPORTED_SCHEMA",
            "INVALID_FIELD_TYPE", "MISSING_IDENTITY", "FIELD_TOO_LONG",
            "CONTROL_CHARACTER_REJECTED", "DISALLOWED_ORIGIN", "PAGE_KIND_MISMATCH",
            "INVALID_IDENTITY", "NON_CANONICAL_THREAD_IDENTITY", "INVALID_AVATAR_URL",
            "NO_PROFILE_FIELDS", "ACCOUNT_IDENTITY_NOT_UNIQUE",
            "CONVERSATION_IDENTITY_NOT_UNIQUE", "CONFLICTING_PROVIDER_IDENTITY",
            "MISSING_CUSTOMER", "CROSS_ACCOUNT_ORGANIZATION",
            "CUSTOMER_IDENTITY_NOT_UNIQUE", "CROSS_CUSTOMER_ORGANIZATION",
            "MERGED_CUSTOMER_REJECTED", "INVALID_PERSON_PROFILE",
        }:
            code = "HOST_REJECTED"
        _write_message({"ok": False, "code": code})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
