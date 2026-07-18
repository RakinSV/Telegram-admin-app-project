"""Бизнес-логика модерации постов (F07).

Переиспользуется и Telegram-ботом (`telegram/moderation_bot.py`,
inline-кнопки ✅/❌/✏️), и веб-админкой (`webui/app.py`, роуты
`/moderation`), Фаза 5.3 — единая точка истины для approve/reject/edit,
обе UI-поверхности остаются согласованы с одной статус-машиной (F05).
"""

from __future__ import annotations

from telegram import Bot
from telegram.error import BadRequest

from tg_repost import post_targets_repo
from tg_repost.config import get_settings
from tg_repost.db.models import Post, PostStatus
from tg_repost.db.session import session_scope
from tg_repost.telegram.publisher import publish_post


def list_pending_posts(limit: int = 50) -> list[Post]:
    """Посты, ожидающие модерации (только что рерайчены или уже отправлены
    на модерацию ботом)."""
    with session_scope() as session:
        return (
            session.query(Post)
            .filter(Post.status.in_([PostStatus.REWRITTEN, PostStatus.PENDING_APPROVAL]))
            .order_by(Post.created_at.asc())
            .limit(limit)
            .all()
        )


def get_post(post_id: int) -> Post | None:
    with session_scope() as session:
        return session.get(Post, post_id)


async def approve_post(bot: Bot, post_id: int) -> str:
    """Одобрить пост: APPROVED, затем публикация сразу или постановка в
    очередь слотов (F11). Возвращает человекочитаемый исход.

    Бросает `InvalidStatusTransition` (см. db.models), если пост не в
    состоянии, допускающем одобрение — вызывающий код решает, как это
    показать пользователю.
    """
    settings = get_settings()
    with session_scope() as session:
        post = session.get(Post, post_id)
        if post is None:
            return "пост не найден"
        post.set_status(PostStatus.APPROVED)

    if settings.scheduled_posting_enabled:
        slots = ", ".join(settings.posting_slots) or "не заданы"
        return f"одобрен, в очереди публикации (слоты: {slots})"

    await publish_post(bot, post_id)
    with session_scope() as session:
        post = session.get(Post, post_id)
        return post.status.value if post else "неизвестно"


def reject_post(post_id: int, reason: str = "отклонено вручную") -> bool:
    """Отклонить пост. False, если не найден.

    Бросает `InvalidStatusTransition`, если текущий статус не допускает
    перехода в REJECTED (например REWRITTEN — отклонять можно только после
    PENDING_APPROVAL, см. db.models) — вызывающий код решает, как это
    показать пользователю."""
    with session_scope() as session:
        post = session.get(Post, post_id)
        if post is None:
            return False
        post.set_status(PostStatus.REJECTED, reason=reason)
        return True


def edit_post_text(post_id: int, new_text: str) -> bool:
    """Заменить rewritten_text (статус не трогаем — пост остаётся в очереди
    на повторное рассмотрение). False, если пост не найден."""
    with session_scope() as session:
        post = session.get(Post, post_id)
        if post is None:
            return False
        post.rewritten_text = new_text
        return True


# --- F29: управление УЖЕ ОПУБЛИКОВАННЫМ постом, по каждой цели отдельно ---
# (см. `db/models.py::PostTarget`, `post_targets_repo.py`) — независимо от
# approve/reject/edit выше, которые работают ТОЛЬКО до публикации.


async def edit_published_post(bot: Bot, target_id: int, new_text: str) -> str | None:
    """Отредактировать уже опубликованное сообщение в ОДНОЙ цели. Вернуть
    текст ошибки для показа пользователю, либо None при успехе.

    Если публикация шла с медиа — правим caption (лимит 1024 симв., см.
    `telegram/publisher.py::_MAX_CAPTION`), иначе — текст сообщения. Если
    исходный текст был длиннее лимита подписи, `_send_one` досылал хвост
    ОТДЕЛЬНЫМ сообщением — эта функция его не трогает (правит только
    первое/основное сообщение), ограничение осознанно принято ради
    простоты: составные посты правятся редко и полное отслеживание
    хвостового message_id не стоит доп. сложности на однопользовательском
    инструменте."""
    target = post_targets_repo.get_target(target_id)
    if target is None or not target.ok or target.message_id is None:
        return "Цель не найдена или сообщение туда не публиковалось."
    with session_scope() as session:
        post = session.get(Post, target.post_id)
        has_media = bool(post and post.media_path)
    try:
        if has_media:
            await bot.edit_message_caption(
                chat_id=target.chat_id, message_id=target.message_id,
                caption=new_text[:1024],
            )
        else:
            await bot.edit_message_text(
                chat_id=target.chat_id, message_id=target.message_id, text=new_text[:4096],
            )
    except BadRequest as exc:
        return str(exc)
    return None


async def delete_published_post(bot: Bot, target_id: int) -> str | None:
    """Удалить уже опубликованное сообщение в ОДНОЙ цели. None при успехе."""
    target = post_targets_repo.get_target(target_id)
    if target is None or not target.ok or target.message_id is None:
        return "Цель не найдена или сообщение туда не публиковалось."
    try:
        await bot.delete_message(chat_id=target.chat_id, message_id=target.message_id)
    except BadRequest as exc:
        return str(exc)
    post_targets_repo.set_message_id(target_id, None)
    return None


async def pin_published_post(bot: Bot, target_id: int, pin: bool) -> str | None:
    """Закрепить/открепить уже опубликованное сообщение в ОДНОЙ цели.
    None при успехе."""
    target = post_targets_repo.get_target(target_id)
    if target is None or not target.ok or target.message_id is None:
        return "Цель не найдена или сообщение туда не публиковалось."
    try:
        if pin:
            await bot.pin_chat_message(
                chat_id=target.chat_id, message_id=target.message_id,
                disable_notification=True,
            )
        else:
            await bot.unpin_chat_message(chat_id=target.chat_id, message_id=target.message_id)
    except BadRequest as exc:
        return str(exc)
    post_targets_repo.set_pinned(target_id, pin)
    return None
