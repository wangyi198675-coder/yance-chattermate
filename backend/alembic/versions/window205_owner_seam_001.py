"""Window205: durable notification sound + canonical inbox state.

Revision ID: window205_owner_seam_001
Revises: file_attachment_identity_metadata_001
Create Date: 2026-10-08
"""

from alembic import op
import sqlalchemy as sa


revision = "window205_owner_seam_001"
down_revision = "file_attachment_identity_metadata_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # S02: extend the existing ChatterMate per-user notification owner.
    op.add_column(
        "user_notification_settings",
        sa.Column("sound_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    # S07: bounded same-table extension of the canonical conversation/session owner.
    op.add_column(
        "session_to_agents",
        sa.Column("is_followed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "session_to_agents",
        sa.Column("is_favourite", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "session_to_agents",
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "session_to_agents",
        sa.Column("last_read_message_id", sa.Integer(), nullable=True),
    )

    # Existing conversations were already presented as read before this durable
    # owner existed. Seed their cursor to current history so migration does not
    # manufacture historical unread badges.
    op.execute(
        """
        UPDATE session_to_agents AS s
        SET last_read_message_id = (
            SELECT MAX(ch.id)
            FROM chat_history AS ch
            WHERE ch.session_id = s.session_id
        )
        """
    )


def downgrade() -> None:
    op.drop_column("session_to_agents", "last_read_message_id")
    op.drop_column("session_to_agents", "is_archived")
    op.drop_column("session_to_agents", "is_favourite")
    op.drop_column("session_to_agents", "is_followed")
    op.drop_column("user_notification_settings", "sound_enabled")
