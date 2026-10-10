"""Add stable manual client send intent identity.

Revision ID: client_send_intent_001
Revises: wa_provider_identity_001
Create Date: 2026-10-07
"""

from alembic import op
import sqlalchemy as sa


revision = "client_send_intent_001"
down_revision = "wa_provider_identity_001"
branch_labels = None
depends_on = None

INDEX_NAME = "uq_chat_history_org_client_send_intent"


def upgrade() -> None:
    op.add_column(
        "chat_history",
        sa.Column("client_send_intent_id", sa.Uuid(as_uuid=True), nullable=True),
    )
    op.create_index(
        INDEX_NAME,
        "chat_history",
        ["organization_id", "client_send_intent_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="chat_history")
    op.drop_column("chat_history", "client_send_intent_id")
