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

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.core.socketio import sio
from app.channels import get_adapter, WindowStatus
from app.models.chat_history import ChatHistory
from app.models.customer import Customer
from app.models.agent import Agent
from app.models.organization import Organization
from app.models.session_to_agent import SessionToAgent
from app.repositories.channels import ChannelAccountRepository, ChannelConversationRepository
from app.repositories.chat import ChatRepository
from app.database import SessionLocal
from app.services.yance_turn_authority import revalidate_auto_send
from app.services.file_storage import resolve_public_url
from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger(__name__)

WEB_CHANNEL = 'web'


@dataclass
class DeliveryResult:
    ok: bool
    reason: Optional[str] = None
    # A WhatsApp template message could reopen the conversation
    can_template: bool = False
    ambiguous: bool = False
    provider_receipts: list[dict] = field(default_factory=list)
    external_message_id: Optional[str] = None


def _lock_auto_context(db: Session, session_record: SessionToAgent):
    """Lock existing owners in one global order before a physical-send decision.

    Customer first serializes all ChatRepository inbound/outbound inserts and
    new session creation. Existing conversation journeys, canonical Session
    takeover and Agent config are locked until the Socket.IO effect returns.
    """
    customer = db.query(Customer).filter(
        Customer.id == session_record.customer_id,
        Customer.organization_id == session_record.organization_id,
    ).with_for_update().first()
    if customer is None:
        return None
    sessions = db.query(SessionToAgent).filter(
        SessionToAgent.customer_id == session_record.customer_id,
        SessionToAgent.organization_id == session_record.organization_id,
    ).order_by(SessionToAgent.session_id.asc()).with_for_update().all()
    current = next(
        (item for item in sessions if item.session_id == session_record.session_id),
        None,
    )
    if current is None:
        return None
    # Lock only the Agent's canonical row. ORM Agent eagerly joins Groups;
    # SELECT ... FOR UPDATE on that nullable outer join fails on real PostgreSQL.
    db.query(Agent.id).filter(
        Agent.id == current.agent_id,
        Agent.organization_id == current.organization_id,
    ).with_for_update().first()
    # Contact local-time/temporal policy also depends on the canonical
    # Organization timezone and its revision; hold it through physical send.
    db.query(Organization).filter(
        Organization.id == current.organization_id,
    ).with_for_update().first()
    return current


