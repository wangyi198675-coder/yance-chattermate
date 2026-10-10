"""Thin multi-channel identity extension for the canonical Customer person owner."""
import uuid
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, JSON, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.database import Base

class PersonIdentity(Base):
    """Typed external identity owned by one canonical Customer."""
    __tablename__ = "person_identities"
    __table_args__ = (
        Index("uix_person_identity_global_active", "organization_id", "identity_type", "normalized_value", unique=True,
              postgresql_where=text("channel_account_id IS NULL AND merged_into_identity_id IS NULL"),
              sqlite_where=text("channel_account_id IS NULL AND merged_into_identity_id IS NULL")),
        Index("uix_person_identity_account_active", "organization_id", "channel_account_id", "identity_type", "normalized_value", unique=True,
              postgresql_where=text("channel_account_id IS NOT NULL AND merged_into_identity_id IS NULL"),
              sqlite_where=text("channel_account_id IS NOT NULL AND merged_into_identity_id IS NULL")),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    customer_id = Column(UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    channel_account_id = Column(UUID(as_uuid=True), ForeignKey("channel_accounts.id", ondelete="CASCADE"), nullable=True, index=True)
    identity_type = Column(String(64), nullable=False)
    raw_value = Column(String(1024), nullable=False)
    normalized_value = Column(String(1024), nullable=False)
    provenance = Column(JSON, nullable=False, default=dict)
    merged_into_identity_id = Column(UUID(as_uuid=True), ForeignKey("person_identities.id", ondelete="SET NULL"), nullable=True, index=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
