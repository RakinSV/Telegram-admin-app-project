"""CRUD-логика обнаруженных чатов (F08-доп.) — куда владелец добавил
репост-бота, но ещё не подтвердил как целевую группу публикации.

Запись/удаление — из `telegram/moderation_bot.py` (апдейт `my_chat_member`,
приходит от Telegram при изменении статуса бота в чате). Чтение — веб-
админкой (`webui/crud_routes.py`, роут `/targets`), избавляет от ручного
поиска chat_id через сторонних ботов.
"""

from __future__ import annotations

from tg_repost.db.models import DiscoveredChat, TargetGroup
from tg_repost.db.session import session_scope


def record_discovered_chat(chat_id: int, title: str | None, chat_type: str) -> None:
    """Записать/обновить чат, где бот стал участником (upsert по chat_id)."""
    with session_scope() as session:
        existing = (
            session.query(DiscoveredChat).filter(DiscoveredChat.chat_id == chat_id).one_or_none()
        )
        if existing:
            existing.title = title
            existing.chat_type = chat_type
        else:
            session.add(DiscoveredChat(chat_id=chat_id, title=title, chat_type=chat_type))


def remove_discovered_chat(chat_id: int) -> None:
    """Убрать чат из списка обнаруженных — бот покинул чат или был удалён."""
    with session_scope() as session:
        session.query(DiscoveredChat).filter(DiscoveredChat.chat_id == chat_id).delete()


def list_pending_discovered_chats(limit: int = 100) -> list[DiscoveredChat]:
    """Обнаруженные чаты, ещё НЕ добавленные как целевая группа публикации —
    именно их имеет смысл показывать в /targets с кнопкой «Добавить»."""
    with session_scope() as session:
        target_chat_ids = session.query(TargetGroup.chat_id)
        return (
            session.query(DiscoveredChat)
            .filter(~DiscoveredChat.chat_id.in_(target_chat_ids))
            .order_by(DiscoveredChat.discovered_at.desc())
            .limit(limit)
            .all()
        )
