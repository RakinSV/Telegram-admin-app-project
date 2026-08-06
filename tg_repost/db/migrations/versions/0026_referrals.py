"""Реферальная программа (F42): кто кого привёл, с антинакруткой.

Реферал засчитывается не по факту перехода по ссылке, а когда приглашённый
прожил в группе N дней И написал хотя бы одно сообщение — иначе механика
превращается в ферму мультиаккаунтов.

Revision ID: 0026_referrals
Revises: 0025_quiz_gamification
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0026_referrals"
down_revision = "0025_quiz_gamification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "referrals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("inviter_user_id", sa.BigInteger(), nullable=False),
        sa.Column("invited_user_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("invited_user_id", name="uq_referral_invited"),
    )
    op.create_index("ix_referrals_chat_id", "referrals", ["chat_id"])
    op.create_index("ix_referrals_inviter", "referrals", ["inviter_user_id"])


def downgrade() -> None:
    op.drop_index("ix_referrals_inviter", table_name="referrals")
    op.drop_index("ix_referrals_chat_id", table_name="referrals")
    op.drop_table("referrals")
