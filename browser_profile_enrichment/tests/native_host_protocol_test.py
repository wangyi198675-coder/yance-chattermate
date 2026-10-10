from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
from pathlib import Path


COMPONENT = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[2]
HOST = COMPONENT / "native_host" / "yance_browser_profile_host.py"
BACKEND = REPO / "backend"
EXTENSION_ORIGIN = "chrome-extension://hfcmihknnigilcafmalchjopmhhkihjf/"


def invoke(origin: str, payload: dict | None):
    body = b""
    if payload is not None:
        encoded = json.dumps(payload).encode("utf-8")
        body = struct.pack("=I", len(encoded)) + encoded

    env = dict(os.environ)
    env["YANCE_BACKEND_ROOT"] = str(BACKEND)
    completed = subprocess.run(
        [sys.executable, str(HOST), origin],
        input=body,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        check=False,
    )
    assert completed.stderr == b""
    length = struct.unpack("=I", completed.stdout[:4])[0]
    response = json.loads(completed.stdout[4:4 + length].decode("utf-8"))
    return completed.returncode, response


def test_native_host_rejects_wrong_extension_origin_before_reading_payload():
    code, response = invoke("chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/", None)
    assert code == 2
    assert response == {"ok": False, "code": "CALLER_ORIGIN_REJECTED"}


def test_unknown_secret_field_is_rejected_before_database_import():
    payload = {
        "schema_version": 1,
        "binding_mode": "DIRECT_PROVIDER_USER",
        "page_account_id": "9",
        "thread_id": "123",
        "provider_user_id": "123",
        "display_name": "A",
        "avatar_url": None,
        "origin": "https://www.facebook.com",
        "page_kind": "facebook_messages",
        "access_token": "must-never-cross",
    }
    code, response = invoke(EXTENSION_ORIGIN, payload)
    assert code == 1
    assert response == {"ok": False, "code": "UNKNOWN_FIELDS"}


def test_native_host_never_reflects_payload_or_secret_value():
    secret = "VERY_SECRET_VALUE_SHOULD_NOT_ECHO"
    payload = {
        "schema_version": 1,
        "binding_mode": "DIRECT_PROVIDER_USER",
        "page_account_id": "9",
        "thread_id": "123",
        "provider_user_id": "123",
        "display_name": "A",
        "avatar_url": None,
        "origin": "https://www.facebook.com",
        "page_kind": "facebook_messages",
        "password": secret,
    }
    _, response = invoke(EXTENSION_ORIGIN, payload)
    assert secret not in json.dumps(response)
    assert "password" not in json.dumps(response)
