"""Promote provider-message identity into canonical ChatHistory columns.

Revision ID: wa_provider_identity_001
Revises: add_allow_new_chat_001, add_hc_faq_url_path_001,
         normalise_upload_prefix_001, yance_persona_history_002
"""

from alembic import op
import sqlalchemy as sa

revision = "wa_provider_identity_001"
down_revision = (
    "add_allow_new_chat_001",
    "add_hc_faq_url_path_001",
    "normalise_upload_prefix_001",
    "yance_persona_history_002",
)
branch_labels = None
depends_on = None

INDEX_NAME = "uq_chat_history_provider_identity"


def upgrade() -> None:
    op.add_column("chat_history", sa.Column("provider_channel", sa.String(), nullable=True))
    op.add_column("chat_history", sa.Column("external_account_id", sa.String(), nullable=True))
    op.add_column("chat_history", sa.Column("external_message_id", sa.String(), nullable=True))

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(sa.text("""
            WITH ranked AS (
                SELECT
                    id,
                    NULLIF(attributes->>'channel', '') AS provider_channel,
                    NULLIF(attributes->>'external_account_id', '') AS external_account_id,
                    NULLIF(attributes->>'external_message_id', '') AS external_message_id,
                    ROW_NUMBER() OVER (
                        PARTITION BY
                            attributes->>'channel',
                            attributes->>'external_account_id',
                            attributes->>'external_message_id'
                        ORDER BY id
                    ) AS rn
                FROM chat_history
                WHERE NULLIF(attributes->>'channel', '') IS NOT NULL
                  AND NULLIF(attributes->>'external_account_id', '') IS NOT NULL
                  AND NULLIF(attributes->>'external_message_id', '') IS NOT NULL
            )
            UPDATE chat_history AS target
            SET provider_channel = ranked.provider_channel,
                external_account_id = ranked.external_account_id,
                external_message_id = ranked.external_message_id
            FROM ranked
            WHERE target.id = ranked.id
              AND ranked.rn = 1
        """))
    elif bind.dialect.name == "sqlite":
        # SQLite is only used by the test harness, but keeping this branch makes
        # migration qualification deterministic if a migration test runs there.
        op.execute(sa.text("""
            WITH ranked AS (
                SELECT
                    id,
                    NULLIF(json_extract(attributes, '$.channel'), '') AS provider_channel,
                    NULLIF(json_extract(attributes, '$.external_account_id'), '') AS external_account_id,
                    NULLIF(json_extract(attributes, '$.external_message_id'), '') AS external_message_id,
                    ROW_NUMBER() OVER (
                        PARTITION BY
                            json_extract(attributes, '$.channel'),
                            json_extract(attributes, '$.external_account_id'),
                            json_extract(attributes, '$.external_message_id')
                        ORDER BY id
                    ) AS rn
                FROM chat_history
                WHERE NULLIF(json_extract(attributes, '$.channel'), '') IS NOT NULL
                  AND NULLIF(json_extract(attributes, '$.external_account_id'), '') IS NOT NULL
                  AND NULLIF(json_extract(attributes, '$.external_message_id'), '') IS NOT NULL
            )
            UPDATE chat_history
            SET provider_channel = (
                    SELECT provider_channel FROM ranked WHERE ranked.id = chat_history.id
                ),
                external_account_id = (
                    SELECT external_account_id FROM ranked WHERE ranked.id = chat_history.id
                ),
                external_message_id = (
                    SELECT external_message_id FROM ranked WHERE ranked.id = chat_history.id
                )
            WHERE id IN (SELECT id FROM ranked WHERE rn = 1)
        """))

    # Existing duplicate historical rows are preserved. Only the oldest row of
    # each identity is promoted above, after which all new writes are enforced.
    op.create_index(
        INDEX_NAME,
        "chat_history",
        ["provider_channel", "external_account_id", "external_message_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="chat_history")
    op.drop_column("chat_history", "external_message_id")
    op.drop_column("chat_history", "external_account_id")
    op.drop_column("chat_history", "provider_channel")
