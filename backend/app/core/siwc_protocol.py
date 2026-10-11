"""Official Sign in with ChatGPT plan-sharing protocol helpers.

PHASE 1 CONTRACT ONLY: no listener, browser launch, HTTP egress, account store,
or API-key fallback. The later native ChatterMate owner must supply these.
See https://developers.openai.com/siwc/token-sharing-open-source/sign-in
"""
from __future__ import annotations

import base64
import hashlib
import re
import secrets
import time
from dataclasses import dataclass, field
from typing import Mapping, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID, uuid4

from jose import jwt
from jose.exceptions import JOSEError

ISSUER = "https://auth.openai.com"
AUTHORIZATION_ENDPOINT = ISSUER + "/api/accounts/authorize"
TOKEN_ENDPOINT = ISSUER + "/api/accounts/oauth/token"
RESOURCE = "https://api.openai.com/v1"
INITIAL_CLIENT_ID = "dynamic_agent_client"
PLAN_SCOPE = "chatgpt.tokens.use.direct"
SCOPES = "openid profile email offline_access resource.invoke " + PLAN_SCOPE
CALLBACK_PATH = "/auth/callback"
AUTH_TTL_SECONDS = 300
_ALPHANUM = re.compile(r"^[a-zA-Z0-9_.:-]{1,256}$")


