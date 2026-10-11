"""Give agent/group associations stable SQLAlchemy-Continuum row identity.

Revision ID: w387_agent_group_version_pk_001
Revises: yance_persona_session_override_003

Existing memberships and historical versions are never silently deduplicated.
Downgrade refuses to discard populated W387-created history or to reinstate an
old transaction-only primary key that would destroy same-transaction versions.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "w387_agent_group_version_pk_001"
down_revision = "yance_persona_session_override_003"
branch_labels = None
depends_on = None

_CREATED_COMMENT = "W387-created Continuum association history; downgrade only if empty"


def _pk(inspector, table):
    value = inspector.get_pk_constraint(table)
    return value["name"], tuple(value["constrained_columns"] or [])


def _check_rows(connection, table, keys):
    # Fail closed. Removing duplicates or nulls would discard actual membership
    # or audit evidence. A DBA must explicitly review conflicting legacy rows.
    cols = ", ".join(keys)
    nulls = " OR ".join(f"{column} IS NULL" for column in keys)
    if connection.exec_driver_sql(
        f"SELECT EXISTS(SELECT 1 FROM {table} WHERE {nulls})"
    ).scalar():
        raise RuntimeError(f"W387: {table} contains NULL identity; manual review required")
    if connection.exec_driver_sql(
        f"SELECT EXISTS(SELECT 1 FROM {table} GROUP BY {cols} HAVING count(*) > 1)"
    ).scalar():
        raise RuntimeError(f"W387: {table} contains duplicate identity; no automatic deletion")


def upgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if not inspector.has_table("agent_usergroup"):
        raise RuntimeError("W387: native agent_usergroup table is missing")
    op.execute("LOCK TABLE agent_usergroup IN ACCESS EXCLUSIVE MODE")
    _check_rows(connection, "agent_usergroup", ("agent_id", "group_id"))
    original_name, original_columns = _pk(inspector, "agent_usergroup")
    desired = {"agent_id", "group_id"}
    if original_columns and set(original_columns) != desired:
        raise RuntimeError("W387: unexpected agent_usergroup primary key")
    op.alter_column("agent_usergroup", "agent_id", nullable=False)
    op.alter_column("agent_usergroup", "group_id", nullable=False)
    if not original_columns:
        op.create_primary_key("agent_usergroup_pkey", "agent_usergroup",
                              ["agent_id", "group_id"])

    if not inspector.has_table("agent_usergroup_version"):
        op.create_table(
            "agent_usergroup_version",
            sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("transaction_id", sa.BigInteger(), nullable=False),
            sa.Column("operation_type", sa.SmallInteger(), nullable=False),
            sa.PrimaryKeyConstraint("agent_id", "group_id", "transaction_id",
                                    name="agent_usergroup_version_pkey"),
            comment=_CREATED_COMMENT,
        )
    else:
        op.execute("LOCK TABLE agent_usergroup_version IN ACCESS EXCLUSIVE MODE")
        inspector = sa.inspect(connection)
        pk_name, pk_columns = _pk(inspector, "agent_usergroup_version")
        if set(pk_columns) not in ({"transaction_id"},
                                   {"agent_id", "group_id", "transaction_id"}):
            raise RuntimeError("W387: unknown legacy association history primary key")
        _check_rows(connection, "agent_usergroup_version",
                    ("agent_id", "group_id", "transaction_id"))
        for column in ("agent_id", "group_id", "transaction_id"):
            op.alter_column("agent_usergroup_version", column, nullable=False)
        if set(pk_columns) != {"agent_id", "group_id", "transaction_id"}:
            op.drop_constraint(pk_name, "agent_usergroup_version",
                               type_="primary")
            op.create_primary_key("agent_usergroup_version_pkey",
                                  "agent_usergroup_version",
                                  ["agent_id", "group_id", "transaction_id"])


def downgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    op.execute("LOCK TABLE agent_usergroup IN ACCESS EXCLUSIVE MODE")
    if inspector.has_table("agent_usergroup_version"):
        op.execute("LOCK TABLE agent_usergroup_version IN ACCESS EXCLUSIVE MODE")
        inspector = sa.inspect(connection)
        table_comment = inspector.get_table_comment("agent_usergroup_version").get("text")
        pk_name, pk_columns = _pk(inspector, "agent_usergroup_version")
        if set(pk_columns) != {"agent_id", "group_id", "transaction_id"}:
            raise RuntimeError("W387: history schema changed; downgrade refused")
        if table_comment == _CREATED_COMMENT:
            if connection.exec_driver_sql(
                "SELECT EXISTS(SELECT 1 FROM agent_usergroup_version)"
            ).scalar():
                raise RuntimeError("W387: populated history must not be dropped on downgrade")
            op.drop_table("agent_usergroup_version")
        else:
            # The original Continuum schema identified versions by txn alone.
            # Multiple memberships may share a transaction after this fix,
            # so reverting that key can be unsafe; refuse rather than delete.
            _check_rows(connection, "agent_usergroup_version", ("transaction_id",))
            op.drop_constraint(pk_name, "agent_usergroup_version",
                               type_="primary")
            op.create_primary_key("agent_usergroup_version_pkey",
                                  "agent_usergroup_version", ["transaction_id"])
            op.alter_column("agent_usergroup_version", "agent_id", nullable=True)
            op.alter_column("agent_usergroup_version", "group_id", nullable=True)

    pk_name, pk_columns = _pk(sa.inspect(connection), "agent_usergroup")
    if set(pk_columns) != {"agent_id", "group_id"}:
        raise RuntimeError("W387: native association identity changed; downgrade refused")
    op.drop_constraint(pk_name, "agent_usergroup", type_="primary")
    op.alter_column("agent_usergroup", "agent_id", nullable=True)
    op.alter_column("agent_usergroup", "group_id", nullable=True)
