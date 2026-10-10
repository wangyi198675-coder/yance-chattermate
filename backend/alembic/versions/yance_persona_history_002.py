"""Add SQLAlchemy-Continuum history for Agent.instructions only.

Revision ID: yance_persona_history_002
Revises: yance_person_identity_001
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "yance_persona_history_002"
down_revision = "yance_person_identity_001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "transaction",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("remote_addr", sa.String(length=50), nullable=True),
        sa.Column("issued_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "agents_version",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column("transaction_id", sa.BigInteger(), nullable=False),
        sa.Column("end_transaction_id", sa.BigInteger(), nullable=True),
        sa.Column("operation_type", sa.SmallInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id", "transaction_id"),
    )
    op.create_index("ix_agents_version_transaction_id", "agents_version", ["transaction_id"])
    op.create_index("ix_agents_version_end_transaction_id", "agents_version", ["end_transaction_id"])
    op.create_index("ix_agents_version_operation_type", "agents_version", ["operation_type"])
    op.create_index("ix_agents_version_pk_transaction_id", "agents_version", ["id", "transaction_id"])
    op.create_index("ix_agents_version_pk_validity", "agents_version", ["id", "transaction_id", "end_transaction_id"])


def downgrade():
    for name in [
        "ix_agents_version_pk_validity",
        "ix_agents_version_pk_transaction_id",
        "ix_agents_version_operation_type",
        "ix_agents_version_end_transaction_id",
        "ix_agents_version_transaction_id",
    ]:
        op.drop_index(name, table_name="agents_version")
    op.drop_table("agents_version")
    op.drop_table("transaction")
