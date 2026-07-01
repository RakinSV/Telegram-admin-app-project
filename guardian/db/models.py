"""SQLAlchemy-модели Guardian (см. guardian/GUARDIAN_PLAN.md, Фаза G1).

Отдельная `Base`/БД от `tg_repost.db.models` — независимые alembic-цепочки
(guardian/migrations vs tg_repost/db/migrations), см. guardian/db/session.py.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Базовый класс для ORM-моделей Guardian."""


class Member(Base):
    """Участник группового чата, охраняемого Guardian (G01/G05)."""

    __tablename__ = "members"
    __table_args__ = (
        UniqueConstraint("user_id", "chat_id", name="uq_members_user_chat"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    join_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    warn_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_warn_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_trusted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Warning(Base):
    """Отдельная запись о выданном предупреждении (G05)."""

    __tablename__ = "warnings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    # user_id выдавшего варн вручную, либо 'auto' — авто-варн от фильтра.
    issued_by: Mapped[str] = mapped_column(String(32), default="auto", nullable=False)


class StopWord(Base):
    """Стоп-слово фильтра ключевых слов (G03)."""

    __tablename__ = "stop_words"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    word: Mapped[str] = mapped_column(String(255), unique=True)
    added_by: Mapped[str] = mapped_column(String(32), default="auto", nullable=False)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class TrustedUser(Base):
    """Пользователь, полностью обходящий спам-/линк-фильтры (G12)."""

    __tablename__ = "trusted_users"
    __table_args__ = (
        UniqueConstraint("user_id", "chat_id", name="uq_trusted_user_chat"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    added_by: Mapped[str] = mapped_column(String(32), default="auto", nullable=False)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class ModerationLog(Base):
    """Журнал всех действий модерации — источник для /stats и лог-канала (G08/G11)."""

    __tablename__ = "moderation_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # warn | mute | kick | ban | unban | delete_msg | trust | untrust
    action: Mapped[str] = mapped_column(String(32))
    user_id: Mapped[int] = mapped_column(BigInteger)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    # user_id актёра, либо 'auto' — действие принял фильтр/система.
    actor: Mapped[str] = mapped_column(String(32), default="auto", nullable=False)


class BotConfig(Base):
    """Живой конфиг Guardian, редактируемый командами бота (G13)."""

    __tablename__ = "bot_config"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_by: Mapped[str] = mapped_column(String(32), default="auto", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class DailyStats(Base):
    """Суточная агрегация метрик модерации на чат (G11/G17)."""

    __tablename__ = "daily_stats"
    __table_args__ = (
        UniqueConstraint("date", "chat_id", name="uq_daily_stats_date_chat"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[date_type] = mapped_column(Date)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    deleted_msgs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    warnings: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    mutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    kicks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    bans: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    new_members: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    verified_members: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ai_calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ai_cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
