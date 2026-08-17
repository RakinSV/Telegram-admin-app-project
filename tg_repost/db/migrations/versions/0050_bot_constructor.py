"""Конструктор ботов: реестр ботов и сценарии-графы (F75).

КЛЮЧ УЗЛА, А НЕ `id`, — главное решение схемы. При публикации строки узлов
копируются в новую версию и получают новые `id`; переходы, ссылающиеся на
`id`, указывали бы после копирования в чужую версию. Поэтому и переходы, и
позиция человека ссылаются на `node_key`, стабильный внутри сценария.

`version = 0` зарезервирован под черновик: так «текущая правка» находится
одним и тем же условием, без поиска максимума.

Revision ID: 0050_bot_constructor
Revises: 0049_order_crypto
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0050_bot_constructor"
down_revision = "0049_order_crypto"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "managed_bots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("username", sa.String(64), nullable=True),
        sa.Column("token_encrypted", sa.Text(), nullable=False),
        sa.Column("token_hint", sa.String(32), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("username", name="uq_managed_bot_username"),
    )

    op.create_table(
        "flows",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "bot_id", sa.Integer(), sa.ForeignKey("managed_bots.id"), nullable=False,
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("trigger", sa.String(16), nullable=False, server_default="start"),
        sa.Column("trigger_value", sa.String(64), nullable=True),
        sa.Column("published_version", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_flows_bot_id", "flows", ["bot_id"])

    op.create_table(
        "flow_nodes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("flow_id", sa.Integer(), sa.ForeignKey("flows.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("node_key", sa.String(32), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("config_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("x", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("y", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint(
            "flow_id", "version", "node_key", name="uq_flow_node_key",
        ),
    )
    op.create_index("ix_flow_nodes_flow_id", "flow_nodes", ["flow_id"])
    op.create_index("ix_flow_nodes_version", "flow_nodes", ["flow_id", "version"])

    op.create_table(
        "flow_edges",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("flow_id", sa.Integer(), sa.ForeignKey("flows.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("from_key", sa.String(32), nullable=False),
        sa.Column("to_key", sa.String(32), nullable=False),
        sa.Column("condition", sa.String(16), nullable=False, server_default="always"),
        sa.Column("condition_value", sa.String(64), nullable=True),
    )
    op.create_index("ix_flow_edges_flow_id", "flow_edges", ["flow_id"])
    op.create_index("ix_flow_edges_version", "flow_edges", ["flow_id", "version"])
    op.create_index(
        "ix_flow_edges_from", "flow_edges", ["flow_id", "version", "from_key"],
    )

    op.create_table(
        "flow_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("flow_id", sa.Integer(), sa.ForeignKey("flows.id"), nullable=False),
        sa.Column("flow_version", sa.Integer(), nullable=False),
        sa.Column("bot_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("current_node_key", sa.String(32), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        sa.Column("waiting_for", sa.String(16), nullable=True),
        sa.Column("wait_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("variables_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("stop_reason", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("flow_id", "user_id", name="uq_flow_run"),
    )
    op.create_index("ix_flow_runs_flow_id", "flow_runs", ["flow_id"])
    op.create_index("ix_flow_runs_user_id", "flow_runs", ["user_id"])
    op.create_index("ix_flow_runs_status", "flow_runs", ["status"])
    op.create_index("ix_flow_runs_waiting", "flow_runs", ["status", "wait_until"])


def downgrade() -> None:
    op.drop_table("flow_runs")
    op.drop_table("flow_edges")
    op.drop_table("flow_nodes")
    op.drop_table("flows")
    op.drop_table("managed_bots")