async def _deliver_ai_auto_web(
    db: Session,
    session_record: SessionToAgent,
    payload: dict,
    message: Optional[ChatHistory],
    authority: dict | None,
) -> DeliveryResult:
    """Exactly one canonical AI_AUTO Web emit; ambiguous crash is not replayed.

    Database ownership: ChatHistory unique client_send_intent, provider_delivery,
    shared execution_guard; no alternate outbox or auto provider sender.
    """
    if (
        message is None or not payload.get("yance_ai_auto")
        or not isinstance(authority, dict)
        or not message.client_send_intent_id
        or (message.attributes or {}).get("client_send_action_kind") != "ai_auto"
        or message.message_type != "bot"
        or str(message.session_id) != str(session_record.session_id)
        or message.message != payload.get("message")
    ):
        return DeliveryResult(ok=False, reason="ai_auto_canonical_intent_or_candidate_missing")
    if (
        (session_record.channel or "web") != "web"
        or payload.get("end_chat") or payload.get("transfer_to_human")
    ):
        return DeliveryResult(ok=False, reason="ai_auto_route_or_side_effect_unavailable")

    from app.services.yance_reply_runtime import revalidate_ai_auto_authority
    # The same advisory guard used by HUMAN and AI_ASSIST serializes all
    # completions for one ChatHistory row, including process re-entry.
    with SessionLocal() as guard_db:
        async with ChatRepository(guard_db).client_send_execution_guard(message.id):
            context = _lock_auto_context(guard_db, session_record)
            if context is None or (context.channel or "web") != "web":
                return DeliveryResult(ok=False, reason="ai_auto_context_missing")
            canonical = guard_db.query(ChatHistory).filter(
                ChatHistory.id == message.id,
                ChatHistory.session_id == context.session_id,
            ).with_for_update().first()
            if canonical is None:
                return DeliveryResult(ok=False, reason="ai_auto_canonical_message_missing")
            previous = (canonical.attributes or {}).get("provider_delivery") or {}
            if previous.get("state") == "succeeded":
                return DeliveryResult(ok=True, reason="provider_already_accepted")
            if previous.get("state") in {"sending", "ambiguous"}:
                return DeliveryResult(
                    ok=False, reason="ambiguous_previous_send", ambiguous=True,
                )
            try:
                stale = revalidate_ai_auto_authority(
                    guard_db, str(context.session_id), authority,
                )
            except Exception:
                logger.exception("AI_AUTO canonical pre-commit revalidation failed")
                return DeliveryResult(ok=False, reason="ai_auto_revalidation_unavailable")
            if stale:
                return DeliveryResult(ok=False, reason=stale)

            canonical.attributes = {
                **(canonical.attributes or {}),
                "provider_delivery": {
                    "state": "sending",
                    "channel": "web",
                    "outcome": "provider_pending",
                },
            }
            # The ambiguous-send marker is durable BEFORE the external effect.
            # Crash/re-entry after this point cannot dispatch a second emit.
            guard_db.commit()

            # A writer that committed while the marker was being persisted must
            # win over the send. A send that reacquires the canonical locks and
            # validates first commits to one physical effect, holding the locks
            # until Socket.IO returns.
            context = _lock_auto_context(guard_db, session_record)
            canonical = guard_db.query(ChatHistory).filter(
                ChatHistory.id == message.id,
            ).with_for_update().first()
            try:
                stale = (
                    "ai_auto_context_missing" if context is None
                    else revalidate_ai_auto_authority(
                        guard_db, str(context.session_id), authority,
                    )
                )
            except Exception:
                stale = "ai_auto_revalidation_unavailable"
            # W294's separate revision/turn commitment proof also applies to
            # the W257 durable Web path while its lock set is held. The
            # "sending" marker belongs to THIS guarded candidate, so it may
            # pass only within the already serialized W257 send section.
            w294_authority = payload.get("_ai_auto_authority")
            if not stale and w294_authority is not None:
                stale = revalidate_auto_send(
                    guard_db, w294_authority, payload,
                    allow_owned_sending=True,
                )
            if stale:
                canonical.attributes = {
                    **(canonical.attributes or {}),
                    "provider_delivery": {
                        "state": "failed", "channel": "web",
                        "outcome": "not_sent", "error": stale,
                    },
                }
                guard_db.commit()
                return DeliveryResult(ok=False, reason=stale)
            try:
                await sio.emit(
                    "chat_response",
                    {k: v for k, v in payload.items() if k != "_ai_auto_authority"},
                    room=str(context.session_id),
                    namespace="/widget",
                )
            except Exception:
                canonical.attributes = {
                    **(canonical.attributes or {}),
                    "provider_delivery": {
                        "state": "ambiguous", "channel": "web",
                        "outcome": "unknown_transport_acceptance",
                    },
                }
                guard_db.commit()
                return DeliveryResult(
                    ok=False, reason="widget_emit_ambiguous", ambiguous=True,
                )
            canonical.attributes = {
                **(canonical.attributes or {}),
                "provider_delivery": {
                    "state": "succeeded", "channel": "web",
                    "outcome": "provider_accepted",
                    "recipient_delivered": False,
                    "recipient_replied": False,
                    "success": False,
                },
            }
            guard_db.commit()
            return DeliveryResult(ok=True)


