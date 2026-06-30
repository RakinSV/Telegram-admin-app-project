"""Бизнес-логика модерации постов (F07).

Переиспользуется и Telegram-ботом (`telegram/moderation_bot.py`,
inline-кнопки ✅/❌/✏️), и веб-админкой (`webui/app.py`, роуты
`/moderation`), Фаза 5.3 — единая точка истины для approve/reject/edit,
обе UI-поверхности остаются согласованы с одной статус-машиной (F05).
"""

from __future__ import annotations

from telegram import Bot

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
