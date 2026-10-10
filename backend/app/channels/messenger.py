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

from typing import ClassVar, List, Optional
import mimetypes
import posixpath
from urllib.parse import unquote, urlparse

from app.channels.base import InboundMessage, RetrievedMedia, SendResult
from app.channels.meta_base import (
    GRAPH_BASE, MetaBaseAdapter, download_meta_media, graph_get, graph_post,
)
from app.channels.registry import register_adapter
from app.models.channels import ChannelAccount, ChannelConversation, ChannelType
from app.core.logger import get_logger

logger = get_logger(__name__)

# Messenger send API limit
MAX_MESSAGE_LENGTH = 2000


class MessengerAdapter(MetaBaseAdapter):
    """Facebook Messenger. Instagram DM shares the same entry[].messaging[]
    envelope and send shape, so InstagramAdapter subclasses this — overriding
    only the host it talks to and the fields that name a sender."""

    channel_type: ClassVar[str] = ChannelType.MESSENGER.value
    # Instagram Login accounts hold an Instagram user token, which only
    # graph.instagram.com accepts; Page tokens only work on the Facebook graph.
    graph_base: ClassVar[str] = GRAPH_BASE
    # Graph fields on the sender node that carry a display name. Instagram user
    # nodes expose different ones, so it overrides this and _display_name.
    profile_fields: ClassVar[str] = "first_name,last_name"
    # Extra keys on a send. messaging_type is a Messenger Platform parameter and
    # is not part of Instagram's documented send body, so Instagram sends none.
    send_extras: ClassVar[dict] = {"messaging_type": "RESPONSE"}

    @staticmethod
    def _event_seconds(raw) -> Optional[int]:
        """Event time in seconds, or None if absent/unparseable.

        Messenger sends milliseconds as a number; Instagram's changes payload
        sends seconds as a string, which the old `// 1000` raised a TypeError on
        — crashing the whole webhook rather than dropping one timestamp.
        """
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return None
        # 13-digit values are milliseconds; 10-digit ones are already seconds.
        return value // 1000 if value > 10_000_000_000 else value

    def _events(self, entry: dict) -> List[dict]:
        """The messaging events on one entry. Messenger always uses messaging[];
        Instagram overrides this because it can deliver the same event under
        changes[] instead."""
        return entry.get("messaging") or []

    @staticmethod
    def _normalize_attachment(attachment: dict, timestamp) -> dict:
        """Normalize provider media without creating a second media authority.

        Provider-only provenance stays in the normalized dict; the canonical
        ChatHistory/FileAttachment path decides what is persisted where.
        """
        payload = attachment.get("payload") or {}
        provider_type = str(attachment.get("type") or "file").lower()
        url = payload.get("url") or attachment.get("url")
        provider_id = attachment.get("id") or payload.get("id")
        content_type = (attachment.get("mime_type") or payload.get("mime_type") or
                        attachment.get("content_type") or payload.get("content_type"))
        if not content_type and url:
            content_type = mimetypes.guess_type(urlparse(str(url)).path)[0]
        if not content_type:
            content_type = {
                "image": "image/*",
                "audio": "audio/*",
                "video": "video/*",
            }.get(provider_type, "application/octet-stream")
        filename = (attachment.get("name") or payload.get("name"))
        if not filename and url:
            filename = posixpath.basename(unquote(urlparse(str(url)).path)) or None
        if not filename:
            filename = f"messenger-{provider_type}"
        size = attachment.get("size") or payload.get("size") or 0
        try:
            size = int(size)
        except (TypeError, ValueError):
            size = 0
        return {
            "provider_type": provider_type,
            "provider_id": str(provider_id) if provider_id is not None else None,
            "url": url,
            "payload": payload,
            "timestamp": timestamp.isoformat() if timestamp is not None else None,
            "file_url": url,
            "filename": filename,
            "content_type": content_type,
            "file_size": size,
        }

    def parse_inbound(self, payload: dict) -> List[InboundMessage]:
        """Normalize text and attachment events while retaining the exact MID."""
        messages: List[InboundMessage] = []
        for entry in payload.get("entry", []):
            account_id = str(entry.get("id", ""))
            for event in self._events(entry):
                message = event.get("message")
                if not message or message.get("is_echo"):
                    continue
                text = message.get("text")
                timestamp = self._timestamp(self._event_seconds(event.get("timestamp")))
                attachments = [
                    self._normalize_attachment(attachment, timestamp)
                    for attachment in (message.get("attachments") or [])
                    if isinstance(attachment, dict)
                ]
                if not text and not attachments:
                    continue
                sender_id = str((event.get("sender") or {}).get("id", ""))
                if not sender_id:
                    continue
                messages.append(InboundMessage(
                    external_account_id=account_id,
                    external_conversation_id=sender_id,
                    external_user_id=sender_id,
                    external_message_id=str(message.get("mid", "")),
                    text=text,
                    attachments=attachments,
                    profile={},
                    timestamp=timestamp,
                ))
        return messages

    async def send_text(self, account: ChannelAccount, conversation: ChannelConversation, text: str) -> SendResult:
        # `me/messages` resolves to the page/account owning the access token
        return await graph_post(
            "me/messages",
            self.access_token(account),
            {
                "recipient": {"id": conversation.external_conversation_id},
                **self.send_extras,
                "message": {"text": text},
            },
            base=self.graph_base,
        )

    async def fetch_inbound_media(self, account: ChannelAccount, attachment: dict) -> Optional[RetrievedMedia]:
        url = attachment.get("url") or attachment.get("file_url")
        if not url:
            return None
        content, response_type = await download_meta_media(str(url))
        content_type = response_type or str(attachment.get("content_type") or "")
        if not content_type or content_type.endswith("/*"):
            content_type = mimetypes.guess_type(urlparse(str(url)).path)[0] or ""
        if not content_type:
            raise ValueError("Messenger media has no verifiable content type")
        filename = str(attachment.get("filename") or "messenger-media")
        if not posixpath.splitext(filename)[1]:
            filename += mimetypes.guess_extension(content_type) or ""
        return RetrievedMedia(content=content, filename=filename, content_type=content_type)

    async def send_media(self, account: ChannelAccount, conversation: ChannelConversation,
                         url: str, content_type: str) -> SendResult:
        """Send Messenger media through the existing Meta Send API transport.

        Instagram subclasses this adapter but is outside this Facebook Page
        extension, so it deliberately keeps the base unsupported behavior.
        """
        if self.channel_type != ChannelType.MESSENGER.value:
            return await super().send_media(account, conversation, url, content_type)
        mime = (content_type or "").lower()
        if mime.startswith("image/"):
            attachment_type = "image"
        elif mime.startswith("audio/"):
            attachment_type = "audio"
        elif mime.startswith("video/"):
            attachment_type = "video"
        else:
            attachment_type = "file"
        return await graph_post(
            "me/messages",
            self.access_token(account),
            {
                "recipient": {"id": conversation.external_conversation_id},
                **self.send_extras,
                "message": {
                    "attachment": {
                        "type": attachment_type,
                        "payload": {"url": url},
                    }
                },
            },
            base=self.graph_base,
        )

    async def send_typing(self, account: ChannelAccount, conversation: ChannelConversation) -> None:
        """Dismissed automatically when the reply is delivered, or after ~20s."""
        try:
            result = await graph_post(
                "me/messages",
                self.access_token(account),
                {
                    "recipient": {"id": conversation.external_conversation_id},
                    "sender_action": "typing_on",
                },
                base=self.graph_base,
            )
            if not result.ok:
                logger.debug(f"{self.channel_type} typing_on failed (non-critical): {result.error}")
        except Exception as e:
            logger.debug(f"{self.channel_type} typing_on failed (non-critical): {e}")

    def format_outbound(self, markdown: str) -> str:
        return markdown[:MAX_MESSAGE_LENGTH]

    async def fetch_profile(self, account: ChannelAccount, external_user_id: str) -> dict:
        """The customer's name, which the webhook never carries — Messenger
        sends only a PSID, so without this every customer shows as
        "Messenger user 2742…" in People.

        Best-effort: a lookup failure must not cost us the message, so it
        degrades to {} (the placeholder stays) rather than raising. Reading a
        sender's name needs no permission beyond messaging them.
        """
        ok, data = await graph_get(external_user_id, self.access_token(account),
                                   params={"fields": self.profile_fields},
                                   base=self.graph_base)
        if not ok:
            return {}
        name = self._display_name(data)
        return {"name": name} if name else {}

    @staticmethod
    def _display_name(data: dict) -> str:
        return " ".join(p for p in (data.get("first_name"), data.get("last_name")) if p).strip()


register_adapter(MessengerAdapter())
