"""Замечания редактора у варианта рерайта (F40, редакция из двух агентов).

Двухагентный рерайт (журналист пишет, редактор-фактчекер рецензирует и правит,
см. rewriter/editorial.py) сохраняет замечания редактора по каждому варианту,
чтобы владелец видел их при модерации. NULL — редакция была выключена.

Revision ID: 0023_editorial_notes
Revises: 0022_target_language
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0023_editorial_notes"
down_revision = "0022_target_language"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "post_rewrite_variants",
        sa.Column("editorial_notes", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("post_rewrite_variants", "editorial_notes")