async def deliver_to_customer(db: Session, session_record: SessionToAgent, payload: dict) -> DeliveryResult:
    """Route a reply (human or bot) to wherever the customer is.

    Widget sessions keep the existing Socket.IO emit unchanged; external
    channel sessions are delivered through their ChannelAdapter. The widget
    emit also fires for channel sessions so any live dashboard viewers of
    the session room stay consistent.
    """
    session_id = str(session_record.session_id)
    channel = getattr(session_record, 'channel', None)
    if not isinstance(channel, str) or not channel:
        channel = WEB_CHANNEL

    message = _delivery_message(db, payload)
    auto_requested = bool(payload.get("yance_ai_auto"))
    auto_snapshot = (message.attributes or {}).get("yance_auto_authority") if message else None
    if auto_requested or auto_snapshot is not None:
        return await _deliver_ai_auto_web(db, session_record, payload, message, auto_snapshot)
    authority = payload.get("_ai_auto_authority")
    if authority is not None:
        # Distinct DB transaction: message_delivery commits ChatHistory attempt
        # metadata while these canonical authority-row locks remain held.
        with SessionLocal() as gate_db:
            reason = revalidate_auto_send(gate_db, authority, payload)
            if reason:
                gate_db.rollback()
                bot_id = authority.get("bot_message_id") if isinstance(authority, dict) else None
                # A replay of an already delivered canonical row is not a
                # delivery failure. Preserve the existing successful receipt.
                if bot_id is not None and reason not in {
                    "auto_send_already_committed", "auto_send_intent_failed"
                }:
                    try:
                        ChatRepository(db).mark_delivery_failed(int(bot_id), reason)
                    except (TypeError, ValueError):
                        pass
                return DeliveryResult(ok=False, reason=reason)
            # The session/agent row locks also serialize auto-send re-entry.
            # FK inserts of newer inbound rows wait for the session lock.
            try:
                if channel == WEB_CHANNEL:
                    # Durable precommit on the SAME canonical bot row.
                    bot = _delivery_message(db, payload)
                    if bot is None:
                        return DeliveryResult(ok=False, reason="auto_send_bot_intent_missing")
                    _persist_delivery_attempt(db, bot, channel, "sending", [], verify=True,
                                              auto_authority=authority)
                    receiver_payload = {
                        k: v for k, v in payload.items() if k != "_ai_auto_authority"
                    }
                    receiver_payload["message_id"] = bot.id
                    try:
                        participants = list(sio.manager.get_participants('/widget', session_id))
                    except (AttributeError, TypeError):
                        logger.exception("Web Socket.IO receiver lookup failed")
                        return DeliveryResult(ok=False, reason="web_receiver_lookup_failed", ambiguous=True)
                    if not participants:
                        return DeliveryResult(ok=False, reason="web_receiver_not_connected", ambiguous=True)
                    received_ack = False
                    for receiver_sid, _ in participants:
                        try:
                            ack = await sio.call('chat_response', receiver_payload,
                                                 to=receiver_sid, namespace='/widget', timeout=4)
                        except Exception:
                            logger.warning("Missing Web ACK for message %s, receiver %s",
                                           bot.id, receiver_sid, exc_info=True)
                            continue
                        if (isinstance(ack, dict)
                                and str(ack.get("message_id")) == str(bot.id)
                                and ack.get("accepted") is True):
                            received_ack = True
                    if not received_ack:
                        # Retry is still authorized and idempotent by canonical ID.
                        return DeliveryResult(ok=False, reason="web_receiver_ack_missing", ambiguous=True)
                    _persist_delivery_attempt(db, bot, channel, "succeeded", [], verify=True)
                    return DeliveryResult(ok=True)
                result = await _deliver_to_channel(db, session_record, channel, payload)
                if result.ok:
                    await sio.emit('chat_response',
                                   {k: v for k, v in payload.items() if k != "_ai_auto_authority"},
                                   room=session_id, namespace='/widget')
                return result
            except BaseException:
                # Web retains its replayable precommit; do not turn ACK crashes
                # into permanent ambiguity. External provider behavior is unchanged.
                if channel != WEB_CHANNEL:
                    try:
                        bot = _delivery_message(db, payload)
                        _persist_delivery_attempt(db, bot, channel, "ambiguous", [],
                                                  "auto_send_commitment_exception")
                    except Exception:
                        db.rollback()
                raise
            finally:
                gate_db.rollback()  # release locks without mutating authority

    if channel == WEB_CHANNEL:
        await sio.emit('chat_response', payload, room=session_id, namespace='/widget')
        return DeliveryResult(ok=True)

    result = await _deliver_to_channel(db, session_record, channel, payload)
    await sio.emit('chat_response', payload, room=session_id, namespace='/widget')
    return result


