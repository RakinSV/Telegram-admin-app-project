"""SQLAlchemy-модели и статус-машина постов (F05).

Статусы поста:

    new ──> filtered_out          (не прошёл фильтр ключевых слов, F03)
        ──> duplicate             (точный дубль по хэшу, F04)
        ──> rewriting ──> rewritten ──> pending_approval
                                            ──> approved ──> posted
                                            ──> rejected
                       ──> failed         (ошибка рерайта/публикации)

Переходы проверяются в `PostStatus.can_transition` — статус нельзя менять
произвольно, только по разрешённым рёбрам графа.
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Базовый класс для всех ORM-моделей."""


class PostStatus(str, enum.Enum):
    """Статусы поста в пайплайне (статус-машина F05)."""

    NEW = "new"
    FILTERED_OUT = "filtered_out"
    DUPLICATE = "duplicate"
    REWRITING = "rewriting"
    REWRITTEN = "rewritten"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    POSTED = "posted"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        """Конечные статусы, из которых нет переходов."""
        return self in _TERMINAL_STATUSES

    def can_transition(self, target: "PostStatus") -> bool:
        """Разрешён ли переход из текущего статуса в `target`."""
        return target in _ALLOWED_TRANSITIONS.get(self, frozenset())


_TERMINAL_STATUSES: frozenset[PostStatus] = frozenset(
    {
        PostStatus.FILTERED_OUT,
        PostStatus.DUPLICATE,
        PostStatus.REJECTED,
        PostStatus.POSTED,
    }
)

_ALLOWED_TRANSITIONS: dict[PostStatus, frozenset[PostStatus]] = {
    PostStatus.NEW: frozenset(
        {
            PostStatus.FILTERED_OUT,
            PostStatus.DUPLICATE,
            PostStatus.REWRITING,
        }
    ),
    PostStatus.REWRITING: frozenset({PostStatus.REWRITTEN, PostStatus.FAILED}),
    PostStatus.REWRITTEN: frozenset({PostStatus.PENDING_APPROVAL, PostStatus.APPROVED}),
    PostStatus.PENDING_APPROVAL: frozenset(
        {PostStatus.APPROVED, PostStatus.REJECTED, PostStatus.REWRITTEN}
    ),
    PostStatus.APPROVED: frozenset({PostStatus.POSTED, PostStatus.FAILED}),
    # failed можно вернуть в обработку (ретрай) — на rewriting.
    PostStatus.FAILED: frozenset({PostStatus.REWRITING, PostStatus.APPROVED}),
}


class PostKind(str, enum.Enum):
    """Происхождение поста — определяет, есть ли у него реальный источник.

    SOURCE — обычный репост из Telegram-канала (F02). AD — сгенерированный
    рекламный пост из брифа (F21). DIGEST — сводный пост недели (F20). Все три
    вида проходят один и тот же пайплайн модерации/публикации (F05/F07/F08);
    AD/DIGEST создаются сразу со статусом REWRITTEN, минуя NEW/дедуп — для них
    нет «оригинала» для рерайта.
    """

    SOURCE = "source"
    AD = "ad"
    DIGEST = "digest"


class InvalidStatusTransition(Exception):
    """Попытка недопустимого перехода статуса поста."""

    def __init__(self, current: PostStatus, target: PostStatus) -> None:
        super().__init__(f"Недопустимый переход статуса: {current.value} -> {target.value}")
        self.current = current
        self.target = target


class Source(Base):
    """Отслеживаемый Telegram-канал-источник (F01)."""

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_username: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    channel_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # ID канала из Telegram (заполняется listener-ом при первом резолве).
    channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Привязка стиля рерайта к источнику (F15, задел на будущее).
    style_profile: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # F12: переопределение целевых групп для источника. CSV из chat_id; если
    # пусто/NULL — пост идёт во все активные target_groups.
    target_chat_ids: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # F16: «галочка добора знаний» на источник. NULL — следовать глобальной
    # настройке ENABLE_SOURCE_ENRICHMENT, True/False — переопределить.
    enrich_sources: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    posts: Mapped[list["Post"]] = relationship(back_populates="source")


