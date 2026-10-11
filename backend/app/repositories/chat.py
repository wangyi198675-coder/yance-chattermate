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

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from weakref import WeakValueDictionary

from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from app.models.chat_history import ChatHistory
from app.models.file_attachment import FileAttachment
from app.models.customer import Customer
from uuid import UUID
from sqlalchemy import func, or_, select, text, and_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql import case
from app.models.agent import Agent
from app.models.session_to_agent import SessionToAgent, SessionStatus
from app.repositories.channels import ChannelConversationRepository
from app.core.logger import get_logger
from app.channels.constants import is_widget_channel
from app.models.user import User
from app.repositories.customer import CustomerRepository
from app.models.schemas.people import project_person_profile
from sqlalchemy.orm import joinedload
from datetime import datetime
from pydantic import BaseModel
from app.core.s3 import get_s3_signed_url
from app.core.config import settings
from app.services.sentiment import analyze_sentiment, compute_session_sentiment

logger = get_logger(__name__)

# Production PostgreSQL uses a database advisory lock below. SQLite does not
# implement advisory locks, so tests/dev use a weak process-local mutex only as
# a dialect fallback; ChatHistory remains the durable completion authority.
_sqlite_client_send_locks: WeakValueDictionary[int, asyncio.Lock] = WeakValueDictionary()


class DuplicateProviderMessage(Exception):
    """The canonical ChatHistory row for this provider message already exists."""


class ClientSendIntentConflict(Exception):
    """A reused client send intent disagrees with its canonical action."""


