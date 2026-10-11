"""Synthetic Phase-1 OAuth/OIDC security contract tests. NO network/real tokens."""
import base64
import hashlib
import json
import time
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt

from app.core.siwc_protocol import (
    AUTHORIZATION_ENDPOINT, INITIAL_CLIENT_ID, ISSUER, PLAN_SCOPE, RESOURCE,
    SIWCError, authorization_code_form, authorization_url, consume_callback,
    create_host_id, new_attempt, refresh_form, revoke_form, validate_callback_uri,
    validate_host_id, validate_token_grant, verify_id_token,
)


def code_of(error):
    return error.value.code


@pytest.fixture
def host():
    return create_host_id()


@pytest.fixture
def attempt(host):
    return new_attempt(host, "http://127.0.0.1:1455/auth/callback")


def callback(attempt, **extra):
    values = {"state": attempt.state, "code": "SYNTHETIC-ONE-TIME-CODE",
              "client_id": "oaiapp_synthetic123"}
    values.update(extra)
    return attempt.redirect_uri + "?" + urlencode(values)


@pytest.fixture(scope="module")
def signing_key():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = key.public_key().public_numbers()
    def b64(v):
        return base64.urlsafe_b64encode(
            v.to_bytes((v.bit_length() + 7) // 8, "big")
        ).decode().rstrip("=")
    public = {"kty": "RSA", "kid": "key-A", "alg": "RS256",
              "use": "sig", "n": b64(numbers.n), "e": b64(numbers.e)}
    private = key.private_bytes(serialization.Encoding.PEM,
                                serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
    return private, {"keys": [public]}


def signed(signing_key, nonce, *, issuer=ISSUER, client="oaiapp_synthetic123",
           subject="subject-1", expiry=None, azp=None):
    private, _ = signing_key
    now = int(time.time())
    claims = {"iss": issuer, "aud": client, "sub": subject, "nonce": nonce,
              "iat": now, "exp": expiry if expiry is not None else now + 1200}
    if azp is not None:
        claims["azp"] = azp
    return jwt.encode(claims, private, algorithm="RS256", headers={"kid": "key-A"})


def test_host_id_uuid_v4_and_malformed(host):
    assert validate_host_id(host) == host
    assert host.startswith("urn:uuid:")
    assert create_host_id() != host
    for bad in ["S-1-123", "user@example.test", "urn:uuid:not-a-uuid",
                "urn:uuid:00000000-0000-1000-8000-000000000000"]:
        with pytest.raises(SIWCError):
            validate_host_id(bad)


@pytest.mark.parametrize("uri", [
    "http://localhost:1455/auth/callback", "http://0.0.0.0:1455/auth/callback",
    "http://127.0.0.2:1455/auth/callback", "https://127.0.0.1:1455/auth/callback",
    "http://127.0.0.1/auth/callback", "http://127.0.0.1:1455/callback",
    "http://127.0.0.1:0/auth/callback",
    "http://127.0.0.1:1455/auth/callback?foo=x",
    "http://evil@127.0.0.1:1455/auth/callback",
])
def test_only_exact_loopback(uri):
    with pytest.raises(SIWCError, match="invalid_loopback_callback"):
        validate_callback_uri(uri)


def test_initial_authorization_exact_pkce_fields(attempt):
    url = authorization_url(attempt)
    assert url.startswith(AUTHORIZATION_ENDPOINT + "?")
    query = parse_qs(urlsplit(url).query)
    assert query["client_id"] == [INITIAL_CLIENT_ID]
    assert query["agent_name_hint"] == ["Yance"]
    assert query["ext_agent_host_id"] == [attempt.host_id]
    assert query["response_type"] == ["code"]
    assert query["redirect_uri"] == [attempt.redirect_uri]
    assert PLAN_SCOPE in query["scope"][0]
    assert query["resource"] == [RESOURCE]
    assert query["code_challenge_method"] == ["S256"]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(attempt.verifier.encode()).digest()).rstrip(b"=").decode()
    assert query["code_challenge"] == [challenge]
    assert "SYNTHETIC" not in url
    assert "verifier" not in url


def test_returning_registration_uses_issued_client_and_no_agent_hint(host):
    attempt = new_attempt(host, "http://127.0.0.1:34567/auth/callback",
                          issued_client_id="oaiapp_synthetic123",
                          expected_subject="subject-1")
    q = parse_qs(urlsplit(authorization_url(attempt, login_hint="fake@example.test")).query)
    assert q["client_id"] == ["oaiapp_synthetic123"]
    assert "agent_name_hint" not in q
    assert q["login_hint"] == ["fake@example.test"]
    assert consume_callback(attempt, attempt.redirect_uri + "?" +
                            urlencode({"state": attempt.state, "code": "test"})).client_id == "oaiapp_synthetic123"


def test_first_callback_and_form_use_issued_id_not_dynamic(attempt):
    grant = consume_callback(attempt, callback(attempt))
    data = authorization_code_form(attempt, grant)
    assert data == {
        "grant_type": "authorization_code", "client_id": "oaiapp_synthetic123",
        "code": "SYNTHETIC-ONE-TIME-CODE",
        "code_verifier": attempt.verifier, "redirect_uri": attempt.redirect_uri,
        "resource": RESOURCE,
    }
    assert grant.code not in repr(grant)
    assert attempt.verifier not in repr(attempt)


def test_cross_session_callbacks_are_rejected(host):
    a = new_attempt(host, "http://127.0.0.1:1455/auth/callback")
    b = new_attempt(host, "http://127.0.0.1:1455/auth/callback")
    assert a.state != b.state and a.nonce != b.nonce and a.verifier != b.verifier
    with pytest.raises(SIWCError, match="state_mismatch"):
        consume_callback(a, callback(b))
    assert a.consumed
    with pytest.raises(SIWCError, match="attempt_consumed"):
        consume_callback(a, callback(a))


@pytest.mark.parametrize("override,code", [
    ({"client_id": ""}, "invalid_issued_client_id"),
    ({"client_id": "dynamic_agent_client"}, "invalid_issued_client_id"),
    ({"code": ""}, "missing_authorization_code"),
    ({"state": "wrong"}, "state_mismatch"),
    ({"error": "access_denied", "code": ""}, "authorization_denied"),
])
def test_registration_failure_closes_attempt(attempt, override, code):
    with pytest.raises(SIWCError) as exc:
        consume_callback(attempt, callback(attempt, **override))
    assert code_of(exc) == code
    assert attempt.consumed


def test_callback_exact_port_path_and_duplicate_state(attempt):
    url = callback(attempt)
    with pytest.raises(SIWCError, match="callback_uri_mismatch"):
        consume_callback(attempt, url.replace(":1455/", ":1456/"))
    other = new_attempt(attempt.host_id, attempt.redirect_uri)
    with pytest.raises(SIWCError, match="callback_parameters_invalid"):
        consume_callback(other, callback(other) + "&state=" + other.state)


def test_callback_expiry(host):
    a = new_attempt(host, "http://127.0.0.1:1455/auth/callback", now=10)
    with pytest.raises(SIWCError, match="attempt_expired"):
        consume_callback(a, callback(a), now=311)


def test_issued_client_mismatch_on_returning_account(host):
    a = new_attempt(host, "http://127.0.0.1:1455/auth/callback",
                    issued_client_id="oaiapp_old")
    with pytest.raises(SIWCError, match="client_id_mismatch"):
        consume_callback(a, callback(a, client_id="oaiapp_new"))


def test_id_token_signature_and_claims(signing_key, attempt):
    encoded = signed(signing_key, attempt.nonce)
    verified = verify_id_token(encoded, signing_key[1],
                               issued_client_id="oaiapp_synthetic123",
                               nonce=attempt.nonce)
    assert verified.subject == "subject-1"
    assert verified.client_id == "oaiapp_synthetic123"


@pytest.mark.parametrize("change", [
    "nonce", "issuer", "audience", "subject", "expiry", "signature", "key",
])
def test_id_token_tampering_fail_closed(signing_key, attempt, change):
    kwargs = {}
    nonce = attempt.nonce
    expected_subject = "subject-1"
    key = signing_key[1]
    if change == "nonce": nonce = "mismatch"
    if change == "issuer": kwargs["issuer"] = "https://evil.example"
    if change == "audience": kwargs["client"] = "oaiapp_wrong"
    if change == "subject": expected_subject = "subject-other"
    if change == "expiry": kwargs["expiry"] = int(time.time()) - 500
    value = signed(signing_key, nonce, **kwargs)
    if change == "signature": value = value[:-2] + ("aa" if value[-2:] != "aa" else "bb")
    if change == "key": key = {"keys": []}
    with pytest.raises(SIWCError):
        verify_id_token(value, key, issued_client_id="oaiapp_synthetic123",
                        nonce=attempt.nonce, expected_subject=expected_subject)


def test_id_token_rejects_alg_none(signing_key, attempt):
    def b64(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")
    bad = b64({"alg": "none", "kid": "key-A"}) + "." + b64({"iss": ISSUER, "sub": "subject-1"}) + "."
    with pytest.raises(SIWCError):
        verify_id_token(bad, signing_key[1],
                        issued_client_id="oaiapp_synthetic123", nonce=attempt.nonce)


def test_plan_scope_from_token_endpoint_only(signing_key, attempt):
    identity = verify_id_token(signed(signing_key, attempt.nonce),
                               signing_key[1], issued_client_id="oaiapp_synthetic123",
                               nonce=attempt.nonce)
    def response(scope):
        return {"scope": scope, "token_type": "Bearer",
                "access_token": "fake-access-token-never-use",
                "expires_in": 3600}
    assert validate_token_grant(response("openid profile"), identity).state == "identity_only"
    assert validate_token_grant(response("openid " + PLAN_SCOPE), identity).state == "identity_only"
    assert validate_token_grant(response("openid resource.invoke " + PLAN_SCOPE),
                                identity).state == "plan_authorized_unverified"
    with pytest.raises(SIWCError):
        validate_token_grant(response(PLAN_SCOPE), identity)


def test_refresh_and_revoke_use_issued_client_only():
    data = refresh_form("oaiapp_synthetic123", "FAKE-ROTATING-REFRESH")
    assert data["grant_type"] == "refresh_token"
    assert data["resource"] == RESOURCE
    assert revoke_form("oaiapp_synthetic123", "FAKE-ROTATING-REFRESH")["token_type_hint"] == "refresh_token"
    with pytest.raises(SIWCError):
        refresh_form("dynamic_agent_client", "FAKE")
    with pytest.raises(SIWCError):
        refresh_form("oaiapp_synthetic123", "")


def test_grant_bound_to_exact_attempt_and_exchanged_once(host):
    from app.core.siwc_protocol import authorization_code_form
    first = new_attempt(host, "http://127.0.0.1:1455/auth/callback")
    second = new_attempt(host, "http://127.0.0.1:1455/auth/callback")
    one = consume_callback(first, callback(first))
    two = consume_callback(second, callback(second))
    with pytest.raises(SIWCError, match="unvalidated_callback"):
        authorization_code_form(first, two)
    assert authorization_code_form(first, one)["client_id"] == "oaiapp_synthetic123"
    with pytest.raises(SIWCError, match="unvalidated_callback"):
        authorization_code_form(first, one)


def test_explicit_empty_issued_client_must_not_re_register(host):
    with pytest.raises(SIWCError, match="invalid_issued_client_id"):
        new_attempt(host, "http://127.0.0.1:1455/auth/callback", issued_client_id="")


def test_refresh_rotation_contract_requires_atomic_compare_and_swap():
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from app.core.siwc_protocol import enforce_atomic_refresh_rotation
    class SyntheticCAS:
        def __init__(self):
            self.version = 7
            self.data = b"FAKE-protected-data"
            self.lock = threading.Lock()
        def replace_bundle_if_version(self, account_ref, expected_version, encrypted_bundle):
            with self.lock:
                if self.version != expected_version:
                    return False
                self.version += 1
                self.data = encrypted_bundle
                return True
    store = SyntheticCAS()
    def rotate(number):
        try:
            enforce_atomic_refresh_rotation(store, "fake-account", 7, b"FAKE-new-cipher" + bytes([number]))
            return "ok"
        except SIWCError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(rotate, [1, 2]))
    assert sorted(results) == ["ok", "stale_refresh_rotation"]
    assert store.version == 8
    assert store.data.startswith(b"FAKE-new-cipher")
    for args in [("", 8, b"FAKE"), ("fake-account", -1, b"FAKE"),
                 ("fake-account", 8, b"")]:
        with pytest.raises(SIWCError, match="refresh_rotation_invalid"):
            enforce_atomic_refresh_rotation(store, *args)


# W378 P0-1: real RSA-signed ID Tokens, not unsigned fake payloads.
@pytest.mark.parametrize("audience,authorized_party,allowed", [
    ("oaiapp_synthetic123", None, True),
    (["oaiapp_synthetic123"], None, True),
    ("oaiapp_synthetic123", "oaiapp_synthetic123", True),
    (["oaiapp_synthetic123"], "oaiapp_synthetic123", True),
    (["oaiapp_synthetic123", "oaiapp_evil"], None, False),
    (["oaiapp_synthetic123", "oaiapp_evil"], "oaiapp_evil", False),
    (["oaiapp_synthetic123", "oaiapp_evil"], "oaiapp_synthetic123", False),
    ("oaiapp_synthetic123", "oaiapp_evil", False),
    (["oaiapp_evil"], "oaiapp_synthetic123", False),
])
def test_signed_oidc_audience_azp_strict_fail_closed(signing_key, attempt, audience, authorized_party, allowed):
    token = signed(signing_key, attempt.nonce, client=audience, azp=authorized_party)
    if allowed:
        result = verify_id_token(token, signing_key[1],
                                 issued_client_id="oaiapp_synthetic123", nonce=attempt.nonce)
        assert result.subject == "subject-1"
    else:
        with pytest.raises(SIWCError):
            verify_id_token(token, signing_key[1],
                            issued_client_id="oaiapp_synthetic123", nonce=attempt.nonce)


@pytest.mark.parametrize("malicious_state", [
    "测试", "føø", "ab" + "\u2603" * 40, "a" * 5000, "",
    "a" * 42 + "!", "a" * 40 + "\x00",
])
def test_nonascii_and_malformed_callback_state_safe_error(host, malicious_state):
    attempt = new_attempt(host, "http://127.0.0.1:1455/auth/callback")
    # urlencode encodes arbitrary Unicode and control characters, as a browser does.
    url = callback(attempt, state=malicious_state)
    with pytest.raises(SIWCError) as exc:
        consume_callback(attempt, url)
    assert exc.value.code == "state_mismatch"
    assert attempt.consumed
    assert "SYNTHETIC-ONE-TIME-CODE" not in str(exc.value)


def test_callback_oversized_or_non_string_closes_safely(host):
    for invalid in (None, 1, "x" * 16385):
        attempt = new_attempt(host, "http://127.0.0.1:1455/auth/callback")
        with pytest.raises(SIWCError, match="callback_parameters_invalid"):
            consume_callback(attempt, invalid)
        assert attempt.consumed