class TargetGroup(Base):
    """Целевая группа/канал для публикации (F08, расширяется в F12)."""

    __tablename__ = "target_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Post(Base):
    """Пост в пайплайне (F02, F05). Хранит оригинал, рерайт и метрики."""

    __tablename__ = "posts"
    __table_args__ = (
        UniqueConstraint("source_id", "source_message_id", name="uq_source_message"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Происхождение поста (F18-F21: AD/DIGEST не имеют реального источника).
    kind: Mapped[PostKind] = mapped_column(
        Enum(PostKind, native_enum=False, length=16),
        default=PostKind.SOURCE,
        nullable=False,
    )

    # NULL для AD/DIGEST постов — у них нет канала-источника.
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("sources.id"), nullable=True, index=True
    )
    source: Mapped["Source | None"] = relationship(back_populates="posts")

    # ID сообщения в канале-источнике (для ссылки на оригинал и анти-дубля).
    # NULL для AD/DIGEST.
    source_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    source_link: Mapped[str | None] = mapped_column(String(512), nullable=True)

    original_text: Mapped[str] = mapped_column(Text, default="")
    rewritten_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Хэш нормализованного оригинала для дедупликации (F04). NULL для AD/DIGEST
    # — дедупликация для синтетических постов не применима.
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    # F21: бриф, из которого сгенерирован рекламный пост (только для kind=AD).
    ad_brief_id: Mapped[int | None] = mapped_column(
        ForeignKey("ad_briefs.id"), nullable=True
    )

    # F13: эмбеддинг оригинала (вектор float32, упакованный в BLOB) для
    # семантического дубль-чека. NULL, если эмбеддинги выключены.
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    # Путь к скачанному медиа (если есть).
    media_path: Mapped[str | None] = mapped_column(String(512), nullable=True)

    status: Mapped[PostStatus] = mapped_column(
        Enum(PostStatus, native_enum=False, length=32),
        default=PostStatus.NEW,
        nullable=False,
        index=True,
    )
    # Причина для filtered_out / failed / rejected.
    status_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Учёт расходов на рерайт (F06).
    rewrite_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rewrite_cost: Mapped[float | None] = mapped_column(Float, nullable=True)

    # ID сообщения модерации (чтобы потом убрать кнопки) и опубликованного поста.
    moderation_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    posted_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Чат, где лежит posted_message_id (для сбора статистики F14).
    posted_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def set_status(self, target: PostStatus, reason: str | None = None) -> None:
        """Сменить статус с проверкой допустимости перехода (F05).

        Бросает `InvalidStatusTransition`, если переход не разрешён графом.
        """
        if self.status == target:
            return
        if not self.status.can_transition(target):
            raise InvalidStatusTransition(self.status, target)
        self.status = target
        if reason is not None:
            self.status_reason = reason


class PostStat(Base):
    """Снимок метрик опубликованного поста во времени (F14)."""

    __tablename__ = "post_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"), index=True)
    view_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    forward_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reaction_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class AdBrief(Base):
    """Бриф для нативной рекламы (F21): текст-задание, по которому ИИ пишет пост."""

    __tablename__ = "ad_briefs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    brief_text: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # NULL — без ограничения по числу использований.
    max_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    times_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ChannelGrowthSnapshot(Base):
    """Снимок числа подписчиков целевого канала во времени (F22)."""

    __tablename__ = "channel_growth_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    subscriber_count: Mapped[int] = mapped_column(Integer)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


def parse_chat_ids_csv(raw: str | None) -> list[int]:
    """Разобрать CSV из chat_id (поле `Source.target_chat_ids`) в список int."""
    if not raw:
        return []
    result: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            result.append(int(part))
        except ValueError:
            continue
    return result
