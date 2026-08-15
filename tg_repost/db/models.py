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

ИЗВЕСТНОЕ РАСХОЖДЕНИЕ СХЕМЫ (выявлено сверкой миграций с моделями на полном
аудите). Ранние миграции создают служебные колонки (`created_at`/`updated_at`/
`added_at`/`captured_at`, `posts.original_text`) как NULLABLE, тогда как
модели объявляют их обязательными: `Mapped[datetime]` без `| None` — это
`nullable=False`. На практике NULL там не появляется, потому что все вставки
идут через ORM с `default=`, а восстановление из бэкапа файловое (целиком
подменяет .db, не вставляет строки). Практическое следствие одно: тесты
создают схему из моделей и потому работают на схеме СТРОЖЕ продовой.
Исправление требует rebuild ~18 таблиц (в SQLite нет ALTER COLUMN) — цена
выше пользы для системы одного владельца, поэтому расхождение принято
осознанно, а не забыто. Новые таблицы объявлять согласованно.
"""

from __future__ import annotations

import enum
from datetime import date as date_type
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from tg_repost.languages import DEFAULT_LANGUAGE


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
    # NEW из rewriting — ручное восстановление поста, зависшего в обработке
    # (процесс упал/перезапустился посреди рерайта): сам он оттуда уже не
    # выйдет, пайплайн разбирает только NEW. FILTERED_OUT — страж от выдумок:
    # уже начав обработку, поняли, что рерайтить нечего (только заголовок,
    # статья не прочитана), см. scheduler/jobs.py::rewrite_new_posts.
    PostStatus.REWRITING: frozenset(
        {PostStatus.REWRITTEN, PostStatus.FAILED, PostStatus.NEW, PostStatus.FILTERED_OUT}
    ),
    # failed из rewritten — это «текст готов, но доставить его на модерацию не
    # удалось» (Telegram стабильно отвергает подпись/медиа). Без этого перехода
    # такой пост оставался в rewritten навсегда и загораживал очередь отправки,
    # см. moderation_bot.send_pending_for_approval. Ретрай — через failed →
    # rewriting, как и у остальных сбоев.
    PostStatus.REWRITTEN: frozenset(
        {PostStatus.PENDING_APPROVAL, PostStatus.APPROVED, PostStatus.FAILED}
    ),
    PostStatus.PENDING_APPROVAL: frozenset(
        {PostStatus.APPROVED, PostStatus.REJECTED, PostStatus.REWRITTEN}
    ),
    PostStatus.APPROVED: frozenset({PostStatus.POSTED, PostStatus.FAILED}),
    # failed можно вернуть в обработку (ретрай) кнопкой «Повторить» в админке,
    # когда причина сбоя уже неактуальна (таймаут модели, разовый сбой сети).
    # Куда именно — зависит от того, докуда пост дошёл: если рерайт готов и
    # сорвалась только доставка, он возвращается сразу в `rewritten`, и
    # заново платить за модель и обложки не нужно; если текста нет — в `new`,
    # на полный проход. Без этих рёбер упавший пост не воскрешался ничем.
    PostStatus.FAILED: frozenset(
        {PostStatus.REWRITING, PostStatus.APPROVED, PostStatus.NEW, PostStatus.REWRITTEN}
    ),
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
    # F33: опрос — публикуется через `bot.send_poll`, не `send_message`/
    # `send_photo`. Как AD/DIGEST, создаётся сразу REWRITTEN (нет реального
    # источника/рерайта) — идёт по тому же пайплайну модерации/публикации.
    POLL = "poll"
    # F55: повтор уже выстрелившего поста. Текст берётся готовым у оригинала
    # (`recycled_from_id`), рерайт не нужен — создаётся сразу REWRITTEN.
    # ВАЖНО: кандидатами на повтор считаются ТОЛЬКО посты вида SOURCE, иначе
    # повтор сам стал бы кандидатом и один и тот же текст крутился бы в ленте
    # бесконечно.
    RECYCLE = "recycle"


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
    # Откуда берём материал: "telegram" (по умолчанию, NULL у старых строк)
    # или "rss". Всё, что ниже по течению — стиль, цели, добор источников,
    # формат публикации — работает одинаково для обоих: разница только в
    # том, кто кладёт пост в очередь (listener или rss/poller).
    kind: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    # Для telegram — @username канала. Для rss — URL ленты: колонка уже
    # UNIQUE + NOT NULL, а лента и опознаётся своим адресом, так что
    # заводить второе поле-идентификатор значило бы держать две копии одного
    # ключа с риском их расхождения. Человеческое имя — в channel_title.
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
    # F54: фильтр слов на уровне источника. CSV, NULL — следовать глобальным
    # спискам (та же тристейт-семантика, что у `enrich_sources`).
    #
    # СЕМАНТИКА ДВУХ СПИСКОВ РАЗНАЯ, и это не небрежность:
    # * стоп-слова СКЛАДЫВАЮТСЯ с глобальными. Стоп-список защитный, и
    #   молчаливое отключение глобальной защиты для одного источника —
    #   опаснее, чем лишняя строгость.
    # * обязательные слова ЗАМЕЩАЮТ глобальные. Тут объединение не ужесточило
    #   бы, а ослабило: срабатывает «хотя бы одно», поэтому чем длиннее
    #   список, тем больше проходит. Замена даёт ленте её собственную тему.
    filter_stop_words: Mapped[str | None] = mapped_column(Text, nullable=True)
    filter_required_words: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Формат публикации: "post" — обычный пост в ленте (как было всегда),
    # "article" — полная статья на Telegraph, а в канал уходит тизер со
    # ссылкой. Выбор именно на источнике: у одного канала посты-новости,
    # у другого — лонгриды с кодом, и один глобальный флаг тут не работает.
    # NULL/пусто = "post".
    post_format: Mapped[str | None] = mapped_column(String(16), nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    posts: Mapped[list["Post"]] = relationship(back_populates="source")


class TargetGroup(Base):
    """Целевая группа/канал для публикации (F08, расширяется в F12)."""

    __tablename__ = "target_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Может ли бот СЕЙЧАС слать сообщения сюда — как и DiscoveredChat.can_post,
    # но актуализируется и ПОСЛЕ того, как чат уже стал целью (F08-доп.,
    # раунд 3 аудита ведения групп): раньше можно было потерять права бота
    # на уже добавленную цель, и предупреждение оставалось только в discovered
    # (который эту цель уже не показывает — она добавлена). Синхронизируется
    # из того же апдейта my_chat_member, что и DiscoveredChat (см.
    # targets_repo.sync_can_post, telegram/moderation_bot.py::_on_my_chat_member).
    can_post: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # Язык публикации именно ЭТОЙ группы (коды см. tg_repost/languages.py).
    # Решение «на каком языке говорить» принадлежит аудитории группы, а не
    # источнику: один источник кормит и русские, и англоязычные каналы.
    # Следствие для пайплайна: пост, уходящий в группы с разными языками,
    # требует по рерайту на каждый язык (см. scheduler/jobs.py).
    language: Mapped[str] = mapped_column(
        String(8), default=DEFAULT_LANGUAGE, server_default=DEFAULT_LANGUAGE, nullable=False,
    )
    # F28 (аудит ведения групп): защищать ли этот чат Guardian'ом (капча,
    # антиспам, антирейд, варны) — раньше Guardian был жёстко привязан к
    # ОДНОЙ группе через GUARDIAN_GROUP_ID в .env, независимо от того, что
    # target_groups поддерживает несколько целей публикации. Список
    # chat_id с use_guardian=True синхронизируется в guardian.bot_config
    # (ключ protected_chat_ids) при каждом изменении — см.
    # webui/crud_routes.py::targets_toggle_guardian.
    use_guardian: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # F28.10: может ли Guardian СЕЙЧАС реально модерировать этот чат (админ +
    # право ограничивать участников) — независимо от `use_guardian` (галочка
    # "включить защиту" может стоять, а прав ещё/уже нет — например владелец
    # забыл выдать админку боту Guardian). NULL, пока Guardian ни разу не
    # видел статус в этом чате (отличать от "точно знаем, что прав нет").
    # Синхронизируется из Guardian-процесса (`guardian/handlers/chat_member.py`)
    # НАПРЯМУЮ в эту таблицу — тот же кросс-пакетный приём, что и
    # `webui/guardian_routes.py` в другую сторону (см. его docstring).
    guardian_can_moderate: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
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
    # Может ли бот СЕЙЧАС слать сообщения в этот чат (F08-доп., аудит ведения
    # групп) — значимо только для каналов: Bot API отдаёт `can_post_messages`
    # именно для них, обычный участник канала никогда не может постить от
    # своего имени. NULL — не применимо (группы/супергруппы, где участник
    # обычно и так может писать) или не удалось определить. False — реальное
    # предупреждение в /targets ПЕРЕД тем, как чат добавят как цель, а не
    # постфактум через FAILED-статус первого же поста.
    can_post: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
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
    # index=True не декоративный: по нему идёт дедупликация RSS-записей
    # (`rss/poller.py::_known_guids` — WHERE source_link IN (...) на каждом
    # опросе каждой ленты). В миграции 0021 индекс есть, а в модели не был —
    # то есть тесты, создающие схему из моделей, проверяли дедуп на схеме БЕЗ
    # индекса, отличной от продовой (найдено сверкой схем на аудите).
    source_link: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)

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

    # F51: сюжет, к которому относится пост. Одна новость приходит из многих
    # источников; вместо того чтобы выбрасывать повторы, мы собираем их в
    # кластер. NULL — пост пока сам по себе (сюжет заводится только со
    # второго участника, плодить кластеры из одного поста бессмысленно).
    cluster_id: Mapped[int | None] = mapped_column(
        ForeignKey("story_clusters.id", ondelete="SET NULL"), nullable=True, index=True
    )
    cluster: Mapped["StoryCluster | None"] = relationship(
        back_populates="posts", foreign_keys=[cluster_id]
    )

    # F55: если это повтор — id оригинала. Самоссылка на `posts`, а не отдельная
    # таблица: связь один-к-одному и без собственных атрибутов, заводить под
    # неё таблицу было бы церемонией. Она же служит признаком «этот пост уже
    # повторяли»: наличие строки с `recycled_from_id == X` закрывает X от
    # повторного отбора, отдельного флага для этого не нужно.
    recycled_from_id: Mapped[int | None] = mapped_column(
        ForeignKey("posts.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # F72: «не раньше этой даты». NULL — как было всегда: пост уходит в
    # ближайший слот расписания. Это НЕ точное время публикации: конкретный
    # час по-прежнему выбирают слоты (F11) и умное расписание (F19), а здесь
    # хранится только запрет выходить раньше срока — «анонс в понедельник,
    # не раньше».
    scheduled_for: Mapped[date_type | None] = mapped_column(
        Date, nullable=True, index=True
    )
    # F72: кто одобрил. Нужно не для отчётности, а для второго уровня
    # согласования: без имени невозможно отличить «одобрил редактор» от
    # «одобрил владелец».
    approved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # F72: ждёт подтверждения владельца. Отдельный флаг, а не новый статус:
    # статус-машина F05 работает годами, и вносить в неё состояние ради
    # необязательной проверки — рисковать публикацией ради церемонии.
    # Публикатор просто не берёт посты с этим флагом.
    needs_owner_approval: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="0"
    )

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

    # Что именно прочитала модель по ссылке из поста (F16-доп.). Без этого
    # владелец, глядя на слабый рерайт, не мог отличить «модель работала по
    # полной статье и всё равно вышло плохо» от «статью не удалось открыть, и
    # переписан один короткий тизер» — а это диаметрально разные починки
    # (править промпт против чинить доступ к сайту). NULL = переход не
    # выполнялся или ни одна ссылка не открылась.
    link_source_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    link_content_chars: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # URL статьи на Telegraph, если пост публиковался в формате «статья».
    # NULL — обычный пост. Хранится, чтобы показать ссылку при модерации и
    # чтобы повторная публикация не создавала вторую копию страницы.
    telegraph_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

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

    # F33: только для kind=POLL — вопрос лежит в `rewritten_text` (как текст
    # у обычного поста), варианты ответа — JSON-массив строк здесь (Bot API
    # ограничивает 2-10 вариантов по 1-100 символов, не проверяем на уровне
    # модели — валидация на входе, в веб-роуте).
    poll_options: Mapped[str | None] = mapped_column(Text, nullable=True)
    poll_is_anonymous: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    poll_allows_multiple_answers: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

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


class StoryCluster(Base):
    """Сюжет — одна новость, пришедшая из нескольких источников (F51).

    Раньше повтор просто помечался `duplicate` и пропадал. Но повтор из
    НЕЗАВИСИМОГО источника — это не мусор, а подтверждение: именно на нём
    работает фактчек редакции (F40) и сравнение версий (F24). Поэтому
    повторы не выбрасываются, а собираются вокруг первого пришедшего поста.

    Кластер заводится только со ВТОРОГО участника: пока новость пришла из
    одного места, сюжета ещё нет, и строка в таблице была бы шумом.
    """

    __tablename__ = "story_clusters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Пост, который пришёл первым и идёт в публикацию. Остальные участники
    # живут при нём как источники.
    #
    # Намеренно БЕЗ ForeignKey, хотя ссылается на posts.id: обратная связь
    # posts.cluster_id -> story_clusters.id уже есть, и пара FK замкнула бы
    # цикл, на котором SQLAlchemy роняет create_all (разорвать его можно
    # только через use_alter, а SQLite не умеет ALTER ... ADD CONSTRAINT).
    # Целостность тут и так обеспечена: значение проставляется в одном месте
    # (`clusters_repo.attach_to_cluster`) из id только что сохранённого поста.
    primary_post_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    # Денормализованный счётчик участников (включая главный). Держим полем, а
    # не COUNT(*) на каждый показ: карточка модерации дёргает его на каждый
    # пост, а растёт он строго на единицу в одном месте.
    member_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    # Момент прихода последнего участника — по нему видно, «остыл» ли сюжет.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    posts: Mapped[list["Post"]] = relationship(
        back_populates="cluster", foreign_keys="Post.cluster_id"
    )


class PostStat(Base):
    """Снимок метрик опубликованного поста во времени (F14)."""

    __tablename__ = "post_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"), index=True)
    view_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    forward_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reaction_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class PostTarget(Base):
    """Результат публикации поста В КОНКРЕТНУЮ целевую группу (F29).

    `Post.posted_message_id`/`posted_chat_id` хранят только ПЕРВУЮ успешную
    цель (см. `telegram/publisher.py::publish_post`) — этого было достаточно
    для сбора статистики и превью, пока пост публиковался в одну группу или
    когда "куда именно ушло" было не важно. F29 (редактирование/удаление/
    закрепление УЖЕ опубликованного поста) требует знать ВСЕ target'ы, а не
    только первый — отсюда отдельная таблица, по одной строке на каждую
    попытку публикации (успешную и неуспешную), заполняется `publish_post`
    целиком при каждой публикации."""

    __tablename__ = "post_targets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"), index=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    # NULL, если публикация в эту цель провалилась (см. `error`).
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # F29: закреплено ли ботом сообщение в этой цели — Bot API не отдаёт
    # состояние pin по chat_id/message_id напрямую, приходится хранить
    # свою правду и доверять ей (обновляется явно при pin/unpin).
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Аудит: тип честно Optional — колонка nullable в БД (миграция 0015
    # бэкфиллит старые публикации из `Post.posted_at`, который сам может
    # быть NULL); новые строки всегда получают значение через `default`.
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=_utcnow)


class PostRewriteVariant(Base):
    """Один из N сгенерированных вариантов рерайта поста (F06-доп.), число N —
    настройка `rewrite_variant_count`. Активный вариант см.
    `Post.active_rewrite_variant_index`/`rewritten_text` (денормализовано)."""

    __tablename__ = "post_rewrite_variants"
    # Составной, а не по одному языку: запрос горячего пути — «вариант ЭТОГО
    # поста на ЭТОМ языке» (публикация подбирает текст на каждую цель), а по
    # одному языку индекс бесполезен — значений всего два.
    __table_args__ = (
        Index("ix_post_rewrite_variants_language", "post_id", "language"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"), index=True)
    variant_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # На каком языке написан ИМЕННО этот вариант. У поста, уходящего в группы
    # с разными языками, вариантов столько же, сколько языков × настроенное
    # число вариантов на язык; при публикации в каждую группу подбирается
    # текст её языка (см. telegram/publisher.py::publish_post).
    language: Mapped[str] = mapped_column(
        String(8), default=DEFAULT_LANGUAGE, server_default=DEFAULT_LANGUAGE, nullable=False,
    )
    # Замечания редактора-фактчекера по ЭТОМУ варианту (F40, редакция из двух
    # агентов, см. rewriter/editorial.py) — показываются при модерации, чтобы
    # владелец видел, что и как правила редакция. NULL — редакция была выключена.
    editorial_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
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


class AdRequest(Base):
    """Заявка рекламодателя на место в сетке (F66).

    НЕДОСТАЮЩЕЕ ЗВЕНО между F21 и F35. Бриф (`ad_briefs`) — это уже принятая
    к работе задача для ИИ, журнал дохода (`ad_revenue`) — уже полученные
    деньги. А как заявка приходит, где она ждёт решения и чем занято
    расписание — не знал никто, и владелец держал это в переписке.

    ЖИЗНЕННЫЙ ЦИКЛ: `new` → `accepted` → `published`, либо `declined`.
    Принятие СОЗДАЁТ бриф, публикация — запись дохода. Так три сущности
    связываются в одну цепочку, и «сколько мы заработали на этом
    рекламодателе» перестаёт быть вопросом к памяти.

    ДВОЙНАЯ ПРОДАЖА МЕСТА — главная опасность фичи. Две принятые заявки на
    одну дату в одном канале означают, что владелец пообещал одно и то же
    двоим; кто-то из них узнает об этом уже после оплаты. Проверка живёт в
    `ad_requests_repo.accept`, а не в базе: объяснить человеку, с кем именно
    конфликт, важнее, чем получить ошибку уникальности.
    """

    __tablename__ = "ad_requests"
    __table_args__ = (
        # Горячий запрос — «что занято в этом канале»: календарь и проверка
        # конфликта идут ровно по этой паре.
        Index("ix_ad_requests_slot", "chat_id", "slot_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    # Как связаться с рекламодателем: @username, почта, что угодно. Свободный
    # текст намеренно — заявки приходят разными путями, и загонять их в
    # формат означало бы терять те, что не подошли.
    advertiser: Mapped[str] = mapped_column(String(255))
    brief_text: Mapped[str] = mapped_column(Text)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="RUB", nullable=False)
    # Дата размещения. Именно дата, а не время: сетка канала планируется по
    # дням, а конкретный час выбирает умное расписание (F19).
    slot_date: Mapped[date_type] = mapped_column(Date)
    # new | accepted | declined | published
    status: Mapped[str] = mapped_column(String(16), default="new", index=True)
    # Заполняются при переходах — так видно, что из чего выросло.
    ad_brief_id: Mapped[int | None] = mapped_column(
        ForeignKey("ad_briefs.id"), nullable=True
    )
    ad_revenue_id: Mapped[int | None] = mapped_column(
        ForeignKey("ad_revenue.id"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AdRevenue(Base):
    """Ручная запись рекламного дохода (F35) — НЕ интеграция с биржей (нет
    партнёрского API-доступа ни к одной конкретной бирже, решено с
    пользователем 2026-07-18), просто журнал: кто заплатил, сколько, когда.
    `ad_brief_id` необязателен — доход может быть от сделки вне системы
    брифов (например, разовая спонсорская интеграция)."""

    __tablename__ = "ad_revenue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ad_brief_id: Mapped[int | None] = mapped_column(
        ForeignKey("ad_briefs.id"), nullable=True
    )
    source: Mapped[str] = mapped_column(String(255))
    amount: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(8), default="RUB", nullable=False)
    # Дата сделки/поступления денег — НЕ обязательно "сегодня" (запись часто
    # вносится задним числом), поэтому отдельно от `created_at`.
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ChannelGrowthSnapshot(Base):
    """Снимок числа подписчиков целевого канала во времени (F22)."""

    __tablename__ = "channel_growth_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    subscriber_count: Mapped[int] = mapped_column(Integer)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ContactTag(Base):
    """Ручная метка на участнике (F63).

    ЗАЧЕМ ЗДЕСЬ НЕТ ТАБЛИЦЫ «КОНТАКТ». Личность участника уже хранится:
    имя и username — в `guardian.members`, откуда пришёл — в `member_origins`
    (F41), кто привёл — в `referrals` (F42), активность — в `user_activity`
    (F43). Своя копия карточки означала бы второй источник правды, который
    неминуемо разойдётся с первым — ровно та ошибка, из-за которой пришлось
    отменять журнал событий. Карточка собирается ЧТЕНИЕМ, а хранится только
    то, чего больше нигде нет: ручные теги и заметка владельца.

    Ключ — `user_id` без `chat_id`: тег вешается на ЧЕЛОВЕКА, а не на его
    участие в конкретном чате. «Постоянный покупатель» остаётся таковым во
    всех группах владельца.
    """

    __tablename__ = "contact_tags"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "tag", name="uq_contact_tag"),
        Index("ix_contact_tags_tag", "tenant_id", "tag"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    tag: Mapped[str] = mapped_column(String(64))
    added_by: Mapped[str] = mapped_column(String(32), default="manual", nullable=False)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class SupportThread(Base):
    """Переписка с одним человеком в поддержке (F68).

    ОДИН ТРЕД НА ЧЕЛОВЕКА, А НЕ НА ОБРАЩЕНИЕ. Человек не мыслит «тикетами»:
    он пишет боту, потом дописывает, потом возвращается через неделю. Нарезка
    на отдельные обращения по таймауту породила бы три треда об одном и том
    же и заставила оператора собирать историю по кускам.

    Статус живёт на треде: закрытый тред открывается заново новым сообщением
    — это и есть «человек вернулся с тем же вопросом».
    """

    __tablename__ = "support_threads"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_support_thread_user"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # open | closed
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    # Есть ли непрочитанное от человека. Отдельный флаг, а не сравнение дат:
    # оператор мог открыть тред и не ответить, и тогда «прочитано» — это его
    # решение, а не факт открытия страницы.
    has_unread: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default="1"
    )
    last_message_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class SupportMessage(Base):
    """Одно сообщение в переписке поддержки (F68)."""

    __tablename__ = "support_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    thread_id: Mapped[int] = mapped_column(
        ForeignKey("support_threads.id", ondelete="CASCADE"), index=True
    )
    # "in" — от человека, "out" — ответ оператора.
    direction: Mapped[str] = mapped_column(String(4))
    text: Mapped[str] = mapped_column(Text)
    # Кто ответил. NULL у входящих: там автор и так известен по треду.
    author: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Broadcast(Base):
    """Рассылка по сегменту (F64) — что отправили и чем это кончилось.

    Отдельно от `queued_tasks` намеренно. Задача — это МЕХАНИКА (курсор,
    попытки, аренда), и она живёт ровно до завершения. Рассылка — ДОКУМЕНТ:
    владельцу через месяц важно знать, что именно он отправлял, кому и
    сколько человек это получило. Смешав их, мы либо потеряли бы историю
    вместе с выполненными задачами, либо превратили бы служебную таблицу
    очереди в хранилище текстов.

    Счётчики раздельные, потому что означают РАЗНОЕ: `sent` — доставлено,
    `blocked` — человек заблокировал бота (не наша ошибка и не повод
    повторять), `failed` — всё прочее. Одна цифра «не дошло» скрыла бы, что
    именно происходит.
    """

    __tablename__ = "broadcasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    segment_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    # Имя сегмента НА МОМЕНТ отправки: сегмент могут переименовать или
    # удалить, а отчёт должен остаться читаемым (тот же приём, что с
    # `invite_name` в F41).
    segment_name: Mapped[str] = mapped_column(String(128))
    text: Mapped[str] = mapped_column(Text)
    task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # planned | running | done | canceled
    status: Mapped[str] = mapped_column(String(16), default="planned", index=True)
    # Сколько было в сегменте и скольким МОЖНО было написать — снимок на
    # момент запуска. Разрыв между ними объясняет владельцу результат.
    segment_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reachable_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sent_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    blocked_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class BotSubscriber(Base):
    """Человек, с которым бот ВООБЩЕ может заговорить (F64).

    ЭТО НЕ НАШЕ ОГРАНИЧЕНИЕ, А ПРАВИЛО TELEGRAM: бот не может написать
    первым. Личная переписка открывается только когда человек сам нажал
    «Запустить» или пришёл по deep-link. До этого момента любая попытка
    отправить ему сообщение вернёт ошибку.

    Отсюда следствие, которое легко упустить: сегмент из 8000 участников
    группы может быть достижим на сотню человек. Показывать владельцу только
    размер сегмента — значит вводить его в заблуждение, поэтому у рассылки
    всегда две цифры: сколько в сегменте и скольким реально можно написать.

    `is_blocked` — человек заблокировал бота. Пробовать снова бессмысленно,
    пока он сам не разблокирует; сбрасывается при новом сообщении от него.
    `unsubscribed_at` — отписался от рассылок кнопкой. Это РАЗНЫЕ вещи:
    первое решает Telegram, второе — человек, и путать их нельзя.
    """

    __tablename__ = "bot_subscribers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_bot_subscriber"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    unsubscribed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ContactSegment(Base):
    """Сохранённый сегмент участников (F63) — ЗАПРОС, а не список.

    Материализованный список людей устаревает молча: человек ушёл из чата или
    перестал подходить под условие, а рассылка всё равно уходит ему — и
    узнаётся это по жалобам. Поэтому здесь хранится только определение
    фильтра; кто именно в сегменте, вычисляется в момент использования.

    Правила проверки фильтра — в `segments_repo.validate`, и они строгие:
    неизвестное условие или пустой фильтр превратили бы узкий сегмент во
    «всю базу», а разосланные сообщения не отзываются.
    """

    __tablename__ = "contact_segments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_contact_segment_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    name: Mapped[str] = mapped_column(String(128))
    # JSON с условиями. Набор ключей меняется вместе с фичами, и колонки под
    # каждое условие означали бы миграцию на каждую новую возможность отбора.
    filter_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class ContactNote(Base):
    """Заметка владельца об участнике (F63). Одна на человека."""

    __tablename__ = "contact_notes"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_contact_note"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    note: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class QueuedTask(Base):
    """Долгая операция, переживающая рестарт процесса (фаза 11, решение 3).

    ЗАЧЕМ НЕ APScheduler И НЕ CELERY. Планировщик умеет «запустить в 9:00»,
    но не умеет «продолжить с 4312-го получателя». Рассылка на 10 000 человек
    идёт минутами, упирается в лимиты Telegram и обязана переживать рестарт —
    а Celery с Redis ради этого означал бы второй сервис в развёртывании
    ради свойства, которое даёт обычная строка в БД.

    КУРСОР — СЕРДЦЕ ТАБЛИЦЫ. Обработчик двигает `cursor` по мере работы, и
    именно он делает задачу возобновляемой: после обрыва она продолжается с
    места, а не начинается заново. Что лежит в курсоре — дело обработчика:
    для рассылки это id последнего получателя, для воронки — номер шага.

    АРЕНДА ВМЕСТО ФЛАГА «ВЫПОЛНЯЕТСЯ». Если процесс упал посреди задачи,
    статус `running` остался бы навсегда, и задача молча зависла бы — самый
    неприятный вид поломки, потому что снаружи всё выглядит рабочим. Поэтому
    `running` действителен, пока обработчик обновляет `updated_at`; протухшую
    аренду подбирает следующий воркер.
    """

    __tablename__ = "queued_tasks"
    __table_args__ = (
        # Выборка «что взять следующим» идёт ровно по этой тройке.
        Index("ix_queued_tasks_pick", "status", "run_after", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    # Что за задача: под неё зарегистрирован обработчик (см. `task_queue`).
    kind: Mapped[str] = mapped_column(String(32), index=True)
    # Параметры задачи, JSON. Хранится строкой: набор полей у каждого вида
    # свой, и заводить под них колонки значило бы менять схему на каждую
    # новую фичу.
    payload: Mapped[str] = mapped_column(Text, default="{}")
    # Прогресс. Семантика — на стороне обработчика (см. docstring класса).
    cursor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    done_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # pending | running | done | failed | canceled
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Не раньше этого момента. Отложенные шаги воронок (F71) — это оно.
    run_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class ChannelStatsSnapshot(Base):
    """Снимок статистики канала из MTProto Stats API (F56).

    ЧИСЛА ПОДПИСЧИКОВ ЗДЕСЬ НЕТ НАМЕРЕННО. Его уже собирает F22 в
    `channel_growth_snapshots`, и вторая колонка с тем же смыслом означала бы
    два источника правды: рано или поздно они разойдутся (разные моменты
    съёма, разные ошибки сети), и никто не сможет сказать, какой верный.

    Здесь только то, чего иначе взять негде:

    * `notifications_enabled_pct` — ГЛАВНОЕ. Доля подписчиков, у которых
      уведомления ВКЛЮЧЕНЫ. Её падение — отток за неделю до самой отписки:
      человек ещё числится подписчиком, но уже не читает. Никаким другим
      способом это не вычисляется: Bot API такого не отдаёт, а по своим
      данным этого не видно вообще.
    * `views_per_post` / `shares_per_post` / `reactions_per_post` — средние
      от самого Telegram. Не дубль наших метрик (F14/F31): те считаются по
      постам, которые опубликовали МЫ, а эти — по всем постам канала,
      включая опубликованные вручную.

    Хранится ИСТОРИЯ, а не последнее значение: Telegram отдаёт срез, а вся
    ценность в динамике (см. `mute_trend`).
    """

    __tablename__ = "channel_stats_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Новая таблица, поэтому ключ арендатора закладывается сразу — решение 1
    # в FEATURES.md. Формально оно писалось про фазы 11–14, но довод («одна
    # колонка сейчас против миграции по всей базе потом») к новой таблице
    # относится ровно так же, а таблицы F01–F51 мы по-прежнему не трогаем.
    tenant_id: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    views_per_post: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shares_per_post: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reactions_per_post: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Доля в процентах, 0–100. NULL — Telegram не отдал это поле.
    notifications_enabled_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class InviteLink(Base):
    """Инвайт-ссылка целевой группы, созданная через бота (F32).

    Bot API не даёт способа перечислить УЖЕ существующие инвайт-ссылки чата
    (только создать/отозвать/отредактировать конкретную) — эта таблица САМА
    является источником истины о том, какие ссылки бот когда-либо создал;
    ссылки, созданные вручную в Telegram (не через эту систему), здесь не
    появятся и системой не управляются."""

    __tablename__ = "invite_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    invite_link: Mapped[str] = mapped_column(String(255))
    name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    member_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    creates_join_request: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Сколько стоило размещение, ради которого создана ссылка (F41). Вместе с
    # числом реально пришедших по ней даёт цену подписчика (CPA). Валюта — как
    # у AdRevenue, без конвертации: считаем отдельно по каждой.
    cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_currency: Mapped[str] = mapped_column(
        String(8), default="RUB", server_default="RUB", nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class MemberOrigin(Base):
    """Откуда пришёл участник — атрибуция рекламы (F41).

    Telegram САМ сообщает использованную инвайт-ссылку в `chat_member` и
    `chat_join_request` (поле `invite_link`) — до F41 эти данные приходили в
    наши хендлеры и молча выбрасывались. Одна строка на пару (чат, участник):
    повторное вступление после ухода перезаписывает запись, потому что
    интересует АКТУАЛЬНЫЙ источник, а не вся история метаний.

    `invite_link` = NULL — пришёл не по нашей ссылке (нашёл поиском, добавлен
    админом, вступил по ссылке, созданной вручную в Telegram).
    """

    __tablename__ = "member_origins"
    __table_args__ = (
        # Горячий путь — апсерт по паре: на каждое вступление/уход.
        Index("ix_member_origins_chat_user", "chat_id", "user_id", unique=True),
        # Статистика «сколько привела ссылка» — группировка по ней.
        Index("ix_member_origins_link", "invite_link"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    user_id: Mapped[int] = mapped_column(BigInteger)
    invite_link: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Имя ссылки НА МОМЕНТ вступления: ссылку могут переименовать или отозвать,
    # а отчёт по кампании должен остаться читаемым.
    invite_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    # NULL — участник всё ещё в чате. Заполняется по `chat_member`-апдейту об
    # уходе/бане: без этого retention считать не из чего.
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class JoinRequestRecord(Base):
    """Заявка на вступление в целевую группу с подтверждением админом (F32) —
    заполняется апдейтом `chat_join_request` (Bot API), решение (approve/
    decline) принимается владельцем через Telegram-бота или веб-админку."""

    __tablename__ = "join_requests"
    __table_args__ = (
        UniqueConstraint("chat_id", "user_id", "status", name="uq_join_request_pending"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    # pending | approved | declined — часть уникального ограничения выше:
    # НЕ более одной PENDING заявки от одного user_id на один chat_id
    # одновременно (Telegram и так не шлёт chat_join_request повторно, пока
    # заявка не решена, но защита на уровне БД дешевле, чем полагаться на
    # это поведение). approved/declined-записи копятся как история.
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    # По какой ссылке подана заявка (F41). Telegram отдаёт это в апдейте;
    # пригодится, когда заявку одобрят — тогда источник переедет в MemberOrigin.
    invite_link: Mapped[str | None] = mapped_column(String(255), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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
    """Учётка администратора веб-панели (F23, роли — F37).

    Раньше строка была ровно одна, а вход — по одному паролю без имени. F37
    это меняет: у бизнеса появляются сотрудники, а пригласить редактора,
    не отдав ему заодно токены ботов и session string, при одном пароле
    невозможно — это полный доступ к аккаунту, а не к контенту.

    РОЛЬ ХРАНИТСЯ СТРОКОЙ, а не ссылкой на таблицу прав: ролей три, они
    заданы кодом, и таблица «права роли» превратила бы понятную проверку в
    цепочку join-ов ради гибкости, которая никому не нужна.
    """

    __tablename__ = "admin_users"
    __table_args__ = (
        # Имя индекса совпадает с миграцией 0038 НАМЕРЕННО. Тесты поднимают
        # схему через `create_all`, прод — через alembic; если объявить
        # уникальность только в миграции, тесты будут гонять схему БЕЗ неё, и
        # дубли имён пройдут в тестах, но упадут у пользователя. Поймано
        # ровно так: тест на дубликат зеленел, пока индекса не было в модели.
        Index("ux_admin_users_username", "username", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # NULL только у строк, созданных до F37; миграция проставляет «owner».
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # owner | editor | analyst — см. `webui/access.py`.
    role: Mapped[str] = mapped_column(String(16), default="owner", nullable=False)
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


class Quiz(Base):
    """Викторина по опубликованному посту (F43, геймификация).

    Механика владельца: бот выдаёт контент, а ЧЕРЕЗ ВРЕМЯ спрашивает по нему.
    Очки — за правильный ответ, а не за количество сообщений: те превращаются
    в ферму флуда («+», «ок»), а тут очки идут за то, что человек реально
    прочитал.

    Вопрос делает LLM из УЖЕ проверенного материала: текст статьи извлечён
    (trafilatura, F16), факты сверены редактором (F40) — поэтому вопрос
    опирается на реальный текст, а не на выдумку модели.

    Публикуется как нативный quiz-poll: Telegram сам проверяет ответ, показывает
    верный вариант с пояснением и не даёт переголосовать. Ноль LLM-вызовов на
    проверку ответов и ноль споров «я это и имел в виду».

    ВАЖНО: работает только в ГРУППАХ. В канале у постов нет авторов-участников,
    и `poll_answer` от читателей канала не приходит — для канала это его
    discussion-группа.
    """

    __tablename__ = "quizzes"
    __table_args__ = (
        # Горячий путь публикации: «какие квизы пора отправить».
        Index("ix_quizzes_pending", "published_at"),
        # poll_answer приходит с poll_id — по нему ищем квиз.
        Index("ix_quizzes_poll", "poll_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Из какого поста сделан вопрос. NULL допустим: пост могли удалить, а
    # статистика ответов должна пережить это.
    post_id: Mapped[int | None] = mapped_column(
        ForeignKey("posts.id"), nullable=True, index=True,
    )
    chat_id: Mapped[int] = mapped_column(BigInteger)
    question: Mapped[str] = mapped_column(Text)
    # JSON-массив вариантов. Не отдельная таблица: варианты не живут своей
    # жизнью, всегда читаются и пишутся целиком вместе с вопросом.
    options_json: Mapped[str] = mapped_column(Text)
    correct_index: Mapped[int] = mapped_column(Integer)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Заполняются при публикации. `poll_id` — строка (Telegram даёт его именно
    # строкой), по ней сопоставляется входящий poll_answer.
    poll_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # NULL — ещё не опубликован (ждёт своей паузы после поста).
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class QuizAnswer(Base):
    """Ответ участника на викторину (F43). Одна попытка на человека —
    Telegram и сам не даёт переголосовать в quiz-режиме, но уникальный индекс
    защищает от дубля при повторной доставке апдейта."""

    __tablename__ = "quiz_answers"
    __table_args__ = (
        UniqueConstraint("quiz_id", "user_id", name="uq_quiz_answer"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    quiz_id: Mapped[int] = mapped_column(ForeignKey("quizzes.id"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    option_index: Mapped[int] = mapped_column(Integer)
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    answered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class UserActivity(Base):
    """Очки участника в чате (F43). Уровень НЕ хранится — он вычисляется из
    очков (`level_for_points`), иначе смена формулы потребовала бы миграции
    данных."""

    __tablename__ = "user_activity"
    __table_args__ = (
        Index("ix_user_activity_chat_user", "chat_id", "user_id", unique=True),
        # Лидерборд: «топ по очкам в этом чате».
        Index("ix_user_activity_leaderboard", "chat_id", "points"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    user_id: Mapped[int] = mapped_column(BigInteger)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    correct_answers: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_answers: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Серия дней подряд с правильным ответом — считается по ДАТЕ, а не по
    # времени: человек не должен терять серию из-за того, что вчера отвечал
    # утром, а сегодня вечером.
    streak_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_correct_date: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Referral(Base):
    """Кто кого привёл (F42, реферальная программа).

    Приглашённый приходит по deep-link `t.me/<bot>?start=ref_<user_id>` — бот
    Engage получает payload первым же сообщением и знает пригласившего.

    АНТИНАКРУТКА — главное в этой таблице. Без неё механика мгновенно
    превращается в ферму мультиаккаунтов: завёл десять аккаунтов, прошёл по
    своей же ссылке, собрал награды. Поэтому реферал считается «подтверждённым»
    (`confirmed_at`) только когда приглашённый ПРОЖИЛ в группе N дней И написал
    хотя бы одно сообщение. Награда выдаётся за подтверждённых, а не за
    пришедших.
    """

    __tablename__ = "referrals"
    __table_args__ = (
        # Один пригласивший на приглашённого: первый, кто привёл, тот и привёл.
        UniqueConstraint("invited_user_id", name="uq_referral_invited"),
        Index("ix_referrals_inviter", "inviter_user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    inviter_user_id: Mapped[int] = mapped_column(BigInteger)
    invited_user_id: Mapped[int] = mapped_column(BigInteger)
    # В какой чат приглашали — награды и лидерборды считаются по чату.
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    # Вступил ли приглашённый в группу (пришёл по ссылке — ещё не значит вступил).
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Написал ли хоть что-то — вторая половина антинакрутки.
    first_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    # Оба условия выполнены и выдержан срок: реферал засчитан и оплачен.
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )


class Contest(Base):
    """Конкурс/розыгрыш среди участников (F44).

    ПРОЗРАЧНОСТЬ РОЗЫГРЫША — не украшение, а условие работоспособности: если
    аудитория не верит, что победителя не выбрали «своим», конкурс не
    вовлекает, а раздражает. Поэтому `draw_seed` генерируется и ПУБЛИКУЕТСЯ
    ЗАРАНЕЕ, вместе с условиями, а после розыгрыша сохраняется протокол
    (`draw_protocol`): список участников в том порядке, в каком их видел
    алгоритм, и выбранные победители. Имея seed, список и описание алгоритма,
    любой желающий воспроизводит результат.
    """

    __tablename__ = "contests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    title: Mapped[str] = mapped_column(String(255))
    prize: Mapped[str] = mapped_column(Text)
    winners_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    # --- Условия участия (0/пусто = условие не проверяется) ---
    # CSV из chat_id каналов, на которые надо быть подписанным. Проверяется
    # через getChatMember — бот должен быть админом в каждом из них.
    require_subscribed_chat_ids: Mapped[str | None] = mapped_column(Text, nullable=True)
    require_min_points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    require_min_referrals: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # --- Прозрачность ---
    # Публикуется ВМЕСТЕ с конкурсом, до того как известен состав участников.
    draw_seed: Mapped[str] = mapped_column(String(64))
    # Заполняется после розыгрыша: кто участвовал и кто выиграл.
    draw_protocol: Mapped[str | None] = mapped_column(Text, nullable=True)
    drawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ContestEntry(Base):
    """Заявка на участие в конкурсе (F44).

    Условия проверяются ДВАЖДЫ: при записи (чтобы сразу сказать человеку, чего
    не хватает) и при розыгрыше (чтобы нельзя было выполнить условие, записаться
    и тут же отписаться от канала).
    """

    __tablename__ = "contest_entries"
    __table_args__ = (
        UniqueConstraint("contest_id", "user_id", name="uq_contest_entry"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contest_id: Mapped[int] = mapped_column(ForeignKey("contests.id"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_winner: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


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
