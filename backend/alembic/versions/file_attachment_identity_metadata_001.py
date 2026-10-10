"""Add bounded identity metadata to canonical FileAttachment.

Revision ID: file_attachment_identity_metadata_001
Revises: client_send_intent_001, yance_persona_history_002
"""
from alembic import op
import sqlalchemy as sa

revision = "file_attachment_identity_metadata_001"
down_revision = ("client_send_intent_001", "yance_persona_history_002")
branch_labels = None
depends_on = None


def upgrade():
    # Alembic's default version_num is VARCHAR(32), but this historical
    # revision identifier is longer. Widen its existing authority column
    # before Alembic records this revision; do not rename the revision.
    op.alter_column(
        "alembic_version",
        "version_num",
        existing_type=sa.String(length=32),
        type_=sa.String(length=64),
        existing_nullable=False,
    )
    op.add_column(
        "file_attachments",
        sa.Column(
            "identity_metadata",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )


def downgrade():
    op.drop_column("file_attachments", "identity_metadata")
