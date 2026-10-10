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

import json
import secrets
import time
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.channels.accounts import get_org_account_or_404, to_account_out
from app.channels.meta_base import (
    debug_token,
    exchange_for_long_lived_token,
    exchange_instagram_code,
    exchange_instagram_long_lived,
    exchange_signup_code,
    graph_get,
    graph_detail,
    graph_list_all,
    instagram_token_payload,
    register_phone_number,
    subscribe_app,
    subscribe_instagram_app,
    GRAPH_INSTAGRAM_BASE,
)
from app.core.security import decrypt_api_key, encrypt_api_key
from app.core.auth import (
    get_current_organization,
    require_permissions,
)
from app.core.config import settings
from app.database import get_db
from app.models.channels import ChannelType
from app.models.organization import Organization
from app.models.schemas.channel import (
    ChannelAccountOut,
    EmbeddedSignupConfigOut,
    EmbeddedSignupRequest,
    WhatsAppConnectRequest,
    WhatsAppCredentialRotationRequest,
    MessengerConnectRequest,
    MessengerSignupConnectRequest,
    MessengerSignupPagesOut,
    MessengerSignupRequest,
    MessengerPageOut,
    InstagramConnectRequest,
    InstagramLoginRequest,
)
from app.models.user import User
from app.repositories.channels import ChannelAccountRepository
from app.core.logger import get_logger

router = APIRouter()
logger = get_logger(__name__)

def _whatsapp_display_name(profile: dict, phone_number_id: str) -> str:
    """How a connected number is labelled in the UI, from its Graph profile."""
    return (f"{profile.get('verified_name', 'WhatsApp')} "
            f"({profile.get('display_phone_number', phone_number_id)})")


async def _page_name(page_id: str, access_token: str) -> str:
    """The Page's name for the UI label, falling back to its id.

    Reading it needs pages_read_engagement, which messaging does not require —
    so a token without it still connects and simply shows the id.
    """
    ok, data = await graph_get(page_id, access_token, params={"fields": "name"})
    if not ok or not data.get("name"):
        logger.info(f"No name for page {page_id} (pages_read_engagement not granted); "
                    f"labelling with the id")
        return page_id
    return data["name"]


async def _verify_signup_assets(waba_id: str, phone_number_id: str, access_token: str) -> dict:
    """Prove the exchanged token really owns the number being claimed, and
    return that number's profile.

    The code only proves the caller completed *a* signup — waba_id and
    phone_number_id arrive in the request body and are entirely caller
    controlled. Without this, an org could pair a genuine code from a throwaway
    WABA with someone else's phone number id: webhook routing resolves accounts
    by phone number id alone, with no org scoping, so their inbound messages
    would land in the attacker's inbox. Listing the WABA's numbers with the
    token checks both ids at once.
    """
    ok, data = await graph_get(f"{waba_id}/phone_numbers", access_token,
                               params={"fields": "id,display_phone_number,verified_name"})
    if not ok:
        raise HTTPException(
            status_code=400,
            detail=graph_detail(data, "Could not read that WhatsApp Business Account"))

    numbers = data.get("data")
    if not isinstance(numbers, list):
        raise HTTPException(status_code=400, detail="Unexpected response from Meta")

    for number in numbers:
        if str(number.get("id")) == phone_number_id:
            return number
    raise HTTPException(status_code=400,
                        detail="That number is not on this WhatsApp Business Account")


def _generate_verification_pin() -> str:
    """A fresh two-step-verification PIN for a number we register.

    The customer never types it — it exists only so the number can be
    registered — so it is random rather than chosen, and kept for re-registers.
    """
    return f"{secrets.randbelow(1_000_000):06d}"


# Channels that can be onboarded through a Meta login popup, each with the Meta
# configuration that drives it. WhatsApp and Messenger run Facebook logins;
# Instagram runs Instagram Login, which needs no Facebook Page at all.
SIGNUP_CHANNELS = (
    ChannelType.WHATSAPP.value,
    ChannelType.MESSENGER.value,
    ChannelType.INSTAGRAM.value,
)

# Webhook fields a Page must subscribe our app to for Messenger to work.
MESSENGER_SUBSCRIBED_FIELDS = "messages,messaging_postbacks"