class SIWCError(Exception):
    """Safe, non-secret error code suitable for native product error mapping."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def create_host_id() -> str:
    """Caller persists once through the later approved Windows credential owner."""
    return "urn:uuid:" + str(uuid4())


def validate_host_id(host_id: str) -> str:
    try:
        if not isinstance(host_id, str) or not host_id.startswith("urn:uuid:"):
            raise ValueError()
        value = UUID(host_id[9:])
        if value.version != 4 or host_id != "urn:uuid:" + str(value):
            raise ValueError()
        return host_id
    except (ValueError, TypeError, AttributeError) as exc:
        raise SIWCError("invalid_host_id") from exc


def validate_callback_uri(uri: str) -> str:
    """An already bound 127.0.0.1 listener must supply the exact callback URI."""
    try:
        value = urlsplit(uri)
        port = value.port
        valid = (
            value.scheme == "http"
            and value.netloc == f"127.0.0.1:{port}"
            and port is not None and 1 <= port <= 65535
            and value.path == CALLBACK_PATH
            and not value.query and not value.fragment
            and not value.username and not value.password
        )
    except (ValueError, AttributeError, TypeError):
        valid = False
    if not valid:
        raise SIWCError("invalid_loopback_callback")
    return uri


def _issued_client(value: str) -> str:
    if (not isinstance(value, str) or value == INITIAL_CLIENT_ID
            or not value.startswith("oaiapp_") or not _ALPHANUM.fullmatch(value)):
        raise SIWCError("invalid_issued_client_id")
    return value


@dataclass
class AuthorizationAttempt:
    """Ephemeral, single-use transaction; must never be stored in AIConfig.

    This is not an OAuth server. The future native owner starts a loopback listener
    *before* constructing the browser URL, and serializes each callback to one
    transaction. Failure consumes the attempt too (anti-replay).
    """

    host_id: str
    redirect_uri: str
    client_id: str
    state: str = field(repr=False)
    nonce: str = field(repr=False)
    verifier: str = field(repr=False)
    deadline: float = field(repr=False)
    expected_subject: str | None = field(default=None, repr=False)
    consumed: bool = False
    exchanged: bool = False
    accepted_grant: CallbackGrant | None = field(default=None, repr=False)


def new_attempt(
    host_id: str,
    redirect_uri: str,
    *,
    issued_client_id: str | None = None,
    expected_subject: str | None = None,
    now: float | None = None,
) -> AuthorizationAttempt:
    validate_host_id(host_id)
    validate_callback_uri(redirect_uri)
    if issued_client_id is not None:
        _issued_client(issued_client_id)
    if expected_subject is not None and (not isinstance(expected_subject, str)
                                          or not expected_subject.strip()):
        raise SIWCError("invalid_expected_subject")
    clock = time.time() if now is None else now
    return AuthorizationAttempt(
        host_id=host_id, redirect_uri=redirect_uri,
        client_id=issued_client_id or INITIAL_CLIENT_ID,
        state=secrets.token_urlsafe(32),
        nonce=secrets.token_urlsafe(32),
        verifier=secrets.token_urlsafe(64),
        deadline=clock + AUTH_TTL_SECONDS,
        expected_subject=expected_subject,
    )


def authorization_url(
    attempt: AuthorizationAttempt, *,
    agent_name: str = "Yance",
    id_token_hint: str | None = None,
    login_hint: str | None = None,
) -> str:
    if attempt.consumed:
        raise SIWCError("attempt_consumed")
    if not 1 <= len(agent_name.strip()) <= 80:
        raise SIWCError("invalid_agent_name")
    values = {
        "client_id": attempt.client_id,
        "ext_agent_host_id": attempt.host_id,
        "response_type": "code",
        "redirect_uri": attempt.redirect_uri,
        "scope": SCOPES,
        "resource": RESOURCE,
        "state": attempt.state,
        "nonce": attempt.nonce,
        "code_challenge_method": "S256",
        "code_challenge": base64.urlsafe_b64encode(
            hashlib.sha256(attempt.verifier.encode("ascii")).digest()
        ).rstrip(b"=").decode("ascii"),
    }
    if attempt.client_id == INITIAL_CLIENT_ID:
        values["agent_name_hint"] = agent_name
        if id_token_hint or login_hint:
            raise SIWCError("initial_registration_hints_forbidden")
    else:
        if id_token_hint:
            values["id_token_hint"] = id_token_hint
        if login_hint:
            values["login_hint"] = login_hint
    return AUTHORIZATION_ENDPOINT + "?" + urlencode(values)


@dataclass(frozen=True)
class CallbackGrant:
    client_id: str
    code: str = field(repr=False)


def consume_callback(
    attempt: AuthorizationAttempt, callback_uri: str, *,
    now: float | None = None,
) -> CallbackGrant:
    """Match scheme/host/port/path and state, reject duplicates, then consume.

    The listener must reject remote connections independently. Never log the
    callback URL: it contains a one-use authorization code.
    """
    if attempt.consumed:
        raise SIWCError("attempt_consumed")
    attempt.consumed = True
    # Callback data is untrusted; fail closed before URL parsing or comparison.
    if not isinstance(callback_uri, str) or len(callback_uri) > 16384:
        raise SIWCError("callback_parameters_invalid")
    if (time.time() if now is None else now) > attempt.deadline:
        raise SIWCError("attempt_expired")
    try:
        url = urlsplit(callback_uri)
        base = urlunsplit((url.scheme, url.netloc, url.path, "", ""))
        if base != attempt.redirect_uri or url.fragment:
            raise SIWCError("callback_uri_mismatch")
        pairs = parse_qsl(url.query, keep_blank_values=True, strict_parsing=True)
        if len(pairs) > 12 or len(set(k for k, _ in pairs)) != len(pairs):
            raise SIWCError("callback_parameters_invalid")
        params = dict(pairs)
    except (ValueError, TypeError) as exc:
        raise SIWCError("callback_parameters_invalid") from exc
    callback_state = params.get("state", "")
    if (not isinstance(callback_state, str)
            or re.fullmatch(r"[A-Za-z0-9_-]{40,128}", callback_state, flags=re.ASCII) is None):
        raise SIWCError("state_mismatch")
    if not secrets.compare_digest(callback_state.encode("ascii"), attempt.state.encode("ascii")):
        raise SIWCError("state_mismatch")
    if params.get("error"):
        raise SIWCError("authorization_denied")
    code = params.get("code", "")
    if not code or len(code) > 8192:
        raise SIWCError("missing_authorization_code")
    returned_client = params.get("client_id")
    if attempt.client_id == INITIAL_CLIENT_ID:
        issued = _issued_client(returned_client)
    else:
        if returned_client is not None and returned_client != attempt.client_id:
            raise SIWCError("client_id_mismatch")
        issued = attempt.client_id
    grant = CallbackGrant(issued, code)
    attempt.accepted_grant = grant
    return grant


def authorization_code_form(attempt: AuthorizationAttempt, grant: CallbackGrant) -> dict[str, str]:
    """Call only after consuming the exact pending callback; form body is SECRET."""
    if not attempt.consumed or grant is not attempt.accepted_grant or attempt.exchanged:
        raise SIWCError("unvalidated_callback")
    attempt.exchanged = True
    if attempt.client_id != INITIAL_CLIENT_ID and grant.client_id != attempt.client_id:
        raise SIWCError("client_id_mismatch")
    return {
        "grant_type": "authorization_code",
        "client_id": _issued_client(grant.client_id),
        "code": grant.code,
        "code_verifier": attempt.verifier,
        "redirect_uri": attempt.redirect_uri,
        "resource": RESOURCE,
    }


def refresh_form(client_id: str, refresh_token: str) -> dict[str, str]:
    if not isinstance(refresh_token, str) or not refresh_token:
        raise SIWCError("missing_refresh_token")
    return {
        "grant_type": "refresh_token",
        "client_id": _issued_client(client_id),
        "refresh_token": refresh_token,
        "resource": RESOURCE,
    }


def revoke_form(client_id: str, refresh_token: str) -> dict[str, str]:
    _issued_client(client_id)
    if not isinstance(refresh_token, str) or not refresh_token:
        raise SIWCError("missing_refresh_token")
    return {"client_id": client_id, "token": refresh_token, "token_type_hint": "refresh_token"}


@dataclass(frozen=True)
class VerifiedIdentity:
    subject: str
    client_id: str
    issuer: str = ISSUER


def verify_id_token(
    encoded: str,
    jwks: Mapping[str, object],
    *,
    issued_client_id: str,
    nonce: str,
    expected_subject: str | None = None,
    now: float | None = None,
) -> VerifiedIdentity:
    """Actual OIDC signature/iss/aud/exp/nonce checks; no unverified claims trusted."""
    client_id = _issued_client(issued_client_id)
    if not isinstance(encoded, str) or not 0 < len(encoded) <= 32768 or not nonce or not isinstance(jwks, Mapping):
        raise SIWCError("id_token_invalid")
    try:
        header = jwt.get_unverified_header(encoded)
        if header.get("alg") not in ("RS256", "ES256") or not header.get("kid"):
            raise SIWCError("id_token_untrusted_algorithm")
        keys = jwks.get("keys")
        if not isinstance(keys, list):
            raise SIWCError("jwks_invalid")
        matches = [key for key in keys if isinstance(key, dict)
                   and key.get("kid") == header["kid"]
                   and key.get("alg", header["alg"]) == header["alg"]
                   and key.get("use", "sig") == "sig"]
        if len(matches) != 1:
            raise SIWCError("id_token_unknown_key")
        # jose validates the signature before any identity data is accepted.
        claims = jwt.decode(
            encoded, matches[0], algorithms=[header["alg"]],
            audience=client_id, issuer=ISSUER,
            options={"require_exp": True, "require_iat": True, "require_sub": True},
        )
        # An issued per-user client is the ONLY trusted audience at Phase 1.
        # OIDC permits aud arrays, but we have no trusted auxiliary resources:
        # fail closed on every extra audience even with a valid signature/azp.
        audience = claims.get("aud")
        if isinstance(audience, str):
            valid_audience = audience == client_id
        elif isinstance(audience, list):
            valid_audience = len(audience) == 1 and audience[0] == client_id
        else:
            valid_audience = False
        if not valid_audience:
            raise SIWCError("id_token_untrusted_audience")
        azp = claims.get("azp")
        if azp is not None and (not isinstance(azp, str) or azp != client_id):
            raise SIWCError("id_token_azp_mismatch")
        if now is not None:
            if (not isinstance(claims.get("exp"), (int, float))
                    or claims["exp"] <= now
                    or claims.get("iat", 0) > now + 60):
                raise SIWCError("id_token_expired")
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject.strip():
            raise SIWCError("id_token_subject_invalid")
        if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
            raise SIWCError("nonce_mismatch")
        if expected_subject is not None and not secrets.compare_digest(subject, expected_subject):
            raise SIWCError("account_switch_mismatch")
        return VerifiedIdentity(subject=subject, client_id=client_id)
    except SIWCError:
        raise
    except (JOSEError, ValueError, TypeError, KeyError) as exc:
        raise SIWCError("id_token_invalid") from exc


@dataclass(frozen=True)
class GrantedAuthorization:
    identity: VerifiedIdentity
    scopes: frozenset[str]
    state: str  # identity_only | plan_authorized_unverified
    expires_in: int


def validate_token_grant(
    token_response: Mapping[str, object],
    identity: VerifiedIdentity,
) -> GrantedAuthorization:
    """Only the token endpoint's scope can grant plan inference, never callbacks."""
    if not isinstance(token_response, Mapping):
        raise SIWCError("token_response_invalid")
    value = token_response.get("scope", "")
    scopes = frozenset(value.split()) if isinstance(value, str) else frozenset()
    expiry = token_response.get("expires_in")
    if (not isinstance(token_response.get("token_type"), str)
            or token_response["token_type"].lower() != "bearer"
            or not isinstance(expiry, int) or not 0 < expiry <= 86400
            or not isinstance(token_response.get("access_token"), str)
            or not token_response["access_token"]
            or "openid" not in scopes):
        raise SIWCError("token_response_invalid")
    state = "plan_authorized_unverified" if PLAN_SCOPE in scopes and "resource.invoke" in scopes else "identity_only"
    return GrantedAuthorization(identity, scopes, state, expiry)


