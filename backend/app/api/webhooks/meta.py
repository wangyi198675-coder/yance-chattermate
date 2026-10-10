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

from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session

from app.api.webhooks.common import is_duplicate_message
from app.channels import get_adapter
from app.channels.meta_base import authenticated_meta_app_ids, verify_challenge
from app.core.config import settings
from app.core.logger import get_logger
from app.database import get_db
from app.models.channels import ChannelType
from app.repositories.channels import ChannelAccountRepository
from app.repositories.chat import ChatRepository
from app.services.channel_chat import process_channel_message

router = APIRouter()
logger = get_logger(__name__)

# One Meta app subscribes WhatsApp + Messenger + Instagram to this single
# callback; the payload's top-level `object` says which product it is.
_OBJECT_TO_CHANNEL = {
    "whatsapp_business_account": ChannelType.WHATSAPP.value,
    "page": ChannelType.MESSENGER.value,
    "instagram": ChannelType.INSTAGRAM.value,
}


@router.get("")
async def meta_webhook_verify(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    """Webhook verification handshake (App Dashboard → Webhooks → Verify)."""
    challenge = verify_challenge(hub_mode, hub_verify_token, hub_challenge)
    if challenge is None:
        raise HTTPException(status_code=403, detail="Verification failed")
    # Meta expects the raw challenge echoed as text/plain
    return Response(content=challenge, media_type="text/plain")


@router.post("")
async def meta_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Receive a Meta webhook for any of WhatsApp / Messenger / Instagram.

    Verifies the app-level signature, routes on the `object` field, resolves
    the connected account per message, acks immediately, and processes in the
    background.
    """
    raw_body = await request.body()
    # Authenticate the registered Meta application from the signed RAW bytes
    # before using the untrusted payload to select a product or account.
    signed_app_ids = authenticated_meta_app_ids(
        raw_body, request.headers.get("x-hub-signature-256", ""))
    if not signed_app_ids:
        logger.warning(f"Meta webhook rejected: bad or unbound signature ({len(raw_body)} bytes)")
        raise HTTPException(status_code=403, detail="Invalid signature")

    payload = await request.json()
    channel_type = _OBJECT_TO_CHANNEL.get(payload.get("object"))
    if channel_type is None:
        # Unknown product subscription — ack so Meta doesn't retry forever
        return {"status": "ignored"}

    expected_app_id = (
        settings.INSTAGRAM_APP_ID if channel_type == ChannelType.INSTAGRAM.value
        else settings.META_APP_ID
    )
    if not expected_app_id or expected_app_id not in signed_app_ids:
        # Same registered App ID can legitimately serve multiple subscriptions;
        # a DIFFERENT app's valid HMAC may not authenticate this product.
        logger.warning("Meta webhook rejected: signer not authorized for product")
        raise HTTPException(status_code=403, detail="Invalid signature")

    adapter = get_adapter(channel_type)
    account_repo = ChannelAccountRepository(db)

    for inbound in adapter.parse_inbound(payload):
        account = account_repo.get_by_external_id(channel_type, inbound.external_account_id)
        if account is None or not account.is_active:
            logger.info(f"No active {channel_type} account for {inbound.external_account_id}")
            continue

        if channel_type == ChannelType.WHATSAPP.value:
            health = dict((account.settings or {}).get("provider_health") or {})
            updates = {
                "waba_subscription": "SUBSCRIBED",
                "last_webhook_at": datetime.now(timezone.utc).isoformat(),
            }
            if (health.get("credential_status") == "VALID"
                    and health.get("phone_registration") != "ACTION_REQUIRED"):
                updates.update(
                    readiness="READY",
                    reconnect_needed=False,
                    last_provider_error=None,
                )
            account_repo.update_provider_health(account, **updates)

        # ChatHistory is the durable authority. This survives restarts and
        # works when Redis is absent; Redis below is only a soft near-term
        # retry hint and cannot suppress an unpersisted provider message.
        if ChatRepository(db).provider_message_exists(
                channel_type, account.external_account_id,
                inbound.external_message_id):
            logger.info(
                f"Skipping durable duplicate {channel_type} message "
                f"{inbound.external_message_id} for {account.external_account_id}")
            continue
        if is_duplicate_message(channel_type,
                                f"{account.id}:{inbound.external_message_id}"):
            # Redis is only a near-term retry hint. It must never suppress a
            # message that ChatHistory has not durably claimed yet: the first
            # background task may have failed after the webhook was acked but
            # before persistence, and a later provider retry must still run.
            logger.info(
                f"Observed soft duplicate hint for {channel_type} message "
                f"{inbound.external_message_id}; durable ChatHistory claim decides")
        background_tasks.add_task(process_channel_message, account.id, inbound)

    return {"status": "ok"}