class ChatRepository:
    def __init__(self, db: Session):
        self.db = db

    def has_customer_messages(self, session_id: UUID | str) -> bool:
        """Whether the customer has said anything in this session yet.

        The widget opens its session on socket connect, before the visitor
        types, so this is what distinguishes a real new chat from someone
        merely opening the chat window.
        """
        if isinstance(session_id, str):
            session_id = UUID(session_id)
        return self.db.query(ChatHistory.id).filter(
            ChatHistory.session_id == session_id,
            ChatHistory.message_type == 'user'
        ).first() is not None

    def get_message_count_for_period(
        self,
        org_id: UUID | str,
        start_date: datetime,
        end_date: datetime
    ) -> int:
        """
        Get the total number of bot messages for an organization within a specific date range.
        Only counts messages with message_type='bot'.
        
        Args:
            org_id: Organization ID
            start_date: Start date of the period
            end_date: End date of the period
            
        Returns:
            int: Total number of bot messages in the period
        """
        if isinstance(org_id, str):
            org_id = UUID(org_id)
            
        try:
            # Build filter conditions
            conditions = [
                ChatHistory.organization_id == org_id,
                ChatHistory.message_type == 'bot'  # Only count bot messages
            ]
            
            # Add date range conditions if they are not None
            if start_date is not None:
                conditions.append(ChatHistory.created_at >= start_date)
            if end_date is not None:
                conditions.append(ChatHistory.created_at <= end_date)
            
            count = self.db.query(func.count(ChatHistory.id))\
                .filter(and_(*conditions))\
                .scalar()
            return count or 0
        except Exception as e:
            logger.error(f"Error getting message count: {str(e)}")
            return 0

    def claim_or_get_client_send_intent(
        self,
        message_data: Dict[str, Any],
        client_send_intent_id: UUID | str,
        action_kind: str,
    ) -> tuple[ChatHistory, bool]:
        """Atomically claim one manual-send intent or return its canonical row.

        The unique (organization_id, client_send_intent_id) index is the
        concurrency authority. A SAVEPOINT contains a losing INSERT so an
        IntegrityError does not poison the caller's outer Session transaction.
        The winning claim is committed before file bytes or provider delivery
        can occur, making retries/reconnect replays converge on one row.
        """
        if not client_send_intent_id:
            raise ValueError("client_send_intent_id is required")
        if not action_kind or not str(action_kind).strip():
            raise ValueError("client send action kind is required")

        payload = dict(message_data)
        org_value = payload.get("organization_id")
        session_value = payload.get("session_id")
        if not org_value or not session_value:
            raise ValueError("organization_id and session_id are required for client send intent")

        organization_id = org_value if isinstance(org_value, UUID) else UUID(str(org_value))
        canonical_session_id = (
            session_value if isinstance(session_value, UUID) else UUID(str(session_value))
        )
        intent_id = (
            client_send_intent_id
            if isinstance(client_send_intent_id, UUID)
            else UUID(str(client_send_intent_id))
        )
        canonical_action_kind = str(action_kind).strip()

        payload["organization_id"] = organization_id
        payload["session_id"] = canonical_session_id
        payload["client_send_intent_id"] = intent_id
        for field in ("user_id", "customer_id", "agent_id"):
            if payload.get(field) is not None and not isinstance(payload[field], UUID):
                payload[field] = UUID(str(payload[field]))
        payload["attributes"] = {
            **(payload.get("attributes") or {}),
            "client_send_action_kind": canonical_action_kind,
        }

        # Serialize all canonical sends for a person against cross-session
        # inbound and relationship evidence mutations on the existing Customer.
        # This is row locking, not a second send/intent owner.
        if self.db.get_bind().dialect.name == "postgresql" and payload.get("customer_id"):
            self.db.query(Customer.id).filter(
                Customer.id == payload["customer_id"],
                Customer.organization_id == organization_id,
            ).with_for_update().first()
        candidate = ChatHistory(**payload)
        try:
            with self.db.begin_nested():
                self.db.add(candidate)
                self.db.flush()
        except IntegrityError as exc:
            existing = self.db.query(ChatHistory).filter(
                ChatHistory.organization_id == organization_id,
                ChatHistory.client_send_intent_id == intent_id,
            ).first()
            if existing is None:
                raise
            existing_action_kind = (existing.attributes or {}).get(
                "client_send_action_kind"
            )
            if (
                existing.session_id != canonical_session_id
                or existing_action_kind != canonical_action_kind
            ):
                raise ClientSendIntentConflict(
                    "client_send_intent_id already belongs to another session/action"
                ) from exc
            return existing, False

        # The claim must be durable before any external side effect such as file
        # materialization or provider delivery.
        self.db.commit()
        self.db.refresh(candidate)
        return candidate, True

    @asynccontextmanager
    async def client_send_execution_guard(self, message_id: int):
        """Serialize downstream completion for one canonical client-send row.

        PostgreSQL session advisory locks are held on a dedicated connection, so
        commits performed by FileAttachment/session/message_delivery owners do not
        release the guard. A process crash closes that connection and therefore
        releases the lock automatically; a replay can then resume the same row.
        """
        bind = self.db.get_bind()
        if bind.dialect.name == "postgresql":
            # The application owns a synchronous SQLAlchemy Engine. Keep the
            # dedicated advisory-lock Connection on one worker thread for its
            # complete lifetime so connect/round-trips/close never block the
            # asyncio event loop and the Connection is never shared across
            # threads. This is an execution boundary only; PostgreSQL remains
            # the lock authority and process/connection death releases the
            # session advisory lock automatically.
            executor = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="client-send-pg-guard",
            )
            loop = asyncio.get_running_loop()
            connection = None
            acquired = False
            connect_future = None
            lock_future = None

            async def settle_executor() -> None:
                """Finish any in-flight DB work, release the lock, and retire the worker."""
                nonlocal connection, acquired, connect_future, lock_future
                try:
                    try:
                        # The outer task awaits executor futures through shield().
                        # If it is cancelled mid-connect/query, the synchronous DB
                        # call therefore keeps running and this cleanup task can
                        # recover its result without losing the Connection handle.
                        if connection is None and connect_future is not None:
                            connection = await connect_future
                            connect_future = None
                        if (
                            connection is not None
                            and not acquired
                            and lock_future is not None
                        ):
                            acquired = bool(await lock_future)
                            lock_future = None
                    finally:
                        if connection is not None:
                            try:
                                if acquired:
                                    def unlock() -> None:
                                        connection.execute(
                                            text(
                                                "SELECT pg_advisory_unlock(:lock_id)"
                                            ),
                                            {"lock_id": int(message_id)},
                                        )

                                    await loop.run_in_executor(executor, unlock)
                            finally:
                                await loop.run_in_executor(
                                    executor, connection.close
                                )
                finally:
                    # ThreadPoolExecutor.shutdown(wait=True) joins its worker.
                    # Joining on the asyncio thread is exactly the cancellation
                    # stall this guard must avoid, so perform the join elsewhere
                    # and await it asynchronously until the dedicated worker is
                    # fully retired.
                    await asyncio.to_thread(
                        executor.shutdown,
                        wait=True,
                        cancel_futures=True,
                    )

            async def wait_for_settlement(cleanup_task) -> None:
                # shield() prevents repeated caller cancellation from cancelling
                # settlement. Re-deliver cancellation only after the DB lock,
                # Connection and dedicated executor have actually been retired.
                cancellation = None
                while True:
                    try:
                        await asyncio.shield(cleanup_task)
                        break
                    except asyncio.CancelledError as exc:
                        cancellation = exc
                        if cleanup_task.done():
                            break
                cleanup_task.result()
                if cancellation is not None:
                    raise cancellation

            try:
                connect_future = loop.run_in_executor(executor, bind.connect)
                connection = await asyncio.shield(connect_future)
                connect_future = None

                def try_lock() -> bool:
                    return bool(connection.execute(
                        text("SELECT pg_try_advisory_lock(:lock_id)"),
                        {"lock_id": int(message_id)},
                    ).scalar_one())

                # pg_try_advisory_lock itself is non-blocking. A losing
                # contender yields before its next database attempt.
                while not acquired:
                    lock_future = loop.run_in_executor(executor, try_lock)
                    acquired = await asyncio.shield(lock_future)
                    lock_future = None
                    if not acquired:
                        await asyncio.sleep(0.05)
                yield
            finally:
                cleanup_task = asyncio.create_task(settle_executor())
                await wait_for_settlement(cleanup_task)
            return

        # SQLite has no cross-process advisory lock. This fallback exists only
        # for local/dev/tests; production PostgreSQL remains the concurrency owner.
        lock = _sqlite_client_send_locks.get(int(message_id))
        if lock is None:
            lock = asyncio.Lock()
            _sqlite_client_send_locks[int(message_id)] = lock
        async with lock:
            yield

    def mark_client_send_completed(self, message_id: int) -> None:
        """Persist that all required downstream work reached a terminal result."""
        self.update_message_attributes(message_id, {"client_send_completed": True})

    def create_message(self, message_data: Dict[str, Any]) -> ChatHistory:
        """Create a canonical chat message and any existing file projections."""
        provider_identity = None
        try:
            message_data = dict(message_data)
            attachments = message_data.pop("attachments", []) or []
            # Convert any Pydantic models in attributes to dict
            if 'attributes' in message_data:
                attributes = message_data['attributes']
                if 'shopify_output' in attributes and attributes['shopify_output'] is not None:
                    if isinstance(attributes['shopify_output'], BaseModel):
                        attributes['shopify_output'] = attributes['shopify_output'].dict()
                    elif isinstance(attributes['shopify_output'], dict):
                        # If it's already a dict, ensure all nested objects are serialized
                        if 'products' in attributes['shopify_output']:
                            products = attributes['shopify_output']['products']
                            attributes['shopify_output']['products'] = [
                                p.dict() if isinstance(p, BaseModel) else p 
                                for p in products
                            ]

            # External provider identity is duplicated into real columns only
            # when all three parts exist. JSON stays as audit/projection data;
            # the unique index on these columns is the canonical dedupe owner.
            attributes = message_data.get('attributes') or {}
            provider_identity = tuple(
                str(attributes.get(key) or '').strip()
                for key in ('channel', 'external_account_id', 'external_message_id')
            )
            if all(provider_identity):
                message_data['provider_channel'] = provider_identity[0]
                message_data['external_account_id'] = provider_identity[1]
                message_data['external_message_id'] = provider_identity[2]
            else:
                provider_identity = None
            
            # Convert string UUIDs to UUID objects
            for field in ['organization_id', 'user_id', 'customer_id', 'agent_id', 'session_id']:
                if field in message_data and message_data[field] is not None:
                    if isinstance(message_data[field], str):
                        message_data[field] = UUID(message_data[field])

            # Analyze sentiment for customer messages ('user' type)
            if message_data.get('message_type') == 'user' and message_data.get('message'):
                try:
                    label, score = analyze_sentiment(message_data['message'])
                    message_data['sentiment_label'] = label
                    message_data['sentiment_score'] = score
                except Exception as e:
                    logger.error(f"Error analyzing message sentiment: {str(e)}")

            # Cross-session Relationship revisions must not acquire a new
            # message between final authority validation and physical send.
            # Both inbound and bot persistence share this canonical row lock.
            if self.db.get_bind().dialect.name == "postgresql" and message_data.get("customer_id"):
                self.db.query(Customer.id).filter(
                    Customer.id == message_data["customer_id"],
                    Customer.organization_id == message_data.get("organization_id"),
                ).with_for_update().first()
            message = ChatHistory(**message_data)
            self.db.add(message)
            # One transaction owns the canonical message and FileAttachment
            # projections, so media never needs a second persistence service.
            if attachments:
                self.db.flush()
            attachment_rows = []
            for attachment_index, attachment in enumerate(attachments):
                if not isinstance(attachment, dict):
                    continue
                file_url = attachment.get("file_url") or attachment.get("url")
                if not file_url:
                    continue
                try:
                    file_size = int(attachment.get("file_size") or 0)
                except (TypeError, ValueError):
                    file_size = 0
                file_row = FileAttachment(
                    file_url=str(file_url),
                    filename=str(attachment.get("filename") or "attachment"),
                    content_type=str(attachment.get("content_type") or "application/octet-stream"),
                    file_size=file_size,
                    chat_history_id=message.id,
                    organization_id=message.organization_id,
                    uploaded_by_customer_id=(
                        message.customer_id if message.message_type == "user" else None
                    ),
                    uploaded_by_user_id=(
                        message.user_id if message.message_type == "agent" else None
                    ),
                )
                self.db.add(file_row)
                attachment_rows.append((attachment_index, attachment, file_row))

            # Voice transcripts are a projection on the canonical message,
            # linked to the exact canonical FileAttachment id created above.
            # The audio bytes themselves remain solely in FileAttachment storage.
            if attachment_rows:
                self.db.flush()
                voice_transcriptions = []
                allowed_voice_keys = (
                    "status", "text", "language", "language_probability",
                    "duration_seconds", "provider", "model", "error",
                )
                for attachment_index, source, file_row in attachment_rows:
                    transcript = source.get("voice_transcription")
                    if not isinstance(transcript, dict):
                        continue
                    projected = {
                        key: transcript.get(key)
                        for key in allowed_voice_keys
                        if transcript.get(key) is not None
                    }
                    projected.update({
                        "attachment_id": file_row.id,
                        "attachment_index": attachment_index,
                        "filename": file_row.filename,
                    })
                    voice_transcriptions.append(projected)
                if voice_transcriptions:
                    message.attributes = {
                        **(message.attributes or {}),
                        "voice_transcriptions": voice_transcriptions,
                    }
            self.db.commit()
            self.db.refresh(message)

            # One canonical inbound persistence owner serves Widget, social
            # receive-only, and ChatAgent. Never infer a reply before the real
            # customer row commits; an optional learning projection must never
            # abort or duplicate that committed inbound.
            if message.message_type == "user":
                try:
                    from app.services.yance_reply_runtime import finalize_response_outcome
                    finalize_response_outcome(self.db, message.id)
                except Exception:
                    self.db.rollback()
                    logger.exception("Reply learning inbound finalization unavailable")

            # Update session-level sentiment after saving a customer message
            if message_data.get('message_type') == 'user' and message_data.get('session_id'):
                try:
                    self._update_session_sentiment(message_data['session_id'])
                except Exception as e:
                    logger.error(f"Error updating session sentiment: {str(e)}")

            return message
        except IntegrityError as e:
            self.db.rollback()
            if provider_identity and self.provider_message_exists(*provider_identity):
                logger.info(
                    "Skipping duplicate provider message %s/%s/%s",
                    *provider_identity,
                )
                raise DuplicateProviderMessage(provider_identity) from e
            raise
        except Exception as e:
            logger.error(f"Error creating message: {str(e)}")
            self.db.rollback()
            raise

    def provider_message_exists(self, channel: str, external_account_id: str,
                                external_message_id: str) -> bool:
        """Database-authoritative provider-message claim lookup."""
        if not channel or not external_account_id or not external_message_id:
            return False
        return self.db.query(ChatHistory.id).filter(
            ChatHistory.provider_channel == channel,
            ChatHistory.external_account_id == external_account_id,
            ChatHistory.external_message_id == external_message_id,
        ).first() is not None

    def update_message_attributes(self, message_id: int, attributes: Dict[str, Any]) -> None:
        """Merge keys into a message's attributes JSON (e.g. delivery_status)."""
        try:
            message = self.db.query(ChatHistory).filter(ChatHistory.id == message_id).first()
            if not message:
                return
            message.attributes = {**(message.attributes or {}), **attributes}
            self.db.commit()
        except Exception as e:
            logger.error(f"Error updating message attributes: {str(e)}")
            self.db.rollback()

    def mark_delivery_failed(self, message_id: int, reason: Optional[str]) -> None:
        """Flag a stored message as never delivered to the customer.

        Sole writer of delivery_status, which therefore only ever holds a
        failure reason — the inbox treats its presence as "not delivered".
        """
        self.update_message_attributes(message_id, {'delivery_status': reason or 'failed'})

    def _channel_account_id(self, channel: Optional[str], session_id) -> Optional[str]:
        """Which connected account a channel conversation belongs to, so the
        inbox can call account-scoped endpoints (e.g. sending a template).

        Looked up separately rather than joined into the chat-detail query:
        session_id is not unique on channel_conversations, so an outer join
        would multiply that query's groups. Only fires for channel sessions,
        and get_chat_detail fetches one session at a time.
        """
        if is_widget_channel(channel):
            return None
        conversation = ChannelConversationRepository(self.db).get_by_session(session_id)
        return str(conversation.channel_account_id) if conversation else None

    def get_latest_bot_message(self, session_id: str | UUID) -> Optional[ChatHistory]:
        """Most recent bot reply in a session.

        The bot path persists its reply inside ChatAgent.get_response and never
        returns the row, so callers that need to annotate it (e.g. recording a
        delivery failure) read it back with this. Only 'bot' qualifies —
        'agent' is a human's message, never the AI's.

        Ordered by id, not created_at: created_at is a server default with
        coarse resolution, so two replies in the same second would tie and
        resolve arbitrarily.

        Caveat: this identifies the latest reply, not a specific one. Two turns
        processed concurrently on one session can read back each other's row.
        """
        if isinstance(session_id, str):
            session_id = UUID(session_id)
        return (
            self.db.query(ChatHistory)
            .filter(
                ChatHistory.session_id == session_id,
                ChatHistory.message_type == 'bot',
            )
            .order_by(ChatHistory.id.desc())
            .first()
        )

    def get_recent_context_messages(
        self, session_id: str | UUID, limit: int = 10
    ) -> List[ChatHistory]:
        """Return the canonical recent transcript in chronological order.

        ChatHistory is encrypted at rest and remains the only message truth.
        This window is fed directly to Agno 3.x instead of duplicating the
        transcript into Agno's sessions/runs tables.
        """
        if isinstance(session_id, str):
            session_id = UUID(session_id)
        rows = (
            self.db.query(ChatHistory)
            .filter(ChatHistory.session_id == session_id)
            .order_by(ChatHistory.created_at.desc(), ChatHistory.id.desc())
            .limit(limit)
            .all()
        )
        rows.reverse()
        return rows

    def _update_session_sentiment(self, session_id) -> None:
        """Recompute and update the overall session sentiment from customer messages."""
        try:
            if isinstance(session_id, str):
                session_id = UUID(session_id)

            # Get all customer message sentiments for this session
            messages = self.db.query(
                ChatHistory.sentiment_score,
                ChatHistory.sentiment_label
            ).filter(
                ChatHistory.session_id == session_id,
                ChatHistory.message_type == 'user',
                ChatHistory.sentiment_score.isnot(None)
            ).all()

            scores = [m.sentiment_score for m in messages]
            labels = [m.sentiment_label for m in messages]

            overall_label, overall_score = compute_session_sentiment(scores, labels)

            if overall_label is not None:
                session = self.db.query(SessionToAgent).filter(
                    SessionToAgent.session_id == session_id
                ).first()
                if session:
                    session.sentiment_label = overall_label
                    session.sentiment_score = overall_score
                    self.db.commit()
        except Exception as e:
            logger.error(f"Error updating session sentiment: {str(e)}")
            self.db.rollback()

    async def get_session_history(self, session_id: str | UUID) -> List[ChatHistory]:
        """Get chat history for a session with joined relationships"""
        if isinstance(session_id, str):
            session_id = UUID(session_id)
        
        messages = (
            self.db.query(ChatHistory)
            .options(
                joinedload(ChatHistory.user),
                joinedload(ChatHistory.agent),
                joinedload(ChatHistory.attachments)
            )
            .filter(ChatHistory.session_id == session_id)
            # id breaks ties — see get_last_messages.
            .order_by(ChatHistory.created_at.asc(), ChatHistory.id.asc())
            .all()
        )
        
        # Generate signed URLs for S3 attachments
        if settings.S3_FILE_STORAGE:
            for message in messages:
                if message.attachments:
                    for attachment in message.attachments:
                        if attachment.file_url:
                            try:
                                signed_url = await get_s3_signed_url(attachment.file_url)
                                # Store the signed URL in a temporary attribute
                                attachment.file_url = signed_url
                            except Exception as e:
                                logger.error(f"Error generating signed URL for attachment {attachment.id}: {str(e)}")
                                
        
        return messages

    async def get_session_history_page(
        self,
        session_id: str | UUID,
        *,
        limit: int = 50,
        direction: str = 'latest',
        cursor_created_at: Optional[datetime] = None,
        cursor_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Fetch one bounded canonical ChatHistory page using a stateless keyset.

        Persisted order is always (created_at ASC, id ASC). The query may run
        newest-first for the latest/older paths so the existing composite index
        stays useful, but rows returned to callers are chronological.
        """
        if isinstance(session_id, str):
            session_id = UUID(session_id)
        if direction not in {'latest', 'older', 'newer'}:
            raise ValueError('Unsupported history page direction')
        if direction != 'latest' and (cursor_created_at is None or cursor_id is None):
            raise ValueError('History cursor requires created_at and id')

        bounded_limit = max(1, min(int(limit), 200))
        query = (
            self.db.query(ChatHistory)
            .options(
                joinedload(ChatHistory.user),
                joinedload(ChatHistory.agent),
                joinedload(ChatHistory.attachments),
            )
            .filter(ChatHistory.session_id == session_id)
        )

        if direction == 'older':
            query = query.filter(
                or_(
                    ChatHistory.created_at < cursor_created_at,
                    and_(
                        ChatHistory.created_at == cursor_created_at,
                        ChatHistory.id < cursor_id,
                    ),
                )
            )
            query = query.order_by(ChatHistory.created_at.desc(), ChatHistory.id.desc())
        elif direction == 'newer':
            query = query.filter(
                or_(
                    ChatHistory.created_at > cursor_created_at,
                    and_(
                        ChatHistory.created_at == cursor_created_at,
                        ChatHistory.id > cursor_id,
                    ),
                )
            )
            query = query.order_by(ChatHistory.created_at.asc(), ChatHistory.id.asc())
        else:
            query = query.order_by(ChatHistory.created_at.desc(), ChatHistory.id.desc())

        rows = query.limit(bounded_limit + 1).all()
        has_more = len(rows) > bounded_limit
        rows = rows[:bounded_limit]

        if direction in {'latest', 'older'}:
            rows.reverse()

        if settings.S3_FILE_STORAGE:
            for message in rows:
                if not message.attachments:
                    continue
                for attachment in message.attachments:
                    if not attachment.file_url:
                        continue
                    try:
                        attachment.file_url = await get_s3_signed_url(attachment.file_url)
                    except Exception as e:
                        logger.error(
                            f"Error generating signed URL for attachment {attachment.id}: {str(e)}"
                        )

        next_cursor = None
        if has_more and rows:
            boundary = rows[-1] if direction == 'newer' else rows[0]
            next_cursor = {
                'created_at': boundary.created_at,
                'id': boundary.id,
            }

        return {
            'messages': rows,
            'has_more': has_more,
            'next_cursor': next_cursor,
        }

    def _project_history_message(self, msg: ChatHistory) -> Dict[str, Any]:
        """Project one canonical row without creating another message owner."""
        attributes = msg.attributes if isinstance(msg.attributes, dict) else msg.attributes
        is_product = isinstance(attributes, dict) and bool(attributes.get('shopify_output'))
        projected: Dict[str, Any] = {
            'id': msg.id,
            'client_send_intent_id': msg.client_send_intent_id,
            'session_id': msg.session_id,
            'message': msg.message,
            'message_type': 'product' if is_product else msg.message_type,
            'created_at': msg.created_at,
            'attributes': attributes,
            'shopify_output': attributes.get('shopify_output') if is_product else None,
            'end_chat': attributes.get('end_chat') if isinstance(attributes, dict) else None,
            'end_chat_reason': attributes.get('end_chat_reason') if isinstance(attributes, dict) else None,
            'end_chat_description': attributes.get('end_chat_description') if isinstance(attributes, dict) else None,
            'agent_name': msg.agent.name if msg.agent else None,
            'user_name': msg.user.full_name if msg.user else None,
        }

        if msg.attachments:
            projected['attachments'] = [
                {
                    'id': attachment.id,
                    'filename': attachment.filename,
                    'file_url': attachment.file_url,
                    'content_type': attachment.content_type,
                    'file_size': attachment.file_size,
                }
                for attachment in msg.attachments
            ]
        return projected

    def get_last_messages(self, session_ids: List[UUID]) -> Dict[UUID, str]:
        """Map each session to its most recent message, decrypted.

        One query for the whole page rather than one per session, and the single
        definition of "most recent" — created_at is transaction time, so messages
        written together share it exactly and id has to break the tie.
        """
        if not session_ids:
            return {}

        ranked = (
            select(
                ChatHistory.session_id,
                ChatHistory.message,
                func.row_number().over(
                    partition_by=ChatHistory.session_id,
                    order_by=(ChatHistory.created_at.desc(), ChatHistory.id.desc()),
                ).label('rank')
            )
            .where(ChatHistory.session_id.in_(session_ids))
            .subquery()
        )

        rows = self.db.execute(
            select(ranked.c.session_id, ranked.c.message).where(ranked.c.rank == 1)
        ).all()
        return {session_id: message for session_id, message in rows}

    def get_user_history(self, user_id: str | UUID) -> List[ChatHistory]:
        """Get chat history for a user"""
        if isinstance(user_id, str):
            user_id = UUID(user_id)
            
        return self.db.query(ChatHistory).filter(
            ChatHistory.user_id == user_id
        ).order_by(ChatHistory.created_at.desc()).all()

    def get_recent_chats(
        self,
        skip: int = 0,
        limit: int = 20,
        agent_id: Optional[str | UUID] = None,
        status: Optional[str] = None,
        user_id: Optional[str | UUID] = None,
        user_groups: Optional[List[str]] = None,
        include_unassigned: bool = False,
        organization_id: Optional[str | UUID] = None,
        user_name: Optional[str] = None,
        filter_user_id: Optional[str | UUID] = None,
        customer_email: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        inbox_filter: Optional[str] = None,
    ) -> List[dict]:
        """Get recent chat overviews grouped by conversation"""
        # Convert string IDs to UUID if needed
        if agent_id and isinstance(agent_id, str):
            agent_id = UUID(agent_id)
        if user_id and isinstance(user_id, str):
            user_id = UUID(user_id)
        if organization_id and isinstance(organization_id, str):
            organization_id = UUID(organization_id)
        if user_groups:
            user_groups = [UUID(g) if isinstance(g, str) else g for g in user_groups]

        query = self.db.query(
            Customer.id.label('customer_id'),
            Customer.email.label('customer_email'),
            Customer.full_name.label('customer_full_name'),
            Customer.meta_data.label('customer_meta_data'),
            Agent.id.label('agent_id'),
            Agent.name.label('agent_name'),
            Agent.display_name.label('agent_display_name'),
            Agent.ai_replies_enabled.label('agent_ai_replies_enabled'),
            SessionToAgent.status.label('status'),
            SessionToAgent.channel.label('channel'),
            SessionToAgent.group_id.label('group_id'),
            SessionToAgent.is_followed.label('followed'),
            SessionToAgent.is_favourite.label('favourite'),
            SessionToAgent.is_archived.label('archived'),
            SessionToAgent.last_read_message_id.label('last_read_message_id'),
            func.sum(case((and_(
                ChatHistory.message_type == 'user',
                or_(
                    SessionToAgent.last_read_message_id.is_(None),
                    ChatHistory.id > SessionToAgent.last_read_message_id,
                ),
            ), 1), else_=0)).label('unread_count'),
            # Who is handling the chat. Without these the list cannot tell an
            # AI-handled conversation from one a human has taken over — the
            # detail view has always known, the overview never did.
            SessionToAgent.user_id.label('user_id'),
            User.full_name.label('user_name'),
            func.max(ChatHistory.created_at).label('updated_at'),
            func.count(ChatHistory.id).label('message_count'),
            SessionToAgent.session_id.label('session_id')
        ).join(
            Agent, ChatHistory.agent_id == Agent.id
        ).join(
            Customer, ChatHistory.customer_id == Customer.id
        ).join(
            SessionToAgent, ChatHistory.session_id == SessionToAgent.session_id
        ).outerjoin(
            User, SessionToAgent.user_id == User.id
        )

        # Filter conditions
        if agent_id:
            query = query.filter(Agent.id == agent_id)
        
        # Filter by status if provided
        if status and status != 'all':
            # The HTTP API exposes lower-case values, while SQLAlchemy persists
            # SessionStatus enum NAMES (OPEN/TRANSFERRED/CLOSED) on PostgreSQL.
            # Bind enum members, never raw client strings: raw 'open' fails with
            # invalid input value for enum sessionstatus in production.
            status_values = [SessionStatus(raw.strip().lower())
                             for raw in status.split(',')]
            if len(status_values) == 1:
                query = query.filter(SessionToAgent.status == status_values[0])
            else:
                query = query.filter(SessionToAgent.status.in_(status_values))
        
        # Filter by organization
        if organization_id:
            query = query.filter(SessionToAgent.organization_id == organization_id)
        
        # S07 filtering happens BEFORE keyset/offset pagination. A client-only
        # archived filter can silently hide archived rows beyond the first page.
        if inbox_filter in {'all', 'unread', 'followed', 'favourite'}:
            query = query.filter(SessionToAgent.is_archived.is_(False))
        elif inbox_filter == 'archived':
            query = query.filter(SessionToAgent.is_archived.is_(True))
        if inbox_filter == 'followed':
            query = query.filter(SessionToAgent.is_followed.is_(True))
        elif inbox_filter == 'favourite':
            query = query.filter(SessionToAgent.is_favourite.is_(True))
        elif inbox_filter == 'unread':
            query = query.having(func.sum(case((and_(
                ChatHistory.message_type == 'user',
                or_(SessionToAgent.last_read_message_id.is_(None),
                    ChatHistory.id > SessionToAgent.last_read_message_id),
            ), 1), else_=0)) > 0)

        # Filter by user name
        if user_name:
            query = query.filter(User.full_name.ilike(f'%{user_name}%'))
        
        # Filter by specific user ID (for agent dropdown)
        if filter_user_id:
            if isinstance(filter_user_id, str):
                filter_user_id = UUID(filter_user_id)
            query = query.filter(SessionToAgent.user_id == filter_user_id)
        
        # Filter by customer email
        if customer_email:
            query = query.filter(Customer.email.ilike(f'%{customer_email}%'))
        
        # Filter by date range
        if date_from:
            query = query.filter(ChatHistory.created_at >= date_from)
        if date_to:
            query = query.filter(ChatHistory.created_at <= date_to)
        
        # Scope to what this user may see: their own sessions, their groups'
        # queue, and — with view_unassigned_chats — the unclaimed AI queue.
        # Callers who may see everything pass none of these.
        visibility = []
        if user_id:
            visibility.append(SessionToAgent.user_id == user_id)
        if user_groups:
            visibility.append(SessionToAgent.group_id.in_(user_groups))
        if include_unassigned:
            # Nobody has taken it yet — the AI is still handling it. group_id
            # is irrelevant: a chat transferred to another group is still
            # claimable, and it is exactly what "unassigned" means.
            visibility.append(SessionToAgent.user_id.is_(None))

        if visibility:
            query = query.filter(or_(*visibility))

        # Group by and order
        query = query.group_by(
            Customer.id,
            Customer.email,
            Customer.full_name,
            Agent.id,
            Agent.name,
            Agent.display_name,
            Agent.ai_replies_enabled,
            SessionToAgent.status,
            SessionToAgent.channel,
            SessionToAgent.group_id,
            SessionToAgent.is_followed,
            SessionToAgent.is_favourite,
            SessionToAgent.is_archived,
            SessionToAgent.last_read_message_id,
            SessionToAgent.user_id,
            User.full_name,
            SessionToAgent.session_id
        ).order_by(
            # Create a custom ordering to prioritize transferred conversations
            # Using direct SQL expression for the CASE statement with uppercase status values
            text("CASE WHEN session_to_agents.status = 'TRANSFERRED' THEN 0 "
                 "WHEN session_to_agents.status = 'OPEN' THEN 1 "
                 "ELSE 2 END"),
            # Then order by most recent activity
            func.max(ChatHistory.created_at).desc()
        ).offset(skip).limit(limit)

        results = query.all()
        # Previews are fetched for the returned page only. Inlining them as a
        # correlated subquery would evaluate once per session in the org, since the
        # LIMIT applies after grouping.
        last_messages = self.get_last_messages([r.session_id for r in results])

        return [{
            'customer': {
                'id': r.customer_id,
                'email': CustomerRepository.display_email(r.customer_email),
                'full_name': r.customer_full_name,
                'profile': project_person_profile(r.customer_meta_data)
            },
            'agent': {
                'id': r.agent_id,
                'name': r.agent_name,
                'display_name': r.agent_display_name,
                'ai_replies_enabled': r.agent_ai_replies_enabled
            },
            'last_message': last_messages.get(r.session_id),
            'updated_at': r.updated_at,
            'message_count': r.message_count,
            'status': r.status,
            'channel': r.channel,
            'group_id': str(r.group_id) if r.group_id else None,
            'user_id': r.user_id,
            'user_name': r.user_name,
            'session_id': r.session_id,
            'followed': r.followed,
            'favourite': r.favourite,
            'archived': r.archived,
            'last_read_message_id': r.last_read_message_id,
            'unread_count': int(r.unread_count or 0),
        } for r in results]

    def session_belongs_to_organization(
        self,
        session_id: str | UUID,
        organization_id: str | UUID,
    ) -> bool:
        if isinstance(session_id, str):
            session_id = UUID(session_id)
        if isinstance(organization_id, str):
            organization_id = UUID(organization_id)
        return self.db.query(SessionToAgent.session_id).filter(
            SessionToAgent.session_id == session_id,
            SessionToAgent.organization_id == organization_id,
        ).first() is not None

    async def check_session_access(
        self,
        session_id: str | UUID,
        user_id: Optional[str | UUID],
        user_groups: Optional[List[str]],
        include_unassigned: bool = False
    ) -> bool:
        """Check if user has access to a chat session.

        Mirrors the visibility filter in get_recent_chats — the two must agree,
        or a session shows in the list and 404s when opened. A None user_id
        means "this caller has no assigned-chat grant"; it must never be
        compared against session.user_id, since both being NULL would silently
        hand over every unclaimed session.
        """
        if isinstance(session_id, str):
            session_id = UUID(session_id)
        if isinstance(user_id, str):
            user_id = UUID(user_id)

        session = (
            self.db.query(SessionToAgent)
            .filter(SessionToAgent.session_id == session_id)
            .first()
        )

        if not session:
            return False

        if include_unassigned and session.user_id is None:
            return True

        if user_id is not None and session.user_id == user_id:
            return True

        return bool(
            session.group_id and user_groups and str(session.group_id) in user_groups
        )

    async def get_chat_detail(
        self,
        session_id: str | UUID,
        org_id: str | UUID,
        message_limit: int = 50,
    ) -> Optional[dict]:
        """Get detailed chat information for a session"""
        if isinstance(session_id, str):
            session_id = UUID(session_id)
        if isinstance(org_id, str):
            org_id = UUID(org_id)

        result = (
            self.db.query(
                Customer.id.label('customer_id'),
                Customer.email.label('customer_email'),
                Customer.full_name.label('customer_full_name'),
                Customer.meta_data.label('customer_meta_data'),
                Agent.id.label('agent_id'),
                Agent.name.label('agent_name'),
                Agent.display_name.label('agent_display_name'),
                Agent.ai_replies_enabled.label('agent_ai_replies_enabled'),
                SessionToAgent.status.label('status'),
                SessionToAgent.channel.label('channel'),
                SessionToAgent.group_id.label('group_id'),
                SessionToAgent.is_followed.label('followed'),
                SessionToAgent.is_favourite.label('favourite'),
                SessionToAgent.is_archived.label('archived'),
                SessionToAgent.last_read_message_id.label('last_read_message_id'),
                SessionToAgent.session_id.label('session_id'),
                SessionToAgent.user_id.label('user_id'),
                User.full_name.label('user_name'),
                func.min(ChatHistory.created_at).label('created_at'),
                func.max(ChatHistory.created_at).label('updated_at')
            )
            .join(Agent, ChatHistory.agent_id == Agent.id)
            .join(Customer, ChatHistory.customer_id == Customer.id)
            .join(SessionToAgent, ChatHistory.session_id == SessionToAgent.session_id)
            .outerjoin(User, SessionToAgent.user_id == User.id)
            .filter(
                ChatHistory.session_id == session_id,
                SessionToAgent.organization_id == org_id
            )
            .group_by(
                # Customer.meta_data is deliberately NOT grouped: Postgres' `json` type
                # has no equality operator, so grouping by it raises "could not identify
                # an equality operator for type json". Customer.id (the PK) is already
                # grouped, so Postgres' functional-dependency rule lets other columns of
                # the same table (email, full_name, meta_data) be selected ungrouped.
                Customer.id,
                Customer.email,
                Customer.full_name,
                Agent.id,
                Agent.name,
                Agent.display_name,
                Agent.ai_replies_enabled,
                SessionToAgent.status,
                SessionToAgent.channel,
                SessionToAgent.group_id,
                SessionToAgent.is_followed,
                SessionToAgent.is_favourite,
                SessionToAgent.is_archived,
                SessionToAgent.last_read_message_id,
                SessionToAgent.session_id,
                SessionToAgent.user_id,
                User.full_name
            )
            .first()
        )

        if not result:
            return None

        # Only the latest bounded canonical page belongs in the initial detail.
        history_page = await self.get_session_history_page(
            session_id,
            limit=message_limit,
            direction='latest',
        )
        messages_list = [
            self._project_history_message(msg)
            for msg in history_page['messages']
        ]
        
        # Convert result to dict
        return {
            'customer': {
                'id': result.customer_id,
                'email': CustomerRepository.display_email(result.customer_email),
                'full_name': result.customer_full_name,
                'meta_data': result.customer_meta_data,
                'profile': project_person_profile(result.customer_meta_data)
            },
            'agent': {
                'id': result.agent_id,
                'name': result.agent_name,
                'display_name': result.agent_display_name,
                'ai_replies_enabled': result.agent_ai_replies_enabled
            },
            'status': result.status,
            'channel': result.channel,
            'channel_account_id': self._channel_account_id(result.channel, result.session_id),
            'group_id': str(result.group_id) if result.group_id else None,
            'session_id': result.session_id,
            'user_id': result.user_id,
            'user_name': result.user_name,
            'created_at': result.created_at,
            'updated_at': result.updated_at,
            'followed': result.followed,
            'favourite': result.favourite,
            'archived': result.archived,
            'last_read_message_id': result.last_read_message_id,
            'messages': messages_list,
            'has_older': history_page['has_more'],
            'older_cursor': history_page['next_cursor'],
        }