class ProtectedCredentialStore(Protocol):
    """Phase-2-only interface; MUST be implemented by W327-approved OS custody.

    A refresh uses one account-specific lock and compare-and-swap; the entire
    access/refresh/id-token bundle is replaced atomically by the secure store,
    never one token at a time. A CAS failure invalidates this refresh result.
    """

    def replace_bundle_if_version(
        self, account_ref: str, expected_version: int, encrypted_bundle: bytes
    ) -> bool: ...

def enforce_atomic_refresh_rotation(
    store: ProtectedCredentialStore,
    account_ref: str,
    expected_version: int,
    protected_bundle: bytes,
) -> None:
    """CAS gate only; never writes unprotected secrets or supplies a disk store.

    The later OS credential owner implements single-flight locking, sealing and
    durable atomic CAS. Failure MUST stop inference and request reconciliation;
    never retry using an already-rotated refresh token or a paid API key.
    """
    if (not isinstance(account_ref, str) or not account_ref.strip()
            or not isinstance(expected_version, int) or expected_version < 0
            or not isinstance(protected_bundle, bytes) or not protected_bundle):
        raise SIWCError("refresh_rotation_invalid")
    if not store.replace_bundle_if_version(account_ref, expected_version, protected_bundle):
        raise SIWCError("stale_refresh_rotation")
