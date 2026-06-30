"""Публикатор (F08) — публикация одобренных постов через Bot API.

Берёт пост со статусом `approved`, шлёт текст (+ медиа, если есть) во все
активные целевые группы, переводит статус в `posted`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from telegram import Bot

from tg_repost.db.models import Post, PostStatus, TargetGroup, parse_chat_ids_csv
from tg_repost.db.session import session_scope
from tg_repost.logging_conf import get_logger
from tg_repost.retry import retry_async

logger = get_logger(__name__)

# Лимит Telegram: 4096 символов на сообщение, 1024 на подпись к медиа.
_MAX_TEXT = 4096
_MAX_CAPTION = 1024


def _active_target_chat_ids() -> list[int]:
    """ID активных целевых групп из БД."""
    with session_scope() as session:
        rows = (
            session.query(TargetGroup.chat_id)
            .filter(TargetGroup.is_active.is_(True))
            .all()
        )
        return [r[0] for r in rows]


def resolve_targets_for_post(post_id: int) -> list[int]:
    """Целевые группы для поста (F12).

    Если у источника задано переопределение (`target_chat_ids`) — публикуем
    только в его активные группы; иначе — во все активные.
    """
    active = _active_target_chat_ids()
    with session_scope() as session:
        post = session.get(Post, post_id)
        override_raw = post.source.target_chat_ids if post and post.source else None
    override = parse_chat_ids_csv(override_raw)
    if override:
        chosen = [c for c in override if c in active]
        if chosen:
            return chosen
        logger.warning(
            "Пост %s: переопределённые цели источника неактивны — публикую во все",
            post_id,
        )
    return active


async def _send_one(bot: Bot, chat_id: int, text: str, media_path: str | None) -> int:
    """Отправить пост в один чат. Возвращает message_id.

    Текст отправляется как plain text (без parse_mode): контент — это вывод LLM
    и заголовки внешних источников (F16), которые могут содержать <, & или
    HTML-теги. С parse_mode=HTML это привело бы к ошибке парсинга или инъекции
    ссылок; plain text безопасен и предсказуем.
    """
    if media_path:
        caption = text[:_MAX_CAPTION] if text else None
        # Файл читаем в потоке, чтобы не блокировать event loop.
        photo_bytes = await asyncio.to_thread(Path(media_path).read_bytes)
        msg = await bot.send_photo(chat_id=chat_id, photo=photo_bytes, caption=caption)
        # Если текст длиннее подписи — досылаем хвост отдельным сообщением.
        if text and len(text) > _MAX_CAPTION:
            await bot.send_message(
                chat_id=chat_id, text=text[_MAX_CAPTION:_MAX_CAPTION + _MAX_TEXT]
            )
        return msg.message_id

    msg = await bot.send_message(chat_id=chat_id, text=text[:_MAX_TEXT])
    return msg.message_id


async def publish_post(bot: Bot, post_id: int) -> None:
    """Опубликовать пост во все активные целевые группы (F08)."""
    from datetime import datetime, timezone

    with session_scope() as session:
        post = session.get(Post, post_id)
        if post is None:
            logger.warning("Публикация поста %s невозможна: пост не найден", post_id)
            return
        if post.status != PostStatus.APPROVED:
            # Не ошибка сама по себе — например, пост уже отклонили модератором
            # между выборкой в publish_slot и этим вызовом (TOCTOU-окно), но
            # без лога оператор не узнает, почему запланированный пост не вышел.
            logger.info(
                "Публикация поста %s пропущена: статус %s (ожидался approved)",
                post_id, post.status.value,
            )
            return
        text = post.rewritten_text or post.original_text
        media_path = post.media_path

    chat_ids = resolve_targets_for_post(post_id)
    if not chat_ids:
        logger.error("Нет активных целевых групп — публикация поста %s невозможна", post_id)
        with session_scope() as session:
            post = session.get(Post, post_id)
            if post:
                post.set_status(PostStatus.FAILED, reason="нет целевых групп")
        return

    first_message_id: int | None = None
    first_chat_id: int | None = None
    try:
        for chat_id in chat_ids:
            mid = await retry_async(
                lambda c=chat_id: _send_one(bot, c, text, media_path),
                description=f"публикация поста {post_id} в {chat_id}",
            )
            if first_message_id is None:
                first_message_id = mid
                first_chat_id = chat_id
            logger.info("Пост %s опубликован в %s (msg=%s)", post_id, chat_id, mid)
    except Exception as exc:  # noqa: BLE001
        logger.error("Ошибка публикации поста %s: %s", post_id, exc)
        with session_scope() as session:
            post = session.get(Post, post_id)
            if post:
                post.set_status(PostStatus.FAILED, reason=f"ошибка публикации: {exc}")
        return

    with session_scope() as session:
        post = session.get(Post, post_id)
        if post:
            post.posted_message_id = first_message_id
            post.posted_chat_id = first_chat_id
            post.posted_at = datetime.now(timezone.utc)
            post.set_status(PostStatus.POSTED)