async def recover_pending_web_auto_messages(
    db: Session, session_record: SessionToAgent,
) -> int:
    """Recover Web precommits on widget history request; no second queue/store.

    Every replay carries the exact durable canonical bot ID and snapshot.
    A failed final authority re-read emits nothing.
    """
    if (getattr(session_record, "channel", None) or WEB_CHANNEL) != WEB_CHANNEL:
        return 0
    rows = (db.query(ChatHistory)
            .filter(ChatHistory.session_id == session_record.session_id,
                    ChatHistory.message_type == "bot")
            .order_by(ChatHistory.id.desc()).limit(100).all())
    delivered = 0
    for bot in reversed(rows):
        attrs = bot.attributes or {}
        attempt = attrs.get("provider_delivery") or {}
        authority = attrs.get("ai_auto_authority")
        if (attempt.get("state") != "sending"
                or attempt.get("channel") != WEB_CHANNEL
                or not isinstance(authority, dict)):
            continue
        # Several authenticated Widget clients can request history at once.
        # Serialize their recovery through the EXISTING per-ChatHistory
        # PostgreSQL advisory execution guard. It waits asynchronously (via
        # pg_try_advisory_lock), so a concurrent history handler never blocks
        # the ASGI event loop on revalidate_auto_send's synchronous FOR UPDATE
        # while the winning delivery awaits a real Socket.IO ACK. The actual
        # authorization row locks remain unchanged in deliver_to_customer.
        async with ChatRepository(db).client_send_execution_guard(bot.id):
            # The original history query may have cached "sending" before
            # another recovery's ACK committed. Re-read the canonical row
            # under the guard so no second callback is sent after success.
            db.expire(bot)
            latest_attrs = bot.attributes or {}
            latest_attempt = latest_attrs.get("provider_delivery") or {}
            latest_authority = latest_attrs.get("ai_auto_authority")
            if (latest_attempt.get("state") != "sending"
                    or latest_attempt.get("channel") != WEB_CHANNEL
                    or not isinstance(latest_authority, dict)):
                continue
            result = await deliver_to_customer(db, session_record, {
                "message": bot.message, "message_id": bot.id,
                "session_id": str(session_record.session_id),
                "type": "chat_response", "_ai_auto_authority": latest_authority,
            })
            if result.ok:
                delivered += 1
    return delivered


def _delivery_message(db: Session, payload: dict) -> Optional[ChatHistory]:
    message_id = payload.get("message_id")
    if message_id is None:
        return None
    try:
        return db.query(ChatHistory).filter(ChatHistory.id == int(message_id)).first()
    except (TypeError, ValueError):
        return None


def _persist_delivery_attempt(db: Session, message: Optional[ChatHistory], channel: str,
                              state: str, receipts: list[dict],
                              error: Optional[str] = None, *,
                              verify: bool = False,
                              auto_authority: Optional[dict] = None) -> None:
    if message is None:
        return
    previous = (message.attributes or {}).get("provider_delivery") or {}
    attempt = {
        "state": state,
        "channel": channel,
        "started_at": previous.get("started_at") or datetime.now(timezone.utc).isoformat(),
        "receipts": receipts,
    }
    if state in {"succeeded", "failed", "ambiguous"}:
        attempt["finished_at"] = datetime.now(timezone.utc).isoformat()
    if error:
        attempt["error"] = error
    updates = {"provider_delivery": attempt}
    if auto_authority is not None:
        updates["ai_auto_authority"] = auto_authority
    ChatRepository(db).update_message_attributes(message.id, updates)
    db.refresh(message)
    if verify:
        persisted = (message.attributes or {}).get("provider_delivery") or {}
        if persisted.get("state") != state or list(persisted.get("receipts") or []) != receipts:
            raise RuntimeError("delivery attempt persistence failed")


def _pending_template_delivery(db: Session, session_id) -> Optional[ChatHistory]:
    """Return an unresolved template intent that must block replay after restart."""
    candidates = (
        db.query(ChatHistory)
        .filter(
            ChatHistory.session_id == session_id,
            ChatHistory.message_type == "bot",
        )
        .order_by(ChatHistory.id.desc())
        .all()
    )
    for candidate in candidates:
        attributes = candidate.attributes or {}
        if not attributes.get("outbound_template"):
            continue
        state = (attributes.get("provider_delivery") or {}).get("state")
        if state in {"sending", "ambiguous"}:
            return candidate
    return None


