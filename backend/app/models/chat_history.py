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

from sqlalchemy import Column, Integer, String, JSON, ForeignKey, TIMESTAMP, func, UUID, Interval, Float, Index, text
from sqlalchemy.orm import relationship
from app.core.encryption import EncryptedText
from app.database import Base


class ChatHistory(Base):
    __tablename__ = "chat_history"
    __table_args__ = (
        # Every read of a conversation filters by session_id and orders by
        # (created_at, id) — the inbox previews, get_session_history, the AI's
        # context window. Declared here as well as in the migration so autogenerate
        # never proposes dropping it and the sqlite test schema matches Postgres.
        Index('ix_chat_history_session_created', 'session_id',
              text('created_at DESC'), text('id DESC')),
        # Durable external-message identity. Nullable columns keep widget/internal
        # messages valid while provider-backed inbound rows become restart-safe.
        Index(
            'uq_chat_history_provider_identity',
            'provider_channel', 'external_account_id', 'external_message_id',
            unique=True,
        ),
        # Manual agent sends are claimed before any file materialization. The
        # database is the concurrency authority for transport retries/replays.
        # Both PostgreSQL and SQLite allow multiple NULLs in a unique index, so
        # historical/inbound/system rows need no synthetic client intent.
        Index(
            'uq_chat_history_org_client_send_intent',
            'organization_id', 'client_send_intent_id',
            unique=True,
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(UUID(as_uuid=True), ForeignKey(
        "organizations.id", ondelete="SET NULL"), nullable=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey(
        "users.id", ondelete="SET NULL"), nullable=True)
    customer_id = Column(UUID(as_uuid=True), ForeignKey(
        "customers.id", ondelete="SET NULL"), nullable=True)
    agent_id = Column(UUID(as_uuid=True), ForeignKey(
        "agents.id", ondelete="SET NULL"), nullable=True)
    session_id = Column(UUID(as_uuid=True), ForeignKey("session_to_agents.session_id"), nullable=True)
    client_send_intent_id = Column(UUID(as_uuid=True), nullable=True)
    # Encrypted at rest — see app.core.encryption. Storage stays text, so rows
    # written before the change read back as plaintext until the backfill lands.
    message = Column(EncryptedText, nullable=False)
    # 'user', 'bot', or 'agent'
    message_type = Column(String, nullable=False)
    # Provider identity is promoted out of JSON so the database, not Redis or
    # process memory, can enforce exactly-once persistence across restarts.
    provider_channel = Column(String, nullable=True)
    external_account_id = Column(String, nullable=True)
    external_message_id = Column(String, nullable=True)
    attributes = Column(JSON, default={})
    sentiment_label = Column(String, nullable=True)  # 'positive', 'neutral', 'negative'
    sentiment_score = Column(Float, nullable=True)  # -1.0 to 1.0
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(),
                        onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="chat_histories")
    customer = relationship("Customer", back_populates="chat_histories")
    agent = relationship("Agent", back_populates="chat_histories")
    organization = relationship("Organization", back_populates="chat_histories")
    session_assignment = relationship("SessionToAgent")