def _signup_config_id(channel: str) -> str:
    """The Facebook Login-for-Business configuration that onboards this channel,
    read at call time so a settings override (tests, reloads) is always seen.

    Instagram Login has no configuration — it is gated on its own app id.
    """
    return {
        ChannelType.WHATSAPP.value: settings.META_CONFIG_ID,
        ChannelType.MESSENGER.value: settings.META_MESSENGER_CONFIG_ID,
    }.get(channel, "")


def _signup_app_id(channel: str) -> str:
    """The app the login popup authenticates against. Instagram Login uses the
    Instagram app; the Facebook flows use the Meta app."""
    if channel == ChannelType.INSTAGRAM.value:
        return settings.INSTAGRAM_APP_ID
    return settings.META_APP_ID


def _signup_available(channel: str) -> bool:
    """Whether this deployment can offer the login flow for this channel.

    Onboarding happens under *our* app, so without its credentials it
    structurally cannot work — a self-hoster has none and gets the manual
    credentials form instead. That is the whole gate: like every other
    integration, signup is not restricted by plan.
    """
    if channel == ChannelType.INSTAGRAM.value:
        return bool(settings.INSTAGRAM_APP_ID and settings.INSTAGRAM_APP_SECRET)
    return bool(_signup_config_id(channel))


def _signup_allowed_for(user: User) -> bool:
    """Whether this account may use one-click signup.

    An empty allowlist means everyone, which is the end state. While the Meta
    app is in App Review the login only succeeds for people with a role on that
    app, so the allowlist keeps the button off everyone it would only fail for.
    Read at call time so the list can be changed without a code deploy.
    """
    allowed = {email.strip().lower()
               for email in settings.SIGNUP_ALLOWED_EMAILS.split(",")
               if email.strip()}
    return not allowed or (user.email or "").strip().lower() in allowed


def check_signup_access(channel: str, user: User) -> None:
    if not _signup_available(channel):
        raise HTTPException(
            status_code=403,
            detail="Signup is not configured on this deployment for this channel. "
                   "Connect with credentials instead.",
        )
    # Separate from the deployment gate so the reason is honest: the flow exists
    # here, this account just isn't one of the ones it is open to yet.
    if not _signup_allowed_for(user):
        raise HTTPException(
            status_code=403,
            detail="One-click connect is limited to selected accounts on this "
                   "deployment. Connect with credentials instead.",
        )


# The signup code is single-use and lives ~10 minutes; the sealed page list it
# produces should not outlive it, so a stale one fails cleanly with a retry.
SIGNUP_TOKEN_TTL_SECONDS = 600
# 500 Pages; an agency ceiling, not a limit a real customer reaches.
PAGE_LIST_MAX_PAGES = 5


def _seal_signup_pages(organization_id, pages: list[dict]) -> str:
    """Carry a signup's Page tokens through the picker without the browser ever
    holding them in the clear.

    The tokens go back to the client as ciphertext only we can open, so step 2
    needs no server-side session — which matters because the two requests are
    not guaranteed to hit the same worker. Binding the org and an expiry inside
    means a leaked blob cannot be replayed by another tenant, or after the
    signup's own code would already have died.
    """
    payload = {
        "org": str(organization_id),
        "exp": int(time.time()) + SIGNUP_TOKEN_TTL_SECONDS,
        "pages": pages,
    }
    return encrypt_api_key(json.dumps(payload))


def _open_signup_pages(signup_token: str, organization: Organization) -> list[dict]:
    """The sealed page list, or 400 if it is forged, expired or another org's.

    One generic message across every reject path, so it is not an oracle for
    which check tripped.
    """
    invalid = HTTPException(status_code=400,
                            detail="That signup has expired — please connect again")
    try:
        # decrypt raises ValueError on a bad token; json.loads raises
        # JSONDecodeError, a ValueError subclass — one except covers both.
        payload = json.loads(decrypt_api_key(signup_token))
    except ValueError:
        raise invalid
    if not isinstance(payload, dict) or payload.get("org") != str(organization.id):
        raise invalid
    if float(payload.get("exp", 0)) <= time.time():
        raise invalid
    pages = payload.get("pages")
    if not isinstance(pages, list):
        raise invalid
    return pages


