"""Публикатор (F08) — публикация одобренных постов через Bot API.

Берёт пост со статусом `approved`, шлёт текст (+ медиа, если есть) во все
активные целевые группы, переводит статус в `posted`.
"""

from __future__ import annotations

import asyncio
import functools
from pathlib import Path

from telegram import Bot
from telegram.error import RetryAfter

from tg_repost.db.models import Post, PostStatus, TargetGroup, parse_chat_ids_csv
from tg_repost.db.session import session_scope
from tg_repost.logging_conf import get_logger, sanitize_proxy_error
from tg_repost.retry import retry_async


def _retry_after_delay(exc: BaseException) -> float | None:
    """Уважать flood-wait от самого Telegram (см. retry.py::retry_async
    docstring) вместо фиксированного backoff."""
    return exc.retry_after if isinstance(exc, RetryAfter) else None

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
    ТОЛЬКО в его активные группы. Если override задан, но ни одна из
    выбранных групп сейчас не активна — публикация не происходит вовсе
    (пустой список), а НЕ фолбэк на все активные группы: раньше в этом
    случае контент источника тихо уходил во все группы подряд, включая те,
    куда его никогда не направляли (найдено на аудите ведения групп).
    """
    active = _active_target_chat_ids()
    with session_scope() as session:
        post = session.get(Post, post_id)
        override_raw = post.source.target_chat_ids if post and post.source else None
    override = parse_chat_ids_csv(override_raw)
    if override:
        chosen = [c for c in override if c in active]
        if not chosen:
            logger.warning(
                "Пост %s: персональные цели источника заданы, но все неактивны — "
                "публикация отменена (без фолбэка на все группы)",
                post_id,
            )
        return chosen
    return active


def resolve_target_labels_for_post(post_id: int) -> list[str]:
    """Человекочитаемые названия целевых групп для поста — чтобы модератор
    (бот и веб-админка) видел, куда пост уйдёт ДО одобрения, а не узнавал
    из лога публикации постфактум (найдено на аудите ведения групп)."""
    chat_ids = resolve_targets_for_post(post_id)
    if not chat_ids:
        return []
    with session_scope() as session:
        rows = (
            session.query(TargetGroup.chat_id, TargetGroup.title)
            .filter(TargetGroup.chat_id.in_(chat_ids))
            .all()
        )
        titles: dict[int, str | None] = {chat_id: title for chat_id, title in rows}
    return [titles.get(cid) or str(cid) for cid in chat_ids]


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
        with session_scope() as session:
            post = session.get(Post, post_id)
            has_override = bool(post.source.target_chat_ids) if post and post.source else False
            reason = (
                "персональные цели источника заданы, но все неактивны"
                if has_override else "нет активных целевых групп"
            )
            logger.error("Публикация поста %s невозможна: %s", post_id, reason)
            if post:
                post.set_status(PostStatus.FAILED, reason=reason)
        return

    # Публикуем в КАЖДУЮ цель НЕЗАВИСИМО И ПАРАЛЛЕЛЬНО (asyncio.gather) —
    # сбой/ретрай в одной группе не должен ни прерывать отправку в
    # остальные, ни задерживать их: раньше цикл был последовательным, и
    # одна зависшая/rate-limited (RetryAfter без верхнего предела, см.
    # retry_async) группа могла надолго отложить доставку во ВСЕ
    # остальные, здоровые группы (найдено на повторном ревью). Порядок
    # результатов `asyncio.gather` совпадает с порядком аргументов (НЕ с
    # порядком завершения) — `first_chat_id`/`first_message_id` остаются
    # детерминированными ("первый по исходному списку chat_ids успешный"),
    # как и при последовательной версии, а не "первый, кто первым ответил".
    async def _send_to_target(chat_id: int) -> tuple[int, int | None, str | None]:
        try:
            mid = await retry_async(
                functools.partial(_send_one, bot, chat_id, text, media_path),
                description=f"публикация поста {post_id} в {chat_id}",
                delay_override=_retry_after_delay,
            )
        except Exception as exc:  # noqa: BLE001
            # sanitize_proxy_error — на случай сбоя подключения через
            # BOT_API_PROXY_URL (см. retry.py).
            return chat_id, None, sanitize_proxy_error(str(exc))
        return chat_id, mid, None

    results = await asyncio.gather(*(_send_to_target(chat_id) for chat_id in chat_ids))

    first_message_id: int | None = None
    first_chat_id: int | None = None
    failed_chat_ids: list[int] = []
    for chat_id, mid, err in results:
        if err is not None:
            logger.error(
                "Ошибка публикации поста %s в группу %s: %s", post_id, chat_id, err,
            )
            failed_chat_ids.append(chat_id)
            continue
        if first_message_id is None:
            first_message_id = mid
            first_chat_id = chat_id
        logger.info("Пост %s опубликован в %s (msg=%s)", post_id, chat_id, mid)

    if first_message_id is None:
        # Ни одна цель не приняла публикацию — пост нигде не появился,
        # ретрай безопасен (дублей быть не может).
        logger.error("Публикация поста %s не удалась ни в одну из %d групп", post_id, len(chat_ids))
        with session_scope() as session:
            post = session.get(Post, post_id)
            if post:
                post.set_status(PostStatus.FAILED, reason="публикация не удалась ни в одну группу")
        return

    with session_scope() as session:
        post = session.get(Post, post_id)
        if post:
            post.posted_message_id = first_message_id
            post.posted_chat_id = first_chat_id
            post.posted_at = datetime.now(timezone.utc)
            # Пост уже реально опубликован (хотя бы куда-то) — статус
            # ВСЕГДА POSTED, частичный провал остаётся только в reason/логе,
            # не блокирует переход и не запускает повторную публикацию.
            #
            # status_reason выставляется НАПРЯМУЮ (не через kwarg set_status),
            # чтобы явно ОЧИСТИТЬ его при полном успехе: set_status(reason=None)
            # — это "не трогать", а не "стереть" (см. Post.set_status), так что
            # старый reason от предыдущего FAILED (например, при ретрае поста,
            # который в этот раз ушёл во ВСЕ группы) остался бы висеть на уже
            # успешно опубликованном посте (найдено на повторном ревью).
            post.status_reason = (
                f"частично: не опубликовано в {', '.join(str(c) for c in failed_chat_ids)}"
                if failed_chat_ids else None
            )
            post.set_status(PostStatus.POSTED)
