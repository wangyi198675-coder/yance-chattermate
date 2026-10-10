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

import mimetypes
from typing import ClassVar, List, Optional

from app.channels.base import InboundMessage, RetrievedMedia, SendResult, WindowStatus
from app.channels.constants import DEFAULT_TEMPLATE_LANGUAGE
from app.channels.meta_base import MetaBaseAdapter, download_meta_media, graph_get, graph_post
from app.channels.registry import register_adapter
from app.models.channels import ChannelAccount, ChannelConversation, ChannelType
from app.core.logger import get_logger

logger = get_logger(__name__)

# https://developers.facebook.com/docs/whatsapp/cloud-api/reference/messages
MAX_MESSAGE_LENGTH = 4096


class WhatsAppAdapter(MetaBaseAdapter):
    channel_type: ClassVar[str] = ChannelType.WHATSAPP.value
    # Outside the 24h window WhatsApp allows re-opening with an approved template
    expired_status: ClassVar[WindowStatus] = WindowStatus.TEMPLATE_REQUIRED

    def parse_inbound(self, payload: dict) -> List[InboundMessage]:
        """Normalize a WhatsApp Cloud API webhook.

        Shape: entry[].changes[].value.{metadata,contacts,messages}. Status
        callbacks (delivered/read) carry no `messages` and yield nothing.
        """
        messages: List[InboundMessage] = []
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                metadata = value.get("metadata", {})
                phone_number_id = metadata.get("phone_number_id")
                if not phone_number_id or not value.get("messages"):
                    continue
                name_by_wa_id = {
                    c.get("wa_id"): (c.get("profile") or {}).get("name")
                    for c in value.get("contacts", [])
                }
                for message in value["messages"]:
                    text = self._extract_text(message)
                    timestamp = self._timestamp(message.get("timestamp"))
                    attachment = self._normalize_media(message, timestamp)
                    if text is None and attachment is None:
                        continue
                    wa_id = message.get("from")
                    if not wa_id:
                        continue
                    messages.append(InboundMessage(
                        external_account_id=str(phone_number_id),
                        external_conversation_id=str(wa_id),
                        external_user_id=str(wa_id),
                        external_message_id=str(message.get("id", "")),
                        text=text,
                        attachments=[attachment] if attachment else [],
                        # wa_id is the customer's number in E.164-without-plus,
                        # declared verbatim (like the SMS adapters) so the one
                        # normalize_msisdn boundary owns all '+' handling.
                        profile={"name": name_by_wa_id.get(wa_id), "phone": str(wa_id)},
                        timestamp=timestamp,
                    ))
        return messages

    @staticmethod
    def _extract_text(message: dict) -> str | None:
        if message.get("type") == "text":
            return (message.get("text") or {}).get("body")
        # Button/interactive replies carry user-visible text too
        if message.get("type") == "button":
            return (message.get("button") or {}).get("text")
        if message.get("type") == "interactive":
            interactive = message.get("interactive") or {}
            for key in ("button_reply", "list_reply"):
                if key in interactive:
                    return interactive[key].get("title")
        if message.get("type") in {"image", "video", "document"}:
            return (message.get(message.get("type")) or {}).get("caption")
        return None

    @staticmethod
    def _normalize_media(message: dict, timestamp) -> Optional[dict]:
        media_type = str(message.get("type") or "").lower()
        if media_type not in {"image", "audio", "video", "document"}:
            return None
        media = message.get(media_type) or {}
        provider_id = media.get("id")
        if not provider_id:
            return None
        content_type = str(media.get("mime_type") or "application/octet-stream").lower()
        filename = media.get("filename")
        if not filename:
            filename = f"whatsapp-{media_type}{mimetypes.guess_extension(content_type) or ''}"
        return {
            "provider_type": media_type,
            "provider_id": str(provider_id),
            "payload": media,
            "timestamp": timestamp.isoformat() if timestamp else None,
            "filename": filename,
            "content_type": content_type,
            "file_size": 0,
        }

    async def fetch_inbound_media(self, account: ChannelAccount, attachment: dict) -> Optional[RetrievedMedia]:
        media_id = attachment.get("provider_id")
        if not media_id:
            return None
        token = self.access_token(account)
        ok, data = await graph_get(str(media_id), token)
        if not ok or not data.get("url"):
            raise ValueError("WhatsApp media metadata lookup failed")
        content, response_type = await download_meta_media(str(data["url"]), token)
        content_type = response_type or str(data.get("mime_type") or attachment.get("content_type") or "")
        filename = str(attachment.get("filename") or "whatsapp-media")
        if "." not in filename.rsplit("/", 1)[-1]:
            filename += mimetypes.guess_extension(content_type) or ""
        return RetrievedMedia(content=content, filename=filename, content_type=content_type)

    def conversation_state(self, inbound: InboundMessage) -> dict:
        # send_typing marks a specific message as read, so it needs the wamid of
        # the message it is replying to.
        if not inbound.external_message_id:
            return {}
        return {"last_inbound_message_id": inbound.external_message_id}

    async def send_typing(self, account: ChannelAccount, conversation: ChannelConversation) -> None:
        """Show a typing indicator. WhatsApp only offers this as part of marking
        an inbound message read, so this also blue-ticks that message. Expires
        after 25s or when the reply is delivered."""
        message_id = (conversation.extra or {}).get("last_inbound_message_id")
        if not message_id:
            return
        try:
            result = await graph_post(
                f"{account.external_account_id}/messages",
                self.access_token(account),
                {
                    "messaging_product": "whatsapp",
                    "status": "read",
                    "message_id": message_id,
                    "typing_indicator": {"type": "text"},
                },
            )
            if not result.ok:
                logger.debug(f"WhatsApp typing indicator failed (non-critical): {result.error}")
        except Exception as e:
            logger.debug(f"WhatsApp typing indicator failed (non-critical): {e}")

    async def send_text(self, account: ChannelAccount, conversation: ChannelConversation, text: str) -> SendResult:
        return await graph_post(
            f"{account.external_account_id}/messages",
            self.access_token(account),
            {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": conversation.external_conversation_id,
                "type": "text",
                "text": {"preview_url": False, "body": text},
            },
        )

    async def send_media(self, account: ChannelAccount, conversation: ChannelConversation,
                         url: str, content_type: str) -> SendResult:
        mime = (content_type or "").lower()
        if mime.startswith("image/"):
            media_type = "image"
        elif mime.startswith("audio/"):
            media_type = "audio"
        elif mime.startswith("video/"):
            media_type = "video"
        else:
            media_type = "document"
        return await graph_post(
            f"{account.external_account_id}/messages",
            self.access_token(account),
            {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": conversation.external_conversation_id,
                "type": media_type,
                media_type: {"link": url},
            },
        )

    async def send_template(self, account: ChannelAccount, conversation: ChannelConversation,
                            template_name: str, language: str = DEFAULT_TEMPLATE_LANGUAGE,
                            components: list = None) -> SendResult:
        """Send an approved template message — the only way to reach a customer
        outside the 24h window."""
        template: dict = {"name": template_name, "language": {"code": language}}
        if components:
            template["components"] = components
        return await graph_post(
            f"{account.external_account_id}/messages",
            self.access_token(account),
            {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": conversation.external_conversation_id,
                "type": "template",
                "template": template,
            },
        )

    def format_outbound(self, markdown: str) -> str:
        # WhatsApp renders *bold* / _italic_ but agent markdown (**bold**) doesn't
        # map cleanly; send as-is with the length cap to avoid mangled markup.
        return markdown[:MAX_MESSAGE_LENGTH]


register_adapter(WhatsAppAdapter())