async def _list_manageable_pages(user_token: str, fields: str) -> list[dict]:
    """The Pages this signup granted us, each with its own Page access token."""
    ok, data = await graph_list_all(
        "me/accounts", user_token, {"fields": fields, "limit": 100},
        max_pages=PAGE_LIST_MAX_PAGES)
    if not ok:
        raise HTTPException(
            status_code=400,
            detail=graph_detail(data, "Could not list your Facebook Pages"))
    return data


async def _signup_user_token(request: MessengerSignupRequest) -> str:
    """Trade a Facebook Login-for-Business code for a long-lived user token.

    Page tokens inherit the user token's lifetime, so it is extended first
    (best-effort; a failure only risks earlier expiry). Instagram does not come
    through here — Instagram Login is its own OAuth against its own host.
    """
    ok, data = await exchange_signup_code(request.code, redirect_uri=request.redirect_uri)
    user_token = data.get("access_token") if ok else None
    if not user_token:
        # The code is short-lived (~10 minutes) and single-use, so a stale or
        # replayed one lands here rather than on a Graph error later.
        raise HTTPException(status_code=400, detail=graph_detail(
            data, "Could not complete signup — please try connecting again"))

    ok, extended = await exchange_for_long_lived_token(user_token)
    if ok and extended.get("access_token"):
        return extended["access_token"]
    logger.warning("Could not extend the signup token; page tokens may expire early")
    return user_token


def _upsert_account(db: Session, organization: Organization, channel_type: str,
                    external_account_id: str, credentials: dict, display_name: str,
                    *, activate: bool = True):
    """Create the account or refresh credentials on reconnect (same org only)."""
    repo = ChannelAccountRepository(db)
    existing = repo.get_by_external_id(channel_type, external_account_id)
    if existing is not None:
        if existing.organization_id != organization.id:
            raise HTTPException(status_code=409,
                                detail="This account is already connected to another organization")
        # Merge rather than replace: a reconnect that omits an optional field
        # must not silently drop it. Someone reconnecting without re-entering
        # their WABA id would otherwise lose template management, and the
        # signup PIN cannot be read back from Meta at all.
        # Reconnect is unavailable to ingress/egress before credentials are
        # rotated or any subscription request is sent. Do this first, not as
        # a compensation after a failed provider call.
        if not activate:
            repo.set_active(existing, False)
        merged = {**repo.get_credentials(existing),
                  **{k: v for k, v in credentials.items() if v is not None}}
        repo.update_credentials(existing, merged)
        if display_name:
            existing.display_name = display_name
            db.commit()
            db.refresh(existing)
        return repo.set_active(existing, True) if activate else existing
    account = repo.create_account(
        organization_id=organization.id,
        channel_type=channel_type,
        external_account_id=external_account_id,
        credentials=credentials,
        display_name=display_name,
        is_active=activate,
    )
    return account


async def _finish_messenger_subscription(
    db: Session,
    account,
    *,
    page_id: str,
    access_token: str,
):
    """Require Page webhook subscription before Messenger is reported connected."""
    try:
        subscribed = await subscribe_app(
            page_id,
            access_token,
            subscribed_fields=MESSENGER_SUBSCRIBED_FIELDS,
        )
    except Exception:
        logger.warning("Messenger Page webhook subscription was not confirmed for %s", page_id)
        subscribed = False
    if subscribed:
        return ChannelAccountRepository(db).set_active(account, True)

    # The Page was staged inactive before the provider call. Never make it
    # observable as active when Meta has not confirmed the subscription.
    raise HTTPException(
        status_code=424,
        detail=(
            "Facebook did not confirm webhook subscription for this Page. "
            "Reconnect this Facebook Page and try again."
        ),
    )


async def _validate_whatsapp_credentials(phone_number_id: str, access_token: str,
                                         waba_id: str | None = None) -> dict:
    """Validate a token against the exact phone and, when known, its WABA.

    Callers must do this before replacing encrypted_credentials. This is the
    credential-rotation gate: an invalid token never overwrites a working one.
    """
    ok, profile = await graph_get(
        phone_number_id, access_token,
        params={"fields": "id,display_phone_number,verified_name"},
    )
    if not ok:
        raise HTTPException(
            status_code=400,
            detail=graph_detail(profile, "Could not verify WhatsApp credentials"),
        )
    # Graph HTTP success is not phone ownership proof: only the provider's
    # explicit, non-empty ID may authorize this exact selected account.
    provider_phone_id = profile.get("id") if isinstance(profile, dict) else None
    if (not isinstance(provider_phone_id, str)
            or not provider_phone_id.strip()
            or provider_phone_id != str(phone_number_id)):
        raise HTTPException(status_code=400,
                            detail="The access token does not own that phone number")
    if waba_id:
        # Also bind the WABA claim to this exact number. A valid token plus an
        # unrelated WABA id must never be accepted as one connected account.
        profile = await _verify_signup_assets(waba_id, phone_number_id, access_token)
    return profile


