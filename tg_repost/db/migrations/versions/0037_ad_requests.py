"""Заявки рекламодателей и бронь мест в сетке (F66).

Недостающее звено между F21 и F35: бриф — уже принятая к работе задача,
журнал дохода — уже полученные деньги, а как заявка приходит и чем занято
расписание, не знал никто. Владелец держал это в переписке.

Цикл: new → accepted → published (либо declined). Принятие создаёт бриф,
публикация — запись дохода, и цепочка «заявка → пост → деньги» становится
прослеживаемой.

Revision ID: 0037_ad_requests
Revises: 0036_broadcasts
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0037_ad_requests"
down_revision = "0036_broadcasts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ad_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        # Свободный текст намеренно: заявки приходят разными путями, и
        # жёсткий формат терял бы те, что в него не укладываются.
        sa.Column("advertiser", sa.String(255), nullable=False),
        sa.Column("brief_text", sa.Text(), nullable=False),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(8), nullable=False, server_default="RUB"),
        # Именно дата, а не время: сетка планируется по дням, конкретный час
        # выбирает умное расписание (F19).
        sa.Column("slot_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="new"),
        sa.Column("ad_brief_id", sa.Integer(), nullable=True),
        sa.Column("ad_revenue_id", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_ad_requests_chat_id", "ad_requests", ["chat_id"])
    op.create_index("ix_ad_requests_status", "ad_requests", ["status"])
    # Календарь занятости и проверка двойной продажи идут по этой паре.
    op.create_index("ix_ad_requests_slot", "ad_requests", ["chat_id", "slot_date"])


def downgrade() -> None:
    op.drop_index("ix_ad_requests_slot", table_name="ad_requests")
    op.drop_index("ix_ad_requests_status", table_name="ad_requests")
    op.drop_index("ix_ad_requests_chat_id", table_name="ad_requests")
    op.drop_table("ad_requests")
