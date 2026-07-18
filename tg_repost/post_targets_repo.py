"""CRUD-доступ к `PostTarget` (F29) — по одной строке на каждую попытку
публикации поста в конкретную цель, заполняется `telegram/publisher.py::
publish_post`, читается веб-админкой/ботом для управления уже
опубликованным постом (редактирование/удаление/закрепление по каждой цели)."""

from __future__ import annotations

from tg_repost.db.models import PostTarget
from tg_repost.db.session import session_scope


def record_targets(
    post_id: int, results: list[tuple[int, int | None, str | None]]
) -> None:
    """Записать результаты публикации (chat_id, message_id, error) для
    ВСЕХ целей одним вызовом — `error is None` значит успех."""
    with session_scope() as session:
        for chat_id, message_id, error in results:
            session.add(
                PostTarget(
                    post_id=post_id,
                    chat_id=chat_id,
                    message_id=message_id,
                    ok=error is None,
                    error=error,
                )
            )


def list_targets_for_post(post_id: int) -> list[PostTarget]:
    with session_scope() as session:
        return (
            session.query(PostTarget)
            .filter(PostTarget.post_id == post_id)
            .order_by(PostTarget.id)
            .all()
        )


def get_target(target_id: int) -> PostTarget | None:
    with session_scope() as session:
        return session.get(PostTarget, target_id)


def set_message_id(target_id: int, message_id: int | None) -> bool:
    """После удаления сообщения обнуляем `message_id` — дальнейшие
    edit/pin по этой цели должны видеть "уже удалено", не пытаться
    действовать на несуществующее сообщение."""
    with session_scope() as session:
        target = session.get(PostTarget, target_id)
        if target is None:
            return False
        target.message_id = message_id
        return True


def set_pinned(target_id: int, pinned: bool) -> bool:
    with session_scope() as session:
        target = session.get(PostTarget, target_id)
        if target is None:
            return False
        target.pinned = pinned
        return True