def _whatsapp_account_or_404(db: Session, account_id: UUID,
                             organization: Organization):
    account = get_org_account_or_404(db, account_id, organization)
    if account.channel_type != ChannelType.WHATSAPP.value:
        raise HTTPException(status_code=404, detail="Channel account not found")
    return account


def _set_whatsapp_health(db: Session, account, *, credential_status: str,
                         phone_registration: str, waba_subscription: str,
                         readiness: str, reconnect_needed: bool,
                         last_provider_error: str | None = None):
    return ChannelAccountRepository(db).update_provider_health(
        account,
        credential_status=credential_status,
        phone_registration=phone_registration,
        waba_subscription=waba_subscription,
        readiness=readiness,
        reconnect_needed=reconnect_needed,
        last_provider_error=last_provider_error,
    )


async def _finish_whatsapp_subscription(db: Session, account, *, waba_id: str | None,
                                        access_token: str,
                                        phone_registration: str):
    """Project subscription outcome into ChannelAccount health, never a poller."""
    if not waba_id:
        return _set_whatsapp_health(
            db, account,
            credential_status="VALID",
            phone_registration=phone_registration,
            waba_subscription="UNMANAGED",
            readiness="DEGRADED",
            reconnect_needed=False,
        )

    if await subscribe_app(waba_id, access_token):
        return _set_whatsapp_health(
            db, account,
            credential_status="VALID",
            phone_registration=phone_registration,
            waba_subscription="SUBSCRIBED",
            readiness="READY",
            reconnect_needed=False,
        )

    # The token/asset pair is valid, but inbound delivery is not proven. Keep
    # the account usable for corrective reconnect actions while refusing READY.
    logger.warning(f"WABA subscribe failed for {waba_id}")
    return _set_whatsapp_health(
        db, account,
        credential_status="VALID",
        phone_registration=phone_registration,
        waba_subscription="ACTION_REQUIRED",
        readiness="ACTION_REQUIRED",
        reconnect_needed=True,
        last_provider_error="waba_subscription_failed",
    )


@router.get("/embedded-signup-config", response_model=EmbeddedSignupConfigOut)
async def get_embedded_signup_config(
    channel: str = ChannelType.WHATSAPP.value,
    current_user: User = Depends(require_permissions("manage_organization")),
):
    """What the connect UI needs to decide between a Meta login flow and the
    manual credentials form, for the given channel. The app id is returned here
    rather than baked into the frontend build, so a self-hoster can point at
    their own app. A disabled channel returns no ids, so one channel's config
    never leaks on another's request."""
    if channel not in SIGNUP_CHANNELS:
        raise HTTPException(status_code=404, detail="No signup flow for this channel")
    # Both halves of the same gate the connect endpoints enforce, so an account
    # outside the allowlist is shown the manual form rather than a button that
    # would 403 on click.
    enabled = _signup_available(channel) and _signup_allowed_for(current_user)
    return EmbeddedSignupConfigOut(
        enabled=enabled,
        # Instagram Login has no configuration id, only an app id.
        config_id=(_signup_config_id(channel) or None) if enabled else None,
        app_id=_signup_app_id(channel) if enabled else None,
        graph_version=settings.META_GRAPH_VERSION,
    )


