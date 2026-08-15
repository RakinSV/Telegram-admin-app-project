"""Маркировка рекламы: erid и данные рекламодателя (F62).

Токен erid выдаёт ОРД на КРЕАТИВ, а креатив здесь — бриф: из него рождается
ровно один рекламный пост. Поэтому поля на `ad_briefs`, а не на `posts`:
пост можно перегенерировать, токен относится к согласованному креативу.

Юридическое имя и ИНН дублируются на заявке (`ad_requests`) и на брифе
намеренно. На заявке они вводятся при переговорах, на бриф копируются в
момент принятия — и дальше не меняются, даже если рекламодатель потом
переименуется. В отчёт ОРД должно уйти то, что было указано в самом посте.

Revision ID: 0042_ad_marking
Revises: 0041_funnels
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0042_ad_marking"
down_revision = "0041_funnels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ad_briefs", sa.Column("advertiser_legal_name", sa.String(255), nullable=True),
    )
    op.add_column("ad_briefs", sa.Column("advertiser_inn", sa.String(32), nullable=True))
    op.add_column("ad_briefs", sa.Column("erid", sa.String(128), nullable=True))

    op.add_column(
        "ad_requests", sa.Column("advertiser_legal_name", sa.String(255), nullable=True),
    )
    op.add_column(
        "ad_requests", sa.Column("advertiser_inn", sa.String(32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ad_requests", "advertiser_inn")
    op.drop_column("ad_requests", "advertiser_legal_name")
    op.drop_column("ad_briefs", "erid")
    op.drop_column("ad_briefs", "advertiser_inn")
    op.drop_column("ad_briefs", "advertiser_legal_name")