def _bind_provider_identity(
    db: Session,
    message: ChatHistory,
    *,
    channel: str,
    external_account_id: str,
    external_message_id: str,
) -> None:
    """Promote a provider receipt onto the same canonical ChatHistory row."""
    message.provider_channel = channel
    message.external_account_id = external_account_id
    message.external_message_id = external_message_id
    message.attributes = {
        **(message.attributes or {}),
        "channel": channel,
        "external_account_id": external_account_id,
        "external_message_id": external_message_id,
    }
    db.commit()
    db.refresh(message)


def _drop_delivery_message(db: Session, message: ChatHistory) -> None:
    """Remove a deterministic non-send intent; ambiguous sends must remain durable."""
    try:
        db.delete(message)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Could not remove failed delivery intent message %s", message.id)


async def deliver_whatsapp_template(
    db: Session,
    session_record: SessionToAgent,
    *,
    template_name: str,
    language: str,
    components: Optional[list],
    rendered_text: str,
) -> DeliveryResult:
    """Persist one canonical intent and send a WhatsApp template through this authority."""
    if getattr(session_record, "channel", None) != "whatsapp":
        return DeliveryResult(ok=False, reason="invalid_template_channel")

    conversation = ChannelConversationRepository(db).get_by_session(session_record.session_id)
    if conversation is None:
        return DeliveryResult(ok=False, reason="no_channel_conversation")

    account = ChannelAccountRepository(db).get_by_id(conversation.channel_account_id)
    if account is None or not account.is_active:
        return DeliveryResult(ok=False, reason="account_inactive")

    pending = _pending_template_delivery(db, session_record.session_id)
    if pending is not None:
        previous = (pending.attributes or {}).get("provider_delivery") or {}
        receipts = list(previous.get("receipts") or [])
        external_message_id = next(
            (str(item.get("external_message_id")) for item in receipts
             if item.get("external_message_id")),
            None,
        )
        return DeliveryResult(
            ok=False,
            reason="ambiguous_previous_send",
            ambiguous=True,
            provider_receipts=receipts,
            external_message_id=external_message_id,
        )

    message = ChatRepository(db).create_message({
        "message": rendered_text,
        "message_type": "bot",
        "session_id": str(session_record.session_id),
        "organization_id": str(account.organization_id),
        "agent_id": str(session_record.agent_id) if session_record.agent_id else None,
        "customer_id": (
            str(conversation.customer_id)
            if conversation.customer_id
            else (str(session_record.customer_id) if session_record.customer_id else None)
        ),
        "attributes": {
            "channel": "whatsapp",
            "external_account_id": account.external_account_id,
            "outbound_template": template_name,
        },
    })

    result = await _deliver_to_channel(
        db,
        session_record,
        "whatsapp",
        {
            "message_id": message.id,
            "message": rendered_text,
            "template": {
                "name": template_name,
                "language": language,
                "components": components,
            },
        },
    )

    if not result.ok and not result.ambiguous:
        _drop_delivery_message(db, message)
    return result


async def _provider_media_url(stored_url: str) -> str:
    public_url = await resolve_public_url(stored_url)
    if public_url.startswith(("http://", "https://")):
        return public_url
    backend = settings.BACKEND_URL.rstrip("/")
    if public_url.startswith("/uploads/"):
        return f"{backend}{settings.API_V1_STR}{public_url}"
    if public_url.startswith("/"):
        return f"{backend}{public_url}"
    return f"{backend}/{public_url}"