@router.post("/whatsapp", response_model=ChannelAccountOut)
async def connect_whatsapp(
    request: WhatsAppConnectRequest,
    current_user: User = Depends(require_permissions("manage_organization")),
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    """Connect a WhatsApp Cloud API number with manual credentials.

    Credential + optional WABA ownership are validated before any credential
    mutation. Subscription failure is projected as ACTION_REQUIRED, never READY.
    """
    repo = ChannelAccountRepository(db)
    existing = repo.get_by_external_id(
        ChannelType.WHATSAPP.value, request.phone_number_id)
    effective_waba_id = request.waba_id
    if (effective_waba_id is None and existing is not None
            and existing.organization_id == organization.id):
        effective_waba_id = repo.get_credentials(existing).get("waba_id")

    profile = await _validate_whatsapp_credentials(
        request.phone_number_id, request.access_token, effective_waba_id)
    display = request.display_name or _whatsapp_display_name(
        profile, request.phone_number_id)
    account = _upsert_account(
        db, organization, ChannelType.WHATSAPP.value,
        external_account_id=request.phone_number_id,
        credentials={"access_token": request.access_token, "waba_id": request.waba_id},
        display_name=display,
    )
    account = await _finish_whatsapp_subscription(
        db, account,
        waba_id=effective_waba_id,
        access_token=request.access_token,
        # Manual Cloud-API credentials may have been registered outside this
        # deployment; no local PIN exists to truthfully re-register them.
        phone_registration="MANAGED_EXTERNALLY",
    )
    return to_account_out(db, account)


@router.post("/whatsapp/embedded-signup", response_model=ChannelAccountOut)
async def connect_whatsapp_embedded_signup(
    request: EmbeddedSignupRequest,
    current_user: User = Depends(require_permissions("manage_organization")),
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    """Finish an Embedded Signup flow: trade the code for the customer's
    business token and connect the number it created.

    Only the way the credentials are obtained differs from connect_whatsapp —
    everything after that is the same upsert and webhook subscribe.
    """
    check_signup_access(ChannelType.WHATSAPP.value, current_user)

    ok, data = await exchange_signup_code(request.code)
    access_token = data.get("access_token") if ok else None
    if not access_token:
        # The code is short-lived (~10 minutes) and single-use, so a stale or
        # replayed one lands here rather than on a Graph error later.
        raise HTTPException(
            status_code=400,
            detail=graph_detail(data, "Could not complete signup — please try connecting again"),
        )

    profile = await _verify_signup_assets(
        request.waba_id, request.phone_number_id, access_token)

    # A number from Embedded Signup is attached to the WABA but cannot send
    # until it is registered for Cloud API use.
    pin = _generate_verification_pin()
    registered, register_data = await register_phone_number(
        request.phone_number_id, access_token, pin)

    credentials = {"access_token": access_token, "waba_id": request.waba_id}
    # Only keep the PIN we actually set on the number. Storing one from a failed
    # register would overwrite a working PIN with a value Meta never accepted.
    if registered:
        credentials["verification_pin"] = pin

    account = _upsert_account(
        db, organization, ChannelType.WHATSAPP.value,
        external_account_id=request.phone_number_id,
        credentials=credentials,
        display_name=request.display_name or _whatsapp_display_name(
            profile, request.phone_number_id),
        activate=registered,
    )
    if not registered:
        # Registration is a sending prerequisite. Persist the account so the UI
        # can offer a corrective reconnect, but never present it as active/ready.
        logger.warning(
            f"Phone {request.phone_number_id} not registered after signup: "
            f"{graph_detail(register_data, 'unknown error')}")
        account = _set_whatsapp_health(
            db, account,
            credential_status="VALID",
            phone_registration="ACTION_REQUIRED",
            waba_subscription="UNKNOWN",
            readiness="ACTION_REQUIRED",
            reconnect_needed=True,
            last_provider_error="phone_registration_failed",
        )
        return to_account_out(db, account)

    account = await _finish_whatsapp_subscription(
        db, account,
        waba_id=request.waba_id,
        access_token=access_token,
        phone_registration="REGISTERED",
    )
    return to_account_out(db, account)


@router.get("/whatsapp/accounts", response_model=list[ChannelAccountOut])
async def list_whatsapp_accounts(
    current_user: User = Depends(require_permissions("manage_organization")),
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    """List every WhatsApp number for this organization, independently."""
    accounts = ChannelAccountRepository(db).list_by_org(
        organization.id, ChannelType.WHATSAPP.value)
    return [to_account_out(db, account) for account in accounts]


@router.post("/whatsapp/{account_id}/reconnect", response_model=ChannelAccountOut)
async def reconnect_whatsapp_account(
    account_id: UUID,
    current_user: User = Depends(require_permissions("manage_organization")),
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    """Re-qualify one exact connected number with its stored credentials."""
    account = _whatsapp_account_or_404(db, account_id, organization)
    repo = ChannelAccountRepository(db)
    credentials = repo.get_credentials(account)
    access_token = credentials.get("access_token")
    waba_id = credentials.get("waba_id")
    if not access_token:
        repo.set_active(account, False)
        _set_whatsapp_health(
            db, account,
            credential_status="INVALID",
            phone_registration="UNKNOWN",
            waba_subscription="UNKNOWN",
            readiness="ACTION_REQUIRED",
            reconnect_needed=True,
            last_provider_error="credential_missing",
        )
        raise HTTPException(status_code=400, detail="Reconnect with a valid WhatsApp access token")

    try:
        await _validate_whatsapp_credentials(
            account.external_account_id, access_token, waba_id)
    except HTTPException:
        repo.set_active(account, False)
        _set_whatsapp_health(
            db, account,
            credential_status="INVALID",
            phone_registration="UNKNOWN",
            waba_subscription="UNKNOWN",
            readiness="ACTION_REQUIRED",
            reconnect_needed=True,
            last_provider_error="credential_validation_failed",
        )
        raise

    registration = "MANAGED_EXTERNALLY"
    pin = credentials.get("verification_pin")
    if pin:
        registered, _ = await register_phone_number(
            account.external_account_id, access_token, pin)
        if not registered:
            repo.set_active(account, False)
            _set_whatsapp_health(
                db, account,
                credential_status="VALID",
                phone_registration="ACTION_REQUIRED",
                waba_subscription="UNKNOWN",
                readiness="ACTION_REQUIRED",
                reconnect_needed=True,
                last_provider_error="phone_registration_failed",
            )
            raise HTTPException(
                status_code=409,
                detail="WhatsApp phone registration needs attention before this number can resume",
            )
        registration = "REGISTERED"

    account = repo.set_active(account, True)
    account = await _finish_whatsapp_subscription(
        db, account,
        waba_id=waba_id,
        access_token=access_token,
        phone_registration=registration,
    )
    return to_account_out(db, account)


@router.post("/whatsapp/{account_id}/rotate-credentials", response_model=ChannelAccountOut)
async def rotate_whatsapp_credentials(
    account_id: UUID,
    request: WhatsAppCredentialRotationRequest,
    current_user: User = Depends(require_permissions("manage_organization")),
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    """Validate a replacement token against this exact number before storing it."""
    account = _whatsapp_account_or_404(db, account_id, organization)
    repo = ChannelAccountRepository(db)
    current = repo.get_credentials(account)
    waba_id = request.waba_id if request.waba_id is not None else current.get("waba_id")

    profile = await _validate_whatsapp_credentials(
        account.external_account_id, request.access_token, waba_id)

    registration = "MANAGED_EXTERNALLY"
    pin = current.get("verification_pin")
    if pin:
        registered, _ = await register_phone_number(
            account.external_account_id, request.access_token, pin)
        if not registered:
            # Do not overwrite the current encrypted credential on a failed
            # rotation. The existing working credential remains authoritative.
            raise HTTPException(
                status_code=400,
                detail="The replacement credential could not register this WhatsApp number",
            )
        registration = "REGISTERED"

    merged = {
        **current,
        "access_token": request.access_token,
        "waba_id": waba_id,
    }
    repo.update_credentials(account, merged)
    if request.display_name:
        account.display_name = request.display_name
        db.commit()
        db.refresh(account)
    elif not account.display_name:
        account.display_name = _whatsapp_display_name(
            profile, account.external_account_id)
        db.commit()
        db.refresh(account)
    account = repo.set_active(account, True)
    account = await _finish_whatsapp_subscription(
        db, account,
        waba_id=waba_id,
        access_token=request.access_token,
        phone_registration=registration,
    )
    return to_account_out(db, account)


@router.delete("/whatsapp/{account_id}")
async def disconnect_whatsapp_account(
    account_id: UUID,
    current_user: User = Depends(require_permissions("manage_organization")),
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    """Remove exactly one local number without unsubscribing its shared WABA."""
    account = _whatsapp_account_or_404(db, account_id, organization)
    if not ChannelAccountRepository(db).delete(account):
        raise HTTPException(status_code=500, detail="Could not disconnect WhatsApp account")
    return {"status": "disconnected"}


@router.post("/messenger", response_model=ChannelAccountOut)
async def connect_messenger(
    request: MessengerConnectRequest,
    current_user: User = Depends(require_permissions("manage_organization")),
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    """Connect a Facebook Page for Messenger with a page access token."""
    # Inspect the token rather than reading the Page node: `me?fields=id,name`
    # needs pages_read_engagement, which a messaging token has no reason to
    # carry — it would reject a token that sends perfectly well.
    ok, info = await debug_token(request.page_access_token)
    if not ok or not info.get("is_valid"):
        raise HTTPException(status_code=400, detail=graph_detail(
            info, "That token is not valid — generate a fresh Page access token"))
    if info.get("type") != "PAGE":
        raise HTTPException(status_code=400, detail=(
            f"That is a {str(info.get('type', 'user')).lower()} access token, not a Page "
            f"access token. In the Meta app dashboard go to Messenger → Settings and "
            f"click Generate on the row for your Page."))
    if str(info.get("profile_id")) != request.page_id:
        raise HTTPException(status_code=400, detail=(
            f"That token is for Page {info.get('profile_id')}, not the Page ID you "
            f"entered. Webhooks are routed by Page ID, so the two must match."))

    display_name = request.display_name or await _page_name(
        request.page_id, request.page_access_token)
    account = _upsert_account(
        db, organization, ChannelType.MESSENGER.value,
        external_account_id=request.page_id,
        credentials={"access_token": request.page_access_token},
        display_name=display_name,
        activate=False,
    )
    account = await _finish_messenger_subscription(
        db,
        account,
        page_id=request.page_id,
        access_token=request.page_access_token,
    )
    return to_account_out(db, account)


@router.post("/messenger/signup/pages", response_model=MessengerSignupPagesOut)
async def list_messenger_signup_pages(
    request: MessengerSignupRequest,
    current_user: User = Depends(require_permissions("manage_organization")),
    organization: Organization = Depends(get_current_organization),
):
    """Step 1 of Facebook Login for Business: trade the code for the customer's
    Pages so they can pick which to connect.

    The Page tokens are sealed into signup_token and never reach the browser;
    only the ids and names come back for the picker.
    """
    check_signup_access(ChannelType.MESSENGER.value, current_user)
    user_token = await _signup_user_token(request)

    pages = await _list_manageable_pages(user_token, "id,name,access_token")
    if not pages:
        raise HTTPException(status_code=400, detail=(
            "No Facebook Pages were shared with ChatterMate. Run the connect "
            "again and tick the Page you want to use."))

    return MessengerSignupPagesOut(
        signup_token=_seal_signup_pages(organization.id, pages),
        pages=[MessengerPageOut(id=p["id"], name=p.get("name") or p["id"]) for p in pages],
    )


@router.post("/messenger/signup/connect", response_model=ChannelAccountOut)
async def connect_messenger_signup(
    request: MessengerSignupConnectRequest,
    current_user: User = Depends(require_permissions("manage_organization")),
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    """Step 2: connect the Page the customer picked in step 1.

    page_id is a selector into the list we fetched ourselves, never a caller
    claim: the token stored is the one /me/accounts returned for that Page, so a
    caller cannot connect a Page they do not administer. This is the Messenger
    equivalent of _verify_signup_assets, and matters for the same reason —
    webhooks resolve accounts by external id with no org scoping.
    """
    check_signup_access(ChannelType.MESSENGER.value, current_user)
    pages = _open_signup_pages(request.signup_token, organization)

    page = next((p for p in pages if p.get("id") == request.page_id), None)
    if page is None or not page.get("access_token"):
        raise HTTPException(status_code=400, detail="That Page was not part of this signup")

    account = _upsert_account(
        db, organization, ChannelType.MESSENGER.value,
        external_account_id=page["id"],
        credentials={"access_token": page["access_token"]},
        display_name=request.display_name or page.get("name") or page["id"],
        activate=False,
    )
    account = await _finish_messenger_subscription(
        db,
        account,
        page_id=page["id"],
        access_token=page["access_token"],
    )
    return to_account_out(db, account)


@router.post("/instagram/login/connect", response_model=ChannelAccountOut)
async def connect_instagram_login(
    request: InstagramLoginRequest,
    current_user: User = Depends(require_permissions("manage_organization")),
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    """Connect an Instagram professional account through Instagram Login.

    Unlike Messenger this needs no Facebook Page: the business signs in with
    Instagram itself, so the login returns exactly one account and there is
    nothing to pick. The token is an Instagram user token, used against
    graph.instagram.com rather than the Facebook graph.
    """
    check_signup_access(ChannelType.INSTAGRAM.value, current_user)

    ok, data = await exchange_instagram_code(request.code, request.redirect_uri)
    token_data = instagram_token_payload(data) if ok else {}
    access_token = token_data.get("access_token")
    user_id = token_data.get("user_id")
    if not access_token or not user_id:
        # The code is single-use and short-lived, so a stale or replayed one
        # lands here rather than on a Graph error later.
        raise HTTPException(status_code=400, detail=graph_detail(
            data, "Could not complete Instagram login — please try connecting again"))

    # The login token lasts about an hour; without extending it the connection
    # dies silently mid-conversation. Best-effort, like the Page flow.
    ok, extended = await exchange_instagram_long_lived(access_token)
    if ok and extended.get("access_token"):
        access_token = extended["access_token"]
    else:
        logger.warning("Could not extend the Instagram token; it may expire within the hour")

    ok, profile = await graph_get("me", access_token,
                                  params={"fields": "user_id,username"},
                                  base=GRAPH_INSTAGRAM_BASE)
    # The OAuth user_id may be app-scoped and differ from webhook entry.id.
    # Connecting on that fallback would acknowledge login but silently lose DMs.
    # A verified professional account identity is mandatory for all accounts.
    account_id = str(profile.get("user_id") or "") if ok else ""
    if not account_id:
        raise HTTPException(status_code=400,
                            detail="Could not verify the Instagram professional account identity")
    username = profile.get("username")

    if request.reconnect_account_id is not None:
        expected = get_org_account_or_404(db, request.reconnect_account_id, organization)
        if (expected.channel_type != ChannelType.INSTAGRAM.value
                or expected.external_account_id != account_id):
            raise HTTPException(status_code=409,
                                detail="Instagram login did not match the selected account")

    account = _upsert_account(
        db, organization, ChannelType.INSTAGRAM.value,
        external_account_id=account_id,
        credentials={"access_token": access_token},
        display_name=request.display_name or ("@" + (username or account_id)),
    )
    if not await subscribe_instagram_app(access_token):
        logger.warning(f"Instagram webhook subscribe failed for {account_id}; DMs may not arrive")
    return to_account_out(db, account)


@router.post("/instagram", response_model=ChannelAccountOut)
async def connect_instagram(
    request: InstagramConnectRequest,
    current_user: User = Depends(require_permissions("manage_organization")),
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    """Connect an Instagram professional account (via its linked page token)."""
    ok, data = await graph_get(request.ig_id, request.page_access_token,
                               params={"fields": "id,username"})
    if not ok:
        raise HTTPException(status_code=400,
                            detail=f"Could not verify Instagram credentials: {data.get('error', {}).get('message', 'invalid token or account id')}")
    # Webhook routing matches entry.id against this value, so reject anything
    # that isn't the actual IG business-account id (e.g. a pasted Page id —
    # the page token can read that node too, so ok=True alone isn't enough).
    if str(data.get("id")) != request.ig_id:
        raise HTTPException(status_code=400,
                            detail="The ID entered is not an Instagram professional account ID")

    account = _upsert_account(
        db, organization, ChannelType.INSTAGRAM.value,
        external_account_id=request.ig_id,
        credentials={"access_token": request.page_access_token},
        display_name=request.display_name or f"@{data.get('username', request.ig_id)}",
    )
    return to_account_out(db, account)


@router.delete("/{account_id}")
async def disconnect_meta_account(
    account_id: UUID,
    current_user: User = Depends(require_permissions("manage_organization")),
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    """Disconnect a WhatsApp/Messenger/Instagram account."""
    account = get_org_account_or_404(db, account_id, organization)
    if account.channel_type not in (ChannelType.WHATSAPP.value,
                                    ChannelType.MESSENGER.value,
                                    ChannelType.INSTAGRAM.value):
        raise HTTPException(status_code=404, detail="Channel account not found")
    if not ChannelAccountRepository(db).delete(account):
        raise HTTPException(status_code=500, detail="Could not disconnect channel account")
    return {"status": "disconnected"}
