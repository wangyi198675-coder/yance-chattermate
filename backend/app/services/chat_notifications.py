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

from typing import Optional

from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.repositories.user import UserRepository
from app.repositories.channels import ChannelAccountRepository, ChannelConversationRepository
from app.services.notifications import ChatNotificationEvent, notify_chat_event

logger = get_logger(__name__)

# A brand-new chat belongs to nobody, so recipients are whoever could actually
# open it from the inbox. Anything narrower (e.g. the agent's groups) misses
# new chats, which usually have no group at all.
UNASSIGNED_CHAT_VIEWERS = (
    "view_all_chats",
    "manage_all_chats",
    "view_unassigned_chats",
    "super_admin",
)

CHANNEL_LABELS = {
    "web": "the web widget",
    "slack": "Slack",
    "whatsapp": "WhatsApp",
    "telegram": "Telegram",
    "messenger": "Messenger",
    "instagram": "Instagram",
    "email": "email",
}


def chat_notification_metadata(db: Session, session) -> dict:
    """Compose one inbox deep-link + canonical channel identity contract.

    Slack Workspace identity comes only from Session -> ChannelConversation ->
    ChannelAccount. Missing or inconsistent linkage leaves session_id alone;
    never recover an account from a customer, Slack user, or another workspace.
    Shared by NEW_CHAT, CHAT_ASSIGNED and both CHAT_TRANSFER paths.
    """
    metadata = {"session_id": str(session.session_id)}
    if session.channel != "slack":
        return metadata
    try:
        conversation = ChannelConversationRepository(db).get_unique_by_session(session.session_id)
        if (
            conversation is None
            or conversation.session_id != session.session_id
            or conversation.channel_type != "slack"
            or conversation.organization_id != session.organization_id
        ):
            return metadata
        account = ChannelAccountRepository(db).get_by_id(conversation.channel_account_id)
        if (
            account is None
            or account.id != conversation.channel_account_id
            or account.channel_type != "slack"
            or account.organization_id != session.organization_id
            or getattr(account, "is_active", True) is False
            or not account.external_account_id
        ):
            return metadata
        metadata.update({
            "channel_account_id": str(account.id),
            "channel_conversation_id": str(conversation.id),
            "external_account_id": account.external_account_id,
        })
    except Exception:
        # Notification identity must fail safely; no speculative workspace ID.
        logger.warning("Could not resolve canonical Slack notification identity")
    return metadata


# Preserve the Window217 internal seam while callers migrate to the public one.
_chat_route_metadata = chat_notification_metadata


async def notify_new_chat(db: Session, session) -> None:
    """Tell the team a customer started a new conversation.

    Never raises — chat creation must not fail because a push did.
    """
    try:
        if session is None or not session.organization_id:
            return

        users = UserRepository(db).get_users_with_any_permission(
            session.organization_id, UNASSIGNED_CHAT_VIEWERS
        )
        if not users:
            return

        channel = CHANNEL_LABELS.get(session.channel, session.channel or "chat")
        await notify_chat_event(
            db=db,
            user_ids=[user.id for user in users],
            event=ChatNotificationEvent.NEW_CHAT,
            title="New chat",
            message=f"A new conversation started on {channel}.",
            metadata=chat_notification_metadata(db, session),
        )
    except Exception as e:
        logger.error(f"Error notifying new chat: {e}")


async def notify_chat_assigned(db: Session, session, user_id, assigned_by: Optional[str] = None) -> None:
    """Tell a user a colleague handed them a conversation.

    Never raises, and no-ops when someone claims a chat for themselves.
    """
    try:
        if not user_id or (assigned_by and str(assigned_by) == str(user_id)):
            return

        await notify_chat_event(
            db=db,
            user_ids=[user_id],
            event=ChatNotificationEvent.CHAT_ASSIGNED,
            title="Chat assigned to you",
            message="A conversation has been assigned to you.",
            metadata=chat_notification_metadata(db, session),
        )
    except Exception as e:
        logger.error(f"Error notifying chat assignment: {e}")