async def _deliver_to_channel(db: Session, session_record: SessionToAgent,
                              channel: str, payload: dict) -> DeliveryResult:
    session_id = str(session_record.session_id)

    adapter = get_adapter(channel)
    if adapter is None:
        logger.error(f"No adapter registered for channel '{channel}' (session {session_id})")
        return DeliveryResult(ok=False, reason='unknown_channel')

    conversation = ChannelConversationRepository(db).get_by_session(session_record.session_id)
    if conversation is None:
        logger.error(f"No channel conversation for {channel} session {session_id}")
        return DeliveryResult(ok=False, reason='no_channel_conversation')

    account_repo = ChannelAccountRepository(db)
    account = account_repo.get_by_id(conversation.channel_account_id)
    if account is None or not account.is_active:
        return DeliveryResult(ok=False, reason='account_inactive')

    template_payload = payload.get("template")
    if template_payload is None:
        window = adapter.check_delivery_window(conversation)
        if window is WindowStatus.TEMPLATE_REQUIRED:
            return DeliveryResult(ok=False, reason='window_expired', can_template=True)
        if window is WindowStatus.UNDELIVERABLE:
            return DeliveryResult(ok=False, reason='window_expired')
    elif channel != "whatsapp" or not isinstance(template_payload, dict):
        return DeliveryResult(ok=False, reason="invalid_template_delivery")

    text = payload.get('message') or ''
    attachments = payload.get('attachments') or []
    message = _delivery_message(db, payload)
    previous = ((message.attributes or {}).get("provider_delivery") or {}) if message else {}
    previous_state = previous.get("state")
    if previous_state == "succeeded":
        return DeliveryResult(
            ok=True,
            reason="already_delivered",
            provider_receipts=list(previous.get("receipts") or []),
        )
    if previous_state in {"sending", "ambiguous"}:
        return DeliveryResult(
            ok=False,
            reason="ambiguous_previous_send",
            ambiguous=True,
            provider_receipts=list(previous.get("receipts") or []),
        )

    receipts: list[dict] = []
    _persist_delivery_attempt(
        db, message, channel, "sending", receipts,
        verify=template_payload is not None or bool(payload.get("_ai_auto_authority")),
    )

    async def record(kind: str, index: int, result, content_type: Optional[str] = None):
        receipt = {
            "kind": kind,
            "index": index,
            "ok": bool(result.ok),
            "external_message_id": result.external_message_id,
        }
        if content_type:
            receipt["content_type"] = content_type
        if result.error:
            receipt["error"] = result.error
        receipts.append(receipt)
        state = "sending" if result.ok else ("ambiguous" if result.ambiguous else "failed")
        _persist_delivery_attempt(
            db, message, channel, state, receipts,
            error=result.error if not result.ok else None,
            verify=template_payload is not None or bool(payload.get("_ai_auto_authority")),
        )

    if template_payload is not None:
        template_result = await adapter.send_template(
            account,
            conversation,
            template_name=str(template_payload.get("name") or ""),
            language=str(template_payload.get("language") or ""),
            components=template_payload.get("components"),
        )
        try:
            await record("template", 0, template_result)
        except Exception as exc:
            db.rollback()
            reason = (
                f"provider_accepted_persistence_ambiguous: {exc}"
                if template_result.ok else f"delivery_persistence_failed: {exc}"
            )
            if template_result.ok:
                try:
                    _persist_delivery_attempt(
                        db, message, channel, "ambiguous", receipts, reason)
                except Exception:
                    db.rollback()
            return DeliveryResult(
                ok=False,
                reason=reason,
                ambiguous=bool(template_result.ok or template_result.ambiguous),
                provider_receipts=receipts,
                external_message_id=template_result.external_message_id,
            )

        try:
            health = dict((account.settings or {}).get("provider_health") or {})
            if template_result.ok:
                subscribed = health.get("waba_subscription") == "SUBSCRIBED"
                account_repo.update_provider_health(
                    account,
                    credential_status="VALID",
                    phone_registration="REGISTERED",
                    readiness="READY" if subscribed else "DEGRADED",
                    reconnect_needed=False,
                    last_provider_error=None,
                    last_send_at=datetime.now(timezone.utc).isoformat(),
                )
            else:
                account_repo.update_provider_health(
                    account,
                    readiness="DEGRADED",
                    last_provider_error=template_result.error or "template_send_failed",
                )
        except Exception:
            db.rollback()
            logger.exception("Could not update WhatsApp provider health after template send")

        if not template_result.ok:
            logger.error(
                f"Failed delivering WhatsApp template on session {session_id}: "
                f"{template_result.error}"
            )
            return DeliveryResult(
                ok=False,
                reason=template_result.error or "template_send_failed",
                ambiguous=template_result.ambiguous,
                provider_receipts=receipts,
                external_message_id=template_result.external_message_id,
            )

        external_message_id = str(template_result.external_message_id or "").strip()
        if not external_message_id:
            reason = "provider accepted template without external_message_id"
            try:
                _persist_delivery_attempt(
                    db, message, channel, "ambiguous", receipts, reason)
            except Exception:
                db.rollback()
            return DeliveryResult(
                ok=False,
                reason=reason,
                ambiguous=True,
                provider_receipts=receipts,
            )

        try:
            if message is None:
                raise RuntimeError("canonical ChatHistory intent missing")
            _bind_provider_identity(
                db,
                message,
                channel=channel,
                external_account_id=str(account.external_account_id),
                external_message_id=external_message_id,
            )
        except Exception as exc:
            db.rollback()
            reason = f"provider_accepted_persistence_ambiguous: {exc}"
            try:
                _persist_delivery_attempt(
                    db, message, channel, "ambiguous", receipts, reason)
            except Exception:
                db.rollback()
            return DeliveryResult(
                ok=False,
                reason=reason,
                ambiguous=True,
                provider_receipts=receipts,
                external_message_id=external_message_id,
            )

        try:
            _persist_delivery_attempt(
                db, message, channel, "succeeded", receipts, verify=True)
        except Exception as exc:
            db.rollback()
            reason = f"provider_accepted_persistence_ambiguous: {exc}"
            try:
                _persist_delivery_attempt(
                    db, message, channel, "ambiguous", receipts, reason)
            except Exception:
                db.rollback()
            return DeliveryResult(
                ok=False,
                reason=reason,
                ambiguous=True,
                provider_receipts=receipts,
                external_message_id=external_message_id,
            )

        return DeliveryResult(
            ok=True,
            provider_receipts=receipts,
            external_message_id=external_message_id,
        )

    if text.strip():
        send_result = await adapter.send_text(account, conversation, adapter.format_outbound(text))
        await record("text", 0, send_result)
        if channel == 'whatsapp':
            health = dict((account.settings or {}).get('provider_health') or {})
            if send_result.ok:
                subscribed = health.get('waba_subscription') == 'SUBSCRIBED'
                account_repo.update_provider_health(
                    account,
                    credential_status='VALID',
                    phone_registration='REGISTERED',
                    readiness='READY' if subscribed else 'DEGRADED',
                    reconnect_needed=False,
                    last_provider_error=None,
                    last_send_at=datetime.now(timezone.utc).isoformat(),
                )
            else:
                account_repo.update_provider_health(
                    account,
                    readiness='DEGRADED',
                    last_provider_error='send_failed',
                )
        if not send_result.ok:
            logger.error(f"Failed delivering to {channel} session {session_id}: {send_result.error}")
            return DeliveryResult(
                ok=False,
                reason=send_result.error or 'send_failed',
                can_template=send_result.can_template,
                ambiguous=send_result.ambiguous,
                provider_receipts=receipts,
            )

    media_index = 0
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        file_url = attachment.get('file_url') or attachment.get('url')
        if not file_url:
            continue
        content_type = attachment.get('content_type') or 'application/octet-stream'
        try:
            provider_url = await _provider_media_url(str(file_url))
        except Exception as exc:
            reason = f"media_url_resolution_failed: {exc}"
            _persist_delivery_attempt(db, message, channel, "failed", receipts, reason)
            return DeliveryResult(ok=False, reason=reason, provider_receipts=receipts)
        media_result = await adapter.send_media(
            account,
            conversation,
            provider_url,
            content_type,
        )
        await record("media", media_index, media_result, content_type)
        media_index += 1
        if not media_result.ok:
            logger.error(
                f"Failed delivering media to {channel} session {session_id}: {media_result.error}"
            )
            return DeliveryResult(
                ok=False,
                reason=media_result.error or 'media_send_failed',
                can_template=media_result.can_template,
                ambiguous=media_result.ambiguous,
                provider_receipts=receipts,
            )

    _persist_delivery_attempt(db, message, channel, "succeeded", receipts,
                              verify=bool(payload.get("_ai_auto_authority")))
    return DeliveryResult(ok=True, provider_receipts=receipts)
