"""Викторины по постам и очки участников (F43, геймификация).

Механика: бот выдаёт контент, через время спрашивает по нему, очки — за
ПРАВИЛЬНЫЙ ОТВЕТ (а не за количество сообщений: те превращаются в ферму
флуда). Вопрос делает LLM из уже проверенного редактором материала.

Таблицы живут в БД tg_repost, а не в своей: квиз делается ИЗ поста, а бот
Engage работает с этой же базой (см. engage/config.py).

Revision ID: 0025_quiz_gamification
Revises: 0024_member_origins
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0025_quiz_gamification"
down_revision = "0024_member_origins"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "quizzes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("post_id", sa.Integer(), sa.ForeignKey("posts.id"), nullable=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("options_json", sa.Text(), nullable=False),
        sa.Column("correct_index", sa.Integer(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("poll_id", sa.String(length=64), nullable=True),
        sa.Column("message_id", sa.Integer(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_quizzes_post_id", "quizzes", ["post_id"])
    op.create_index("ix_quizzes_pending", "quizzes", ["published_at"])
    op.create_index("ix_quizzes_poll", "quizzes", ["poll_id"])

    op.create_table(
        "quiz_answers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("quiz_id", sa.Integer(), sa.ForeignKey("quizzes.id"), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("option_index", sa.Integer(), nullable=False),
        sa.Column("is_correct", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("quiz_id", "user_id", name="uq_quiz_answer"),
    )
    op.create_index("ix_quiz_answers_quiz_id", "quiz_answers", ["quiz_id"])

    op.create_table(
        "user_activity",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("points", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("correct_answers", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_answers", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("streak_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_correct_date", sa.Date(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_user_activity_chat_user", "user_activity", ["chat_id", "user_id"], unique=True,
    )
    op.create_index("ix_user_activity_leaderboard", "user_activity", ["chat_id", "points"])


def downgrade() -> None:
    op.drop_index("ix_user_activity_leaderboard", table_name="user_activity")
    op.drop_index("ix_user_activity_chat_user", table_name="user_activity")
    op.drop_table("user_activity")
    op.drop_index("ix_quiz_answers_quiz_id", table_name="quiz_answers")
    op.drop_table("quiz_answers")
    op.drop_index("ix_quizzes_poll", table_name="quizzes")
    op.drop_index("ix_quizzes_pending", table_name="quizzes")
    op.drop_index("ix_quizzes_post_id", table_name="quizzes")
    op.drop_table("quizzes")
