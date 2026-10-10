"""Add thin Customer-owned person identity mapping.
Revision ID: yance_person_identity_001
Revises: idx_kq_org_status_001
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision = "yance_person_identity_001"
down_revision = "idx_kq_org_status_001"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("person_identities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel_account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("identity_type", sa.String(64), nullable=False), sa.Column("raw_value", sa.String(1024), nullable=False),
        sa.Column("normalized_value", sa.String(1024), nullable=False), sa.Column("provenance", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("merged_into_identity_id", postgresql.UUID(as_uuid=True), nullable=True), sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["channel_account_id"], ["channel_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["merged_into_identity_id"], ["person_identities.id"], ondelete="SET NULL"))
    for name, cols in [("ix_person_identities_organization_id",["organization_id"]),("ix_person_identities_customer_id",["customer_id"]),("ix_person_identities_channel_account_id",["channel_account_id"]),("ix_person_identities_merged_into_identity_id",["merged_into_identity_id"])]: op.create_index(name,"person_identities",cols)
    op.create_index("uix_person_identity_global_active","person_identities",["organization_id","identity_type","normalized_value"],unique=True,postgresql_where=sa.text("channel_account_id IS NULL AND merged_into_identity_id IS NULL"))
    op.create_index("uix_person_identity_account_active","person_identities",["organization_id","channel_account_id","identity_type","normalized_value"],unique=True,postgresql_where=sa.text("channel_account_id IS NOT NULL AND merged_into_identity_id IS NULL"))

def downgrade():
    for name in ["uix_person_identity_account_active","uix_person_identity_global_active","ix_person_identities_merged_into_identity_id","ix_person_identities_channel_account_id","ix_person_identities_customer_id","ix_person_identities_organization_id"]: op.drop_index(name, table_name="person_identities")
    op.drop_table("person_identities")
