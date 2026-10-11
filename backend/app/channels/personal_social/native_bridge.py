"""W435: fail-closed native ChannelAdapter boundary for personal TG/WA transports.

The canonical ChannelAccount, ChannelConversation, ChatHistory, FileAttachment and
message_delivery remain the only persistent owners. Process handles below are
ephemeral and never constitute a second channel/account registry or store.
No implicit login, outbound retry, webhook exposure or provider network activity.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import ClassVar, Mapping

from app.channels.base import ChannelAdapter, InboundMessage, RetrievedMedia, SendResult
from app.channels.registry import register_adapter
from app.models.channels import ChannelAccount, ChannelConversation, ChannelType
from app.repositories.channels import ChannelAccountRepository

from .base import PersonalSocialTransportAdapter, TransportSessionStatus

PERSONAL_TYPES = frozenset({ChannelType.TELEGRAM_USER.value, ChannelType.WHATSAPP_USER.value})
MAX_MEDIA_BYTES = 16 * 1024 * 1024


class PersonalNativeError(RuntimeError):
    """Safe error code, never a provider exception containing credentials."""


def _require_account(account: ChannelAccount, channel: str) -> None:
    if account is None or account.channel_type != channel or not account.is_active:
        raise PersonalNativeError("PERSONAL_ACCOUNT_INACTIVE_OR_TYPE_MISMATCH")
    if not account.id or not account.organization_id or not account.external_account_id:
        raise PersonalNativeError("PERSONAL_ACCOUNT_IDENTITY_MISSING")


class CanonicalTelegramCustody:
    """Session secret is stored only in the existing Fernet ChannelAccount row."""

    def __init__(self, db_factory=None):
        if db_factory is None:
            from app.database import SessionLocal
            db_factory = SessionLocal
        self._db_factory = db_factory

    def _scoped_account(self, db, organization_id: str, account_id: str):
        from uuid import UUID
        try:
            uid = UUID(account_id)
        except (ValueError, TypeError) as exc:
            raise PersonalNativeError("ACCOUNT_ID_INVALID") from exc
        repo = ChannelAccountRepository(db)
        account = repo.get_by_id(uid)
        if (account is None or not account.is_active
                or str(account.organization_id) != organization_id
                or account.channel_type != ChannelType.TELEGRAM_USER.value):
            raise PersonalNativeError("SESSION_CUSTODY_SCOPE_MISMATCH")
        return repo, account

    async def load_session(self, organization_id: str, account_id: str) -> str:
        with self._db_factory() as db:
            repo, account = self._scoped_account(db, organization_id, account_id)
            secret = repo.get_credentials(account).get("gramjs_session", "")
            if not isinstance(secret, str):
                raise PersonalNativeError("SESSION_CUSTODY_CORRUPT")
            return secret

    async def save_session(self, organization_id: str, account_id: str, session: str) -> None:
        if not isinstance(session, str) or not session:
            raise PersonalNativeError("SESSION_EMPTY")
        with self._db_factory() as db:
            repo, account = self._scoped_account(db, organization_id, account_id)
            credentials = repo.get_credentials(account)
            credentials["gramjs_session"] = session
            repo.update_credentials(account, credentials)

    async def clear_session(self, organization_id: str, account_id: str) -> None:
        with self._db_factory() as db:
            repo, account = self._scoped_account(db, organization_id, account_id)
            credentials = repo.get_credentials(account)
            credentials.pop("gramjs_session", None)
            repo.update_credentials(account, credentials)


def make_personal_transport(account: ChannelAccount, *, node_executable: str,
                            private_root: str | None = None,
                            custody=None) -> PersonalSocialTransportAdapter:
    """Construct without connecting. Private audited Windows Node is mandatory."""
    if account.channel_type not in PERSONAL_TYPES:
        raise PersonalNativeError("NOT_A_PERSONAL_ACCOUNT")
    _require_account(account, account.channel_type)
    node = Path(node_executable) if node_executable else None
    if node is None or not node.is_absolute() or not node.is_file():
        raise PersonalNativeError("PRIVATE_NODE_RUNTIME_REQUIRED")

    if account.channel_type == ChannelType.TELEGRAM_USER.value:
        from .telegram_user.adapter import TelegramUserAdapter
        from app.repositories.channels.accounts import ChannelAccountRepository
        from app.database import SessionLocal
        with SessionLocal() as db:
            repository = ChannelAccountRepository(db)
            canonical = repository.get_by_id(account.id)
            if (canonical is None or not canonical.is_active
                    or canonical.channel_type != account.channel_type
                    or str(canonical.organization_id) != str(account.organization_id)
                    or canonical.external_account_id != account.external_account_id):
                raise PersonalNativeError("PERSONAL_CANONICAL_ACCOUNT_SCOPE_MISMATCH")
            config = repository.get_credentials(canonical)
        return TelegramUserAdapter(
            organization_id=str(account.organization_id),
            channel_account_id=str(account.id),
            api_id=config.get("api_id"), api_hash=config.get("api_hash", ""),
            expected_user_id=account.external_account_id,
            custody=custody or CanonicalTelegramCustody(),
            node_executable=str(node),
        )
    from .whatsapp_user.adapter import WhatsAppUserTransport
    return WhatsAppUserTransport(
        str(account.id), node_executable=str(node), private_root=private_root,
    )


class PersonalSessionOwner:
    """Only live process handles; persisted identity stays in ChannelAccount.

    An authenticated caller must explicitly authorize bind, QR and logout.
    No background auto-connect on import/startup.
    """
    def __init__(self):
        self._handles: dict[str, tuple[str, str, str, PersonalSocialTransportAdapter]] = {}

    def bind(self, account: ChannelAccount, transport: PersonalSocialTransportAdapter,
             *, user_authorized: bool = False) -> None:
        _require_account(account, account.channel_type)
        if account.channel_type not in PERSONAL_TYPES or not user_authorized:
            raise PersonalNativeError("PERSONAL_USER_AUTHORIZATION_REQUIRED")
        key = str(account.id)
        if key in self._handles:
            raise PersonalNativeError("PERSONAL_ACCOUNT_ALREADY_BOUND")
        if account.channel_type == ChannelType.TELEGRAM_USER.value:
            if (getattr(transport, "organization_id", None) != str(account.organization_id)
                    or getattr(transport, "channel_account_id", None) != key):
                raise PersonalNativeError("TRANSPORT_SCOPE_MISMATCH")
        elif getattr(transport, "account_id", None) != key:
            raise PersonalNativeError("TRANSPORT_SCOPE_MISMATCH")
        self._handles[key] = (
            account.channel_type, str(account.organization_id),
            str(account.external_account_id), transport,
        )

    def get(self, account: ChannelAccount) -> PersonalSocialTransportAdapter:
        _require_account(account, account.channel_type)
        handle = self._handles.get(str(account.id))
        if (handle is None or handle[:3] != (
                account.channel_type, str(account.organization_id),
                str(account.external_account_id))):
            raise PersonalNativeError("PERSONAL_SESSION_NOT_BOUND")
        return handle[3]

    async def status(self, account: ChannelAccount) -> TransportSessionStatus:
        try:
            transport = self.get(account)
        except PersonalNativeError:
            return TransportSessionStatus.DISCONNECTED
        return (await transport.health()).status

    async def connect(self, account: ChannelAccount, *, user_authorized: bool = False) -> None:
        if not user_authorized:
            raise PersonalNativeError("PERSONAL_USER_AUTHORIZATION_REQUIRED")
        await self.get(account).connect()

    async def begin_qr(self, account: ChannelAccount, *, user_authorized: bool = False) -> None:
        """Only an explicit user action can ask the real provider for a QR."""
        if not user_authorized:
            raise PersonalNativeError("PERSONAL_USER_AUTHORIZATION_REQUIRED")
        transport = self.get(account)
        if account.channel_type == ChannelType.TELEGRAM_USER.value:
            await transport.begin_qr_login(interactive_authorized=True)
        else:
            await transport.connect()

    async def next_auth_event(self, account: ChannelAccount):
        """Forward a real transport event; never synthesize a QR or Connected."""
        transport = self.get(account)
        if account.channel_type == ChannelType.TELEGRAM_USER.value:
            return await transport.next_login_challenge()
        async for event in transport.auth_events():
            return event
        raise PersonalNativeError("PERSONAL_AUTH_EVENT_STREAM_ENDED")

    async def reconnect(self, account: ChannelAccount, *,
                        user_authorized: bool = False) -> None:
        if not user_authorized:
            raise PersonalNativeError("PERSONAL_USER_AUTHORIZATION_REQUIRED")
        await self.get(account).reconnect()

    async def cancel_login(self, account: ChannelAccount, *,
                           user_authorized: bool = False) -> None:
        if not user_authorized:
            raise PersonalNativeError("PERSONAL_USER_AUTHORIZATION_REQUIRED")
        transport = self.get(account)
        if account.channel_type == ChannelType.WHATSAPP_USER.value:
            await transport.cancel_login()
        else:
            await transport.disconnect()

    async def logout(self, account: ChannelAccount, *, user_authorized: bool = False) -> None:
        if not user_authorized:
            raise PersonalNativeError("PERSONAL_USER_AUTHORIZATION_REQUIRED")
        transport = self.get(account)
        if account.channel_type == ChannelType.TELEGRAM_USER.value:
            await transport.logout(interactive_authorized=True)
        else:
            await transport.logout()
        self._handles.pop(str(account.id), None)

    async def disconnect(self, account: ChannelAccount) -> None:
        transport = self.get(account)
        await transport.disconnect()
        if hasattr(transport, "close"):
            await transport.close()
        self._handles.pop(str(account.id), None)


# One ephemeral process-lifetime supervisor shared by the two native adapters.
personal_sessions = PersonalSessionOwner()


def _inbound(account: ChannelAccount, event: Mapping) -> InboundMessage | None:
    """Fail-closed normalization; never trust an event to select its own tenant."""
    _require_account(account, account.channel_type)
    if account.channel_type == ChannelType.TELEGRAM_USER.value:
        if (str(event.get("organization_id")) != str(account.organization_id)
                or str(event.get("channel_account_id")) != str(account.id)
                or event.get("provider") != "telegram"
                or event.get("account_kind") != "personal"
                or event.get("from_me") is not False
                or event.get("is_customer_turn") is not True):
            raise PersonalNativeError("INBOUND_SCOPE_OR_DIRECTION_INVALID")
        peer = str(event.get("external_conversation_id") or "")
        mid = str(event.get("external_message_id") or "")
        sender = str(event.get("sender_id") or peer)
        if not mid.startswith(peer + ":"):
            raise PersonalNativeError("TELEGRAM_COMPOSITE_MESSAGE_ID_REQUIRED")
        media_ref = event.get("media_ref") if event.get("has_media") else None
        ts = event.get("created_at")
    elif account.channel_type == ChannelType.WHATSAPP_USER.value:
        from .whatsapp_user.adapter import JID_RE
        if (event.get("event") != "inbound"
                or str(event.get("accountId")) != str(account.id)
                or str(event.get("externalAccountId")) != str(account.external_account_id)
                or event.get("fromMe") is not False
                or event.get("source") != "live"):
            raise PersonalNativeError("INBOUND_SCOPE_OR_DIRECTION_INVALID")
        peer = str(event.get("externalConversationId") or "")
        if not JID_RE.fullmatch(peer):
            raise PersonalNativeError("PERSONAL_JID_INVALID")
        remote_id = str(event.get("externalMessageId") or "")
        mid = f"{peer}:{remote_id}" if remote_id else ""
        sender = str(event.get("participant") or peer)
        media_ref = event.get("mediaRef")
        ts = event.get("timestamp")
    else:
        raise PersonalNativeError("PERSONAL_CHANNEL_REQUIRED")
    if not peer or not mid or len(mid) > 500:
        raise PersonalNativeError("INBOUND_IDENTITY_REQUIRED")
    stamp = None
    if isinstance(ts, (int, float)) and ts > 0:
        stamp = datetime.fromtimestamp(ts, tz=timezone.utc)
    elif isinstance(ts, str) and ts:
        try:
            stamp = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            pass
    attachments = []
    if media_ref:
        attachments = [{
            "provider_type": str(event.get("kind") or "document"),
            "provider_id": str(media_ref), "filename": str(event.get("fileName") or "attachment"),
            "content_type": str(event.get("mime") or "application/octet-stream"),
        }]
    message = event.get("text")
    if not isinstance(message, str):
        message = None
    if not message and not attachments:
        return None
    return InboundMessage(
        external_account_id=account.external_account_id,
        external_conversation_id=peer, external_user_id=sender,
        external_message_id=mid, text=message, attachments=attachments,
        timestamp=stamp,
    )


async def ingest_live(account: ChannelAccount, event: Mapping) -> bool:
    """Reuse canonical channel_chat, but only after its receive-only gate is wired.

    Current W418 authorization does NOT cover human_routing.py; reject instead
    of accidentally triggering unsolicited AI or human-only auto-ACK sends.
    """
    if not isinstance(event, Mapping):
        raise PersonalNativeError("INBOUND_FRAME_INVALID")
    normalized = _inbound(account, event)
    if normalized is None:
        return False
    from app.services.human_routing import RECEIVE_ONLY_SOCIAL_CHANNELS
    if account.channel_type not in RECEIVE_ONLY_SOCIAL_CHANNELS:
        raise PersonalNativeError("PERSONAL_RECEIVE_ONLY_GATE_NOT_ADMITTED")
    if await personal_sessions.status(account) != TransportSessionStatus.CONNECTED:
        raise PersonalNativeError("PERSONAL_PROVIDER_NOT_CONNECTED")
    from app.services.channel_chat import process_channel_message
    await process_channel_message(account.id, normalized)
    return True


class _PersonalChannelAdapter(ChannelAdapter):
    channel_type: ClassVar[str]

    async def verify_webhook(self, headers: dict, raw_body: bytes, account) -> bool:
        return False  # personal IPC, never public HTTP webhooks

    def parse_inbound(self, payload: dict) -> list[InboundMessage]:
        return []  # only verified scoped IPC via ingest_live()

    async def send_text(self, account: ChannelAccount, conversation: ChannelConversation,
                        text: str) -> SendResult:
        # The currently authorized native message_delivery interface omits the
        # durable physical attempt id. Never invent an id or replay a send.
        return SendResult(ok=False, error="PERSONAL_CANONICAL_ATTEMPT_ID_NOT_WIRED")

    async def send_media(self, account: ChannelAccount, conversation: ChannelConversation,
                         url: str, content_type: str) -> SendResult:
        # Baileys/GramJS require canonical stored media bytes, never a public URL
        # read as a local arbitrary file or fetched from an unchecked endpoint.
        return SendResult(ok=False, error="PERSONAL_CANONICAL_MEDIA_BYTES_NOT_WIRED")

    async def fetch_inbound_media(self, account: ChannelAccount,
                                  attachment: dict) -> RetrievedMedia | None:
        if account.channel_type != self.channel_type:
            raise PersonalNativeError("PERSONAL_CHANNEL_MISMATCH")
        ref = attachment.get("provider_id")
        if not isinstance(ref, str) or not ref:
            raise PersonalNativeError("PERSONAL_MEDIA_REFERENCE_REQUIRED")
        transport = personal_sessions.get(account)
        if await transport.session_status() != TransportSessionStatus.CONNECTED:
            raise PersonalNativeError("PERSONAL_PROVIDER_NOT_CONNECTED")
        data = await transport.media(ref)
        if not isinstance(data, bytes) or not 0 < len(data) <= MAX_MEDIA_BYTES:
            raise PersonalNativeError("PERSONAL_MEDIA_SIZE_INVALID")
        return RetrievedMedia(
            content=data, filename=str(attachment.get("filename") or "attachment"),
            content_type=str(attachment.get("content_type") or "application/octet-stream"),
        )


class TelegramUserNativeAdapter(_PersonalChannelAdapter):
    channel_type = ChannelType.TELEGRAM_USER.value


class WhatsAppUserNativeAdapter(_PersonalChannelAdapter):
    channel_type = ChannelType.WHATSAPP_USER.value


register_adapter(TelegramUserNativeAdapter())
register_adapter(WhatsAppUserNativeAdapter())
