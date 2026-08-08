"""Периодический опрос RSS-источников → посты со статусом NEW.

Дальше их подхватывает обычный `rewrite_new_posts` — отдельного пайплайна
для RSS нет и не нужно.
"""

from __future__ import annotations

from tg_repost import ingest
from tg_repost.config import get_settings
from tg_repost.db.models import Post, PostStatus, Source
from tg_repost.db.session import session_scope
from tg_repost.logging_conf import get_logger
from tg_repost.rss.feed import FeedItem, fetch_feed

logger = get_logger(__name__)

SOURCE_KIND_RSS = "rss"


def _known_guids(source_id: int, guids: list[str]) -> set[str]:
    """Какие записи этой ленты уже заводились постами.

    Ключ дедупликации — `Post.source_link`: у RSS это ссылка/guid записи,
    штука стабильная между опросами (в отличие от заголовка, который автор
    может поправить, и от текста, который у ленты часто меняется целиком
    при редактуре).
    """
    if not guids:
        return set()
    with session_scope() as session:
        rows = (
            session.query(Post.source_link)
            .filter(Post.source_id == source_id, Post.source_link.in_(guids))
            .all()
        )
    return {r[0] for r in rows if r[0]}


def _has_any_post(source_id: int) -> bool:
    with session_scope() as session:
        return session.query(Post.id).filter(Post.source_id == source_id).first() is not None


async def _create_post(source_id: int, item: FeedItem) -> bool:
    """Завести пост по записи ленты. False — отсеяна фильтром или это повтор.

    Приём общий с Telegram-веткой (`tg_repost.ingest`). Раньше здесь жила
    своя урезанная копия правил: `content_hash` считался, но НИ РАЗУ не
    сверялся, а семантического дубль-чека не было вовсе — поэтому одна и та
    же новость из пяти лент давала пять постов. `_known_guids` эту дыру не
    закрывает: он сравнивает guid ВНУТРИ одной ленты, то есть отвечает на
    вопрос «я уже забирал эту запись?», а не «эта новость уже была?».
    """
    text = item.as_post_text()
    # Эмбеддинг — сетевой вызов, поэтому до открытия транзакции.
    embedding = await ingest.compute_embedding(text)
    with session_scope() as session:
        result = ingest.ingest_post(
            session,
            source_id=source_id,
            text=text,
            # Ссылка записи служит и ключом дедупликации (см. _known_guids),
            # поэтому кладём именно guid, а не item.link: они совпадают не
            # всегда, а уникален по контракту ленты именно guid.
            source_link=item.guid,
            embedding=embedding,
        )
    return result.queued


async def poll_one_source(
    source_id: int, feed_url: str, title: str | None = None, *, limit: int | None = None,
) -> int:
    """Опросить одну ленту. Возвращает число новых постов.

    Флаг `rss_enabled` здесь СОЗНАТЕЛЬНО не проверяется: это низкоуровневый
    шаг, и его же зовёт кнопка «Собрать сейчас» в админке — кнопка, которая
    молча ничего не делает из-за неотмеченной галочки, хуже, чем её
    отсутствие. Расписание проверяет флаг само (см. `poll_rss_sources`).
    """
    settings = get_settings()
    items = await fetch_feed(feed_url)
    if not items:
        return 0

    # Первый опрос новой ленты: в архиве могут лежать тысячи записей
    # (у MSRC — больше пяти тысяч), и завести их все постами значит
    # намертво забить очередь модерации и счёт за рерайт. Берём только
    # несколько свежих, остальное считаем историей.
    first_run = not _has_any_post(source_id)
    if limit is None:
        limit = settings.rss_first_poll_items if first_run else settings.rss_max_items_per_poll

    known = _known_guids(source_id, [i.guid for i in items])
    fresh = [i for i in items if i.guid not in known][:max(0, limit)]

    if first_run and len(items) > len(fresh):
        logger.info(
            "Лента «%s» опрошена впервые: беру %d свежих из %d, остальное — история",
            title or feed_url, len(fresh), len(items),
        )

    # Последовательно, а не gather: приём смотрит на уже сохранённые посты
    # (хэш, сходство), и параллельная обработка двух одинаковых записей
    # прошла бы мимо друг друга — оба увидели бы пустую историю.
    created = 0
    for item in fresh:
        if await _create_post(source_id, item):
            created += 1
    if fresh:
        logger.info(
            "RSS «%s»: %d новых записей, в очередь попало %d",
            title or feed_url, len(fresh), created,
        )
    return created


def pending_queue_size() -> int:
    """Сколько постов ждут обработки (ещё не дошли до модерации)."""
    with session_scope() as session:
        return (
            session.query(Post)
            .filter(Post.status.in_((PostStatus.NEW, PostStatus.REWRITING)))
            .count()
        )


async def poll_rss_sources() -> int:
    """Опросить все активные RSS-источники. Возвращает число новых постов."""
    settings = get_settings()
    if not settings.rss_enabled:
        return 0

    # Предохранитель: приток из лент легко обгоняет обработку (пост = вызовы
    # модели + генерация обложек), и без остановки очередь растёт бесконечно
    # вместе со счётом за API. Записи никуда не денутся — ленты отдают их и
    # на следующем опросе, когда очередь разгребётся.
    limit = settings.rss_max_queue_backlog
    if limit > 0:
        backlog = pending_queue_size()
        if backlog >= limit:
            logger.warning(
                "Опрос лент пропущен: в очереди %d необработанных постов (потолок %d). "
                "Разгреби модерацию или подними потолок в настройках RSS.",
                backlog, limit,
            )
            return 0

    with session_scope() as session:
        sources = [
            (s.id, s.channel_username, s.channel_title)
            for s in session.query(Source)
            .filter(Source.kind == SOURCE_KIND_RSS, Source.is_active.is_(True))
            .all()
        ]

    return sum([await poll_one_source(sid, url, title) for sid, url, title in sources])
