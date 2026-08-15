"""F57: петля обучения антиспама — очередь спорных вердиктов на разметку.

AI-фильтр объявлен fail-open: при ошибке, таймауте или невалидном ответе
сообщение проходит. Решение верное, но обратной связи не было вообще —
фильтр ошибался и не узнавал об этом, точность не росла никогда.

Теперь спорные случаи копятся здесь и уходят владельцу с кнопками
«спам / не спам», а размеченные примеры подмешиваются в промпт few-shot.

Таблица только наблюдает: поведение модерации не меняется.

Revision ID: 0003_spam_reviews
Revises: 0002_per_chat_lists
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_spam_reviews"
down_revision = "0002_per_chat_lists"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "spam_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("message_text", sa.Text(), nullable=False),
        # Хэш нормализованного текста: один спамер с пятьюдесятью одинаковыми
        # сообщениями не должен превращать лог-канал в ленту из пятидесяти
        # одинаковых запросов на разметку.
        sa.Column("text_hash", sa.String(64), nullable=False),
        # "no_verdict" — классификатор не ответил; "low_confidence" — ответил
        # «спам», но не дотянул до порога уверенности.
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("model_said_spam", sa.Boolean(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        # "spam" | "ham" | NULL (ещё не размечено).
        sa.Column("label", sa.String(8), nullable=True),
        sa.Column("labeled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_spam_reviews_chat_id", "spam_reviews", ["chat_id"])
    op.create_index("ix_spam_reviews_text_hash", "spam_reviews", ["text_hash"])
    op.create_index("ix_spam_reviews_label", "spam_reviews", ["label"])


def downgrade() -> None:
    op.drop_index("ix_spam_reviews_label", table_name="spam_reviews")
    op.drop_index("ix_spam_reviews_text_hash", table_name="spam_reviews")
    op.drop_index("ix_spam_reviews_chat_id", table_name="spam_reviews")
    op.drop_table("spam_reviews")
