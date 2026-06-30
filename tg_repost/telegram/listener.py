"""Telethon listener (F02) — слушает новые посты в источниках.

Подключается под юзер-сессией, подписывается на `events.NewMessage` для
каналов из таблицы `sources`, применяет фильтр (F03) и хэш-дедупликацию (F04),
сохраняет пост в `posts` с корректным начальным статусом.
"""

from __future__ import annotations

import os

from telethon import TelegramClient, events
from telethon.sessions import StringSession

from tg_repost.antiban import HourlyRateLimiter, jitter_sleep
from tg_repost.config import get_settings
from tg_repost.db.models import Post, PostStatus, Source
from tg_repost.db.session import session_scope
from tg_repost.dedup.hash_dedup import content_hash
from tg_repost.dedup.semantic import find_similar_post, pack_embedding
from tg_repost.filtering import check_keywords
from tg_repost.logging_conf import get_logger
from tg_repost.rewriter.client import get_rewriter

logger = get_logger(__name__)

# F17: почасовой лимит «тяжёлых» действий (скачивание медиа). Создаётся лениво,
# чтобы настройки уже были загружены.
_rate_limiter: HourlyRateLimiter | None = None


def _get_rate_limiter() -> HourlyRateLimiter:
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = HourlyRateLimiter(get_settings().max_reads_per_hour)
    return _rate_limiter


def build_client() -> TelegramClient:
    """Создать Telethon-клиент из настроек (без подключения)."""
    settings = get_settings()
    return TelegramClient(
        StringSession(settings.tg_session_string),
        settings.tg_api_id,
        settings.tg_api_hash,
    )


def _load_active_source_entities() -> list[str]:
    """Список username активных источников для подписки на события."""
    with session_scope() as session:
        sources = session.query(Source).filter(Source.is_active.is_(True)).all()
        return [s.channel_username for s in sources]


def _find_source_id(channel_id: int, channel_username: str | None) -> int | None:
    """Найти id источника в БД по channel_id или username; обновить channel_id."""
    with session_scope() as session:
        query = session.query(Source).filter(Source.is_active.is_(True))
        source = query.filter(Source.channel_id == channel_id).one_or_none()
        if source is None and channel_username:
            source = query.filter(
                Source.channel_username == channel_username
            ).one_or_none()
            if source is not None and source.channel_id is None:
                source.channel_id = channel_id
        return source.id if source else None


async def _handle_new_message(event: events.NewMessage.Event) -> None:
    """Обработать новое сообщение из источника (F02 → F03 → F04 → F13)."""
    settings = get_settings()
    message = event.message
    text = message.message or ""

    # F17 — джиттер: случайная пауза, чтобы не обрабатывать пачку мгновенно.
    await jitter_sleep(
        settings.listener_min_delay_seconds, settings.listener_max_delay_seconds
    )

    chat = await event.get_chat()
    username = getattr(chat, "username", None)
    channel_id = getattr(chat, "id", None)
    if channel_id is None:
        return

    source_id = _find_source_id(channel_id, username)
    if source_id is None:
        # Сообщение из канала, которого нет среди активных источников.
        return

    if not text.strip():
        logger.debug("Пропуск пустого/медиа-без-текста сообщения %s", message.id)
        return

    digest = content_hash(text)
    source_link = f"https://t.me/{username}/{message.id}" if username else None

    # F03 — фильтр ключевых слов (чистая функция, до обращения к БД и эмбеддингам).
    filter_result = check_keywords(
        text, settings.filter_stop_words, settings.filter_required_words
    )

    # F13 — эмбеддинг считаем только если он понадобится (фильтр прошёл и включён
    # семантический дубль-чек), чтобы не тратить токены зря.
    embedding: list[float] | None = None
    if settings.semantic_dedup_enabled and filter_result.passed:
        try:
            embedding = await get_rewriter().embed(text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Не удалось получить эмбеддинг поста %s: %s", message.id, exc)

    with session_scope() as session:
        # Анти-дубль по (source_id, message_id) — уже видели это сообщение.
        exists = (
            session.query(Post.id)
            .filter(Post.source_id == source_id, Post.source_message_id == message.id)
            .first()
        )
        if exists:
            return

        post = Post(
            source_id=source_id,
            source_message_id=message.id,
            source_link=source_link,
            original_text=text,
            content_hash=digest,
            status=PostStatus.NEW,
        )
        if embedding is not None:
            post.embedding = pack_embedding(embedding)

        if not filter_result.passed:
            post.set_status(PostStatus.FILTERED_OUT, reason=filter_result.reason)
            session.add(post)
            logger.info("Пост %s отфильтрован: %s", message.id, filter_result.reason)
            return

        # F04 — хэш-дедупликация (точный дубль из другого источника).
        dup = (
            session.query(Post.id)
            .filter(
                Post.content_hash == digest,
                Post.status != PostStatus.DUPLICATE,
                Post.status != PostStatus.FILTERED_OUT,
            )
            .first()
        )
        if dup:
            post.set_status(PostStatus.DUPLICATE, reason="точный дубль по хэшу")
            session.add(post)
            logger.info("Пост %s — дубль (хэш), пропущен", message.id)
            return

        # F13 — семантический дубль-чек (перефразированный повтор).
        if embedding is not None:
            similar = find_similar_post(
                session,
                embedding,
                threshold=settings.semantic_similarity_threshold,
                window_days=settings.dedup_window_days,
            )
            if similar is not None:
                sim_id, sim_score = similar
                post.set_status(
                    PostStatus.DUPLICATE,
                    reason=f"семантический дубль #{sim_id} (sim={sim_score:.3f})",
                )
                session.add(post)
                logger.info(
                    "Пост %s — семантический дубль #%s (sim=%.3f)",
                    message.id, sim_id, sim_score,
                )
                return

        # Пост-кипер. Сохраняем сразу, БЕЗ медиа: скачивание медиа и ожидание
        # почасового лимита (может спать долго) выносим за пределы транзакции,
        # чтобы не держать соединение с БД открытым во время сетевого I/O.
        session.add(post)
        session.flush()
        post_id = post.id
        logger.info("Новый пост в очереди: source_id=%s msg=%s", source_id, message.id)

    # Скачивание медиа вне сессии (F17: под почасовым лимитом «тяжёлых» действий).
    if message.media:
        os.makedirs(settings.media_dir, exist_ok=True)
        await _get_rate_limiter().acquire()
        try:
            path = await message.download_media(file=settings.media_dir)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Не удалось скачать медиа поста %s: %s", message.id, exc)
            path = None
        if path:
            with session_scope() as session:
                saved = session.get(Post, post_id)
                if saved is not None:
                    saved.media_path = path


async def start_listener(client: TelegramClient) -> None:
    """Подключить клиент и зарегистрировать обработчик новых сообщений.

    Клиент должен быть уже авторизован (валидный session string в .env).
    """
    await client.connect()
    if not await client.is_user_authorized():
        raise RuntimeError(
            "Telethon не авторизован. Сгенерируй session string: "
            "python -m tg_repost.tools.gen_session"
        )

    entities = _load_active_source_entities()
    me = await client.get_me()
    logger.info("Telethon авторизован как %s, источников: %d",
                getattr(me, "username", me.id), len(entities))

    # Подписываемся на все каналы (если список пуст — слушаем всё, но фильтруем
    # по наличию источника в БД внутри обработчика).
    chats = entities or None
    client.add_event_handler(_handle_new_message, events.NewMessage(chats=chats))
    logger.info("Listener запущен, слушаю %s",
                "указанные источники" if chats else "все диалоги (фильтр в БД)")
