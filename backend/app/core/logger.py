"""
Copyright 2024-2026 ChatterMate

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

from __future__ import annotations

import logging
import os
import re
import sys
import threading
from collections.abc import Mapping
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit, urlunsplit

_REDACTED = "[REDACTED]"
_REDACTED_URL = "[REDACTED_URL]"
_REDACTED_PATH = "[REDACTED_PATH]"
_TRUNCATED = "[TRUNCATED]"
_REDACTION_FAILED = "[REDACTION_FAILED]"
_SAFE_DYNAMIC_MARKERS = {
    _REDACTED,
    _REDACTED_URL,
    _REDACTED_PATH,
    _TRUNCATED,
    _REDACTION_FAILED,
}

_MAX_DEPTH = 5
_MAX_ITEMS = 50
_MAX_STRING_LENGTH = 4096

_PRODUCTION_ENVIRONMENTS = {"prod", "production"}
_QUALIFICATION_ENVIRONMENTS = {"qual", "qualification"}

_SENSITIVE_KEY_PARTS = (
    "authorization",
    "bearer",
    "token",
    "secret",
    "password",
    "passwd",
    "cookie",
    "credential",
    "signature",
    "ciphertext",
    "encrypted",
    "api_key",
    "apikey",
    "access_key",
    "private_key",
    "verify_token",
    "webhook_token",
)

_NEVER_LOG_KEYS = {
    "message",
    "message_body",
    "translation",
    "translated_body",
    "prompt",
    "system_prompt",
    "system_instruction",
    "instructions",
    "context",
    "model_response",
    "completion",
    "content",
    "body",
    "text",
    "payload",
    "raw_payload",
    "provider_payload",
    "provider_request",
    "provider_response",
    "request_body",
    "response_body",
    "webhook",
    "webhook_payload",
    "form",
    "form_data",
    "user_input",
    "workflow_result",
    "person_profile",
    "customer",
    "media",
    "attachment",
    "attachments",
    "transcript",
    "bytes",
    "base64",
    "filename",
    "file_path",
    "local_path",
    "email",
    "phone",
}

_HEADER_SECRET_RE = re.compile(
    r"(?im)\b(authorization|proxy-authorization|cookie|set-cookie)"
    r"\s*[:=]\s*[^\r\n]+"
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_KEY_VALUE_SECRET_RE = re.compile(
    r"(?i)\b("
    r"api[_-]?key|access[_-]?token|refresh[_-]?token|id[_-]?token|"
    r"session[_-]?token|conversation[_-]?token|client[_-]?secret|app[_-]?secret|"
    r"password|passwd|credential|encrypted[_-]?api[_-]?key|ciphertext|"
    r"aws[_-]?(?:secret[_-]?access[_-]?key|access[_-]?key[_-]?id)|"
    r"signing[_-]?secret|encryption[_-]?secret|jwt[_-]?secret|"
    r"webhook[_-]?(?:secret|token)|verify[_-]?token|signature"
    r")\b(\s*[:=]\s*)"
    r'''(?:"[^"]*"|'[^']*'|[^\s,;]+)'''
)
_NEVER_LOG_LABEL_RE = re.compile(
    r"(?i)\b("
    r"message|translation|prompt|system[_ -]?instruction|model[_ -]?response|"
    r"provider[_ -]?(?:payload|request|response)|raw[_ -]?payload|webhook[_ -]?payload|"
    r"form[_ -]?data|user[_ -]?input|workflow[_ -]?result|"
    r"person[_ -]?profile|customer|media|transcript|"
    r"request[_ -]?body|response[_ -]?body|content|body"
    r")\b(\s*[:=]\s*)"
    r'''(?:"[^"]*"|'[^']*'|[^\r\n,;]*?)(?=\s+[A-Za-z_][A-Za-z0-9_.-]*\s*[:=]|[,;\r\n]|$)'''
)
_URL_RE = re.compile(
    r"(?i)\b(?:https?|redis(?:s)?|postgres(?:ql)?|mysql|mariadb|"
    r'''amqp(?:s)?|mongodb(?:\+srv)?):\/\/[^\s"'<>]+'''
)
_WINDOWS_PATH_RE = re.compile(
    r'''(?i)(?<![A-Za-z0-9_])(?:[A-Z]:[\\/]|\\\\).*?(?=\s+[A-Za-z_][A-Za-z0-9_.-]*\s*[:=]|[,;\r\n]|$)'''
)
_PRIVATE_UNIX_PATH_RE = re.compile(
    r'''(?<![A-Za-z0-9_])/(?:home|Users|tmp|var/tmp)/.*?(?=\s+[A-Za-z_][A-Za-z0-9_.-]*\s*[:=]|[,;\r\n]|$)'''
)
_EMAIL_RE = re.compile(
    r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"
)
_JWT_RE = re.compile(
    r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"
)
_AWS_ACCESS_KEY_RE = re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")
_SAFE_TYPE_MARKER_RE = re.compile(r"^<[A-Za-z_][A-Za-z0-9_.]{0,80}>$")

_config_lock = threading.RLock()
_configured = False


def _normalize_key(key: str) -> str:
    return key.strip().lower().replace("-", "_").replace(" ", "_")


def _is_sensitive_key(key: str) -> bool:
    normalized = _normalize_key(key)
    if normalized == "key" or normalized.endswith("_key"):
        return True
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _is_never_log_key(key: str) -> bool:
    normalized = _normalize_key(key)
    return normalized in _NEVER_LOG_KEYS


def _safe_mapping_key(key: Any) -> str:
    if not isinstance(key, str):
        return "[REDACTED_KEY]"
    candidate = key[:80]
    if re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", candidate):
        return candidate
    return "[REDACTED_KEY]"


def _is_signed_or_oauth_url(raw_url: str) -> bool:
    try:
        query_keys = {
            key.lower()
            for key, _ in parse_qsl(urlsplit(raw_url).query, keep_blank_values=True)
        }
    except Exception:
        return True

    sensitive_query_parts = (
        "signature",
        "x-amz-",
        "x-goog-",
        "token",
        "secret",
        "state",
        "code",
        "credential",
        "key",
        "sig",
    )
    return any(
        any(part in key for part in sensitive_query_parts)
        for key in query_keys
    )


def _sanitize_url(raw_url: str) -> str:
    try:
        if _is_signed_or_oauth_url(raw_url):
            return _REDACTED_URL

        parts = urlsplit(raw_url)
        host = parts.hostname
        if not parts.scheme or not host:
            return _REDACTED_URL

        safe_host = f"[{host}]" if ":" in host and not host.startswith("[") else host
        try:
            port = parts.port
        except ValueError:
            return _REDACTED_URL
        netloc = f"{safe_host}:{port}" if port else safe_host

        return urlunsplit((parts.scheme, netloc, parts.path, "", ""))
    except Exception:
        return _REDACTED_URL


def _sanitize_string(value: str) -> str:
    try:
        sanitized = _HEADER_SECRET_RE.sub(
            lambda match: f"{match.group(1)}: {_REDACTED}", value
        )
        sanitized = _BEARER_RE.sub(f"Bearer {_REDACTED}", sanitized)
        sanitized = _KEY_VALUE_SECRET_RE.sub(
            lambda match: f"{match.group(1)}{match.group(2)}{_REDACTED}",
            sanitized,
        )
        sanitized = _NEVER_LOG_LABEL_RE.sub(
            lambda match: f"{match.group(1)}{match.group(2)}{_REDACTED}",
            sanitized,
        )
        sanitized = _JWT_RE.sub(_REDACTED, sanitized)
        sanitized = _AWS_ACCESS_KEY_RE.sub(_REDACTED, sanitized)
        sanitized = _URL_RE.sub(lambda match: _sanitize_url(match.group(0)), sanitized)
        sanitized = _WINDOWS_PATH_RE.sub(_REDACTED_PATH, sanitized)
        sanitized = _PRIVATE_UNIX_PATH_RE.sub(_REDACTED_PATH, sanitized)
        sanitized = _EMAIL_RE.sub(_REDACTED, sanitized)

        if len(sanitized) > _MAX_STRING_LENGTH:
            sanitized = f"{sanitized[:_MAX_STRING_LENGTH]}{_TRUNCATED}"
        return sanitized
    except Exception:
        return _REDACTION_FAILED


def _sanitize_value(
    value: Any,
    *,
    key: str | None = None,
    depth: int = 0,
    seen: set[int] | None = None,
) -> Any:
    if key is not None and (_is_sensitive_key(key) or _is_never_log_key(key)):
        return _REDACTED

    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _sanitize_string(value)
    if isinstance(value, (bytes, bytearray, memoryview, os.PathLike)):
        return _REDACTED
    if isinstance(value, BaseException):
        return f"<{type(value).__name__}>"

    if depth >= _MAX_DEPTH:
        return _TRUNCATED

    if seen is None:
        seen = set()

    if isinstance(value, Mapping):
        value_id = id(value)
        if value_id in seen:
            return _TRUNCATED
        seen.add(value_id)
        try:
            sanitized: dict[str, Any] = {}
            for index, (raw_key, raw_value) in enumerate(value.items()):
                if index >= _MAX_ITEMS:
                    sanitized["__truncated__"] = _TRUNCATED
                    break
                safe_key = _safe_mapping_key(raw_key)
                sanitized[safe_key] = _sanitize_value(
                    raw_value,
                    key=safe_key,
                    depth=depth + 1,
                    seen=seen,
                )
            return sanitized
        except Exception:
            return _REDACTION_FAILED
        finally:
            seen.discard(value_id)

    if isinstance(value, (list, tuple, set, frozenset)):
        value_id = id(value)
        if value_id in seen:
            return _TRUNCATED
        seen.add(value_id)
        try:
            sanitized_items = [
                _sanitize_value(item, depth=depth + 1, seen=seen)
                for item in list(value)[:_MAX_ITEMS]
            ]
            if len(value) > _MAX_ITEMS:
                sanitized_items.append(_TRUNCATED)
            return tuple(sanitized_items) if isinstance(value, tuple) else sanitized_items
        except Exception:
            return _REDACTION_FAILED
        finally:
            seen.discard(value_id)

    return f"<{type(value).__name__}>"


def _sanitize_log_argument(
    value: Any,
    *,
    key: str | None = None,
    depth: int = 0,
    seen: set[int] | None = None,
) -> Any:
    """Treat every dynamic string/container value as private unless it is numeric metadata."""
    if key is not None and (_is_sensitive_key(key) or _is_never_log_key(key)):
        return _REDACTED

    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, BaseException):
        return f"<{type(value).__name__}>"
    if isinstance(value, str):
        if value in _SAFE_DYNAMIC_MARKERS or _SAFE_TYPE_MARKER_RE.fullmatch(value):
            return value
        return _REDACTED
    if isinstance(value, (bytes, bytearray, memoryview, os.PathLike)):
        return _REDACTED

    if depth >= _MAX_DEPTH:
        return _TRUNCATED

    if seen is None:
        seen = set()

    if isinstance(value, Mapping):
        value_id = id(value)
        if value_id in seen:
            return _TRUNCATED
        seen.add(value_id)
        try:
            sanitized: dict[str, Any] = {}
            for index, (raw_key, raw_value) in enumerate(value.items()):
                if index >= _MAX_ITEMS:
                    sanitized["__truncated__"] = _TRUNCATED
                    break
                safe_key = _safe_mapping_key(raw_key)
                sanitized[safe_key] = _sanitize_log_argument(
                    raw_value,
                    key=safe_key,
                    depth=depth + 1,
                    seen=seen,
                )
            return sanitized
        except Exception:
            return _REDACTION_FAILED
        finally:
            seen.discard(value_id)

    if isinstance(value, (list, tuple, set, frozenset)):
        value_id = id(value)
        if value_id in seen:
            return _TRUNCATED
        seen.add(value_id)
        try:
            sanitized_items = [
                _sanitize_log_argument(item, depth=depth + 1, seen=seen)
                for item in list(value)[:_MAX_ITEMS]
            ]
            if len(value) > _MAX_ITEMS:
                sanitized_items.append(_TRUNCATED)
            return tuple(sanitized_items) if isinstance(value, tuple) else sanitized_items
        except Exception:
            return _REDACTION_FAILED
        finally:
            seen.discard(value_id)

    return f"<{type(value).__name__}>"


def _sanitize_args(args: Any) -> Any:
    if not args:
        return args
    return _sanitize_log_argument(args)


def _sanitize_record(record: logging.LogRecord) -> logging.LogRecord:
    """Make a LogRecord privacy-safe before any handler can observe it."""
    try:
        if not isinstance(record.msg, str):
            record.msg = _sanitize_value(record.msg)

        record.args = _sanitize_args(record.args)
        safe_exception = None
        if record.exc_info:
            try:
                safe_exception = f"<{record.exc_info[0].__name__}>"
            except Exception:
                safe_exception = "<Exception>"

        rendered = _sanitize_string(record.getMessage())
        if safe_exception:
            rendered = f"{rendered} exception={safe_exception}"

        record.msg = rendered
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        return record
    except Exception:
        record.msg = _REDACTION_FAILED
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        return record


def _install_privacy_record_factory() -> None:
    """Wrap the active stdlib factory once so every later handler sees safe records."""
    current_factory = logging.getLogRecordFactory()
    if getattr(current_factory, "_yance_privacy_record_factory", False):
        return

    def privacy_record_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        return _sanitize_record(current_factory(*args, **kwargs))

    privacy_record_factory._yance_privacy_record_factory = True  # type: ignore[attr-defined]
    privacy_record_factory._yance_wrapped_record_factory = current_factory  # type: ignore[attr-defined]
    logging.setLogRecordFactory(privacy_record_factory)


_install_privacy_record_factory()


class PrivacyRedactionFilter(logging.Filter):
    """Idempotent defense in depth for Yance-owned handlers."""

    def filter(self, record: logging.LogRecord) -> bool:
        _sanitize_record(record)
        return True


class PrivacyFormatter(logging.Formatter):
    """Formatter that never emits free-form exception tracebacks."""

    def formatException(self, exc_info: tuple[type[BaseException], BaseException, Any]) -> str:
        try:
            return f"<{exc_info[0].__name__}>"
        except Exception:
            return _REDACTION_FAILED

    def formatStack(self, stack_info: str) -> str:
        return _REDACTED

    def format(self, record: logging.LogRecord) -> str:
        try:
            return _sanitize_string(super().format(record))
        except Exception:
            safe_name = _sanitize_string(str(getattr(record, "name", "app")))
            safe_level = _sanitize_string(str(getattr(record, "levelname", "ERROR")))
            return f"{safe_name} - {safe_level} - {_REDACTION_FAILED}"


def _effective_level() -> int:
    environment = os.environ.get("ENVIRONMENT", "development").strip().lower()
    default_level = (
        logging.INFO
        if environment in _PRODUCTION_ENVIRONMENTS | _QUALIFICATION_ENVIRONMENTS
        else logging.DEBUG
    )

    requested = os.environ.get("LOG_LEVEL", "").strip().upper()
    candidate = getattr(logging, requested, None) if requested else default_level
    if not isinstance(candidate, int):
        candidate = default_level

    if environment in _PRODUCTION_ENVIRONMENTS and candidate < logging.INFO:
        return logging.INFO
    return candidate


def _resolve_log_file() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        log_dir = Path(local_app_data) / "Yance" / "logs"
    elif sys.platform.startswith("win"):
        raise RuntimeError("LOCALAPPDATA is required for Yance logging on Windows")
    else:
        state_home = os.environ.get("XDG_STATE_HOME")
        base = Path(state_home) if state_home else Path.home() / ".local" / "state"
        log_dir = base / "Yance" / "logs"

    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "app.log"


def _configure_logging() -> int:
    global _configured

    with _config_lock:
        _install_privacy_record_factory()
        if _configured:
            return logging.getLogger().level

        level = _effective_level()
        root_logger = logging.getLogger()

        for handler in list(root_logger.handlers):
            if getattr(handler, "_yance_application_handler", False):
                root_logger.removeHandler(handler)
                try:
                    handler.close()
                except Exception:
                    pass

        formatter = PrivacyFormatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        privacy_filter = PrivacyRedactionFilter()

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        console_handler.addFilter(privacy_filter)
        console_handler._yance_application_handler = True  # type: ignore[attr-defined]

        file_handler = RotatingFileHandler(
            _resolve_log_file(),
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        file_handler.addFilter(privacy_filter)
        file_handler._yance_application_handler = True  # type: ignore[attr-defined]

        root_logger.setLevel(level)
        root_logger.addHandler(console_handler)
        root_logger.addHandler(file_handler)

        for noisy_logger_name in ("sqlalchemy", "alembic", "urllib3", "httpx"):
            logging.getLogger(noisy_logger_name).setLevel(logging.WARNING)

        _configured = True
        return level


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a named stdlib logger routed through the single privacy-safe graph."""
    _configure_logging()

    logger = logging.getLogger(name or "app")
    logger.setLevel(logging.NOTSET)
    logger.propagate = True

    for handler in list(logger.handlers):
        if getattr(handler, "_yance_application_handler", False):
            logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass

    return logger
