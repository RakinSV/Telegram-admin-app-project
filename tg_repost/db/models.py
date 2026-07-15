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


class DiscoveredChat(Base):
    """Чат, куда владелец добавил репост-бота, но ещё не подтвердил как
    целевую группу (F08-доп.) — заполняется автоматически из апдейта
    `my_chat_member`, избавляет от ручного поиска chat_id через сторонних
    ботов (см. `telegram/moderation_bot.py::_on_my_chat_member`). Строка
    удаляется, когда бот покидает чат — список в админке всегда отражает
    ТЕКУЩЕЕ членство бота, а не историю."""

    __tablename__ = "discovered_chats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    chat_type: Mapped[str] = mapped_column(String(32), default="")
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


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

    # F25 — уведомление владельцу о негативных реакциях уже отправлено (не
    # слать повторно на каждый цикл сбора статистики, пока порог превышен).
    negative_alert_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # F06/F18-доп.: настраиваемое число вариантов рерайта/обложки на пост
    # (см. `post_variants_repo.py`, таблицы ниже). Индекс АКТИВНОГО варианта
    # среди сгенерированных — денормализован сюда, а не хранится флагом на
    # самой строке варианта, чтобы `rewritten_text`/`media_path` оставались
    # единственным источником истины для publish_post/дашборда/статистики —
    # им не нужно знать о существовании вариантов вообще. NULL, если
    # вариантов не было (пост создан до этой фичи, либо генерация вернула 0).
    active_rewrite_variant_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active_cover_variant_index: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Индекс — дашборд (`webui/dashboard.py`) фильтрует/сортирует по этому
    # полю на каждой загрузке (recent_posts, todays_rewrite_tokens,
    # error_rate); без индекса это full table scan при росте `posts`,
    # выполняемый прямо в общем event loop (найдено при аудите Фазы 5,
    # см. миграцию 0006).
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
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


class PostRewriteVariant(Base):
    """Один из N сгенерированных вариантов рерайта поста (F06-доп.), число N —
    настройка `rewrite_variant_count`. Активный вариант см.
    `Post.active_rewrite_variant_index`/`rewritten_text` (денормализовано)."""

    __tablename__ = "post_rewrite_variants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"), index=True)
    variant_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class PostCoverVariant(Base):
    """Один из N сгенерированных вариантов обложки поста (F18-доп.), число N —
    настройка `cover_variant_count`. Активный вариант см.
    `Post.active_cover_variant_index`/`media_path` (денормализовано)."""

    __tablename__ = "post_cover_variants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"), index=True)
    variant_index: Mapped[int] = mapped_column(Integer)
    media_path: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


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


class TelethonSession(Base):
    """Дополнительная Telethon-сессия для распределения источников между
    несколькими аккаунтами (F26) — снижает риск ограничений на один
    аккаунт при большом числе источников.

    Основная сессия (`TG_SESSION_STRING`, единственная в Фазах 0-5) остаётся
    как есть в `secrets`/`.env` — эта таблица только для ДОПОЛНИТЕЛЬНЫХ,
    добавляемых по мере роста числа источников. `encrypted_session_string` —
    Fernet-токен тем же `WEBUI_MASTER_KEY`, что и обычные секреты (см.
    `webui/crypto.py`), никогда не отдаётся обратно в браузер.
    """

    __tablename__ = "telethon_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str] = mapped_column(String(64))
    encrypted_session_string: Mapped[str] = mapped_column(Text)
    masked_hint: Mapped[str] = mapped_column(String(16))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class AppSetting(Base):
    """Настройка приложения, заданная через веб-админку (F23, Фаза 5).

    Оверлей поверх дефолтов `.env`/`Settings` — см. `webui/settings_store.py`.
    `value` хранится как JSON-текст (строка/число/bool/список), тип — в
    `value_type`, чтобы расширение новых настроек не требовало новых колонок.
    """

    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    value: Mapped[str] = mapped_column(Text)
    value_type: Mapped[str] = mapped_column(String(16))  # int|float|bool|str|csv_list
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class Secret(Base):
    """Зашифрованный секрет, заданный через веб-админку (F23, Фаза 5).

    `encrypted_value` — Fernet-токен (см. `webui/crypto.py`), никогда не
    отдаётся обратно в браузер. `masked_hint` — то, что реально показывается
    в UI (например "••••a1b2"), считается один раз при записи.
    """

    __tablename__ = "secrets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    encrypted_value: Mapped[str] = mapped_column(Text)
    masked_hint: Mapped[str] = mapped_column(String(16))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class AdminUser(Base):
    """Учётка администратора веб-панели (F23, Фаза 5).

    Один владелец системы (см. CLAUDE.md) — таблица рассчитана на ровно одну
    строку, но названа во множественном числе на случай будущего расширения
    до нескольких пользователей (не потребует миграции схемы).
    """

    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    password_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class AuditLog(Base):
    """Журнал действий из веб-админки (F23, Фаза 5).

    Только факт изменения и его адрес (`target`), НИКОГДА значения секретов.
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor: Mapped[str] = mapped_column(String(64), default="admin")
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str | None] = mapped_column(String(255), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


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
