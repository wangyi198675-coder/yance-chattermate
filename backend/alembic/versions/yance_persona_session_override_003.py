"""Window176 conversation-scoped Persona override on canonical SessionToAgent.

Revision ID: yance_persona_session_override_003
Revises: window205_owner_seam_001
"""
from alembic import op
import sqlalchemy as sa


revision = "yance_persona_session_override_003"
down_revision = "window205_owner_seam_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # W258/C3 already owns alembic_version VARCHAR(64); do not replay widening.
    op.add_column(
        "session_to_agents",
        sa.Column("persona_override", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("session_to_agents", "persona_override")
