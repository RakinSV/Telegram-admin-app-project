"""CRUD-логика целевых групп публикации (F08, F12).

Переиспользуется `cli.py` (add-target/list-targets) и веб-админкой
(`webui/app.py`, роуты `/targets`), Фаза 5.3.
"""

from __future__ import annotations

from tg_repost.db.models import TargetGroup
from tg_repost.db.session import session_scope


def add_target(chat_id: int, title: str | None = None) -> tuple[TargetGroup, bool]:
    """Добавить целевую группу или реактивировать существующую.

    Возвращает (TargetGroup, created).
    """
    with session_scope() as session:
        existing = session.query(TargetGroup).filter(TargetGroup.chat_id == chat_id).one_or_none()
        if existing:
            existing.is_active = True
            if title:
                existing.title = title
            session.flush()
            session.refresh(existing)
            return existing, False
        target = TargetGroup(chat_id=chat_id, title=title, is_active=True)
        session.add(target)
        session.flush()
        session.refresh(target)
        return target, True


def list_targets(limit: int = 500) -> list[TargetGroup]:
    with session_scope() as session:
        return session.query(TargetGroup).order_by(TargetGroup.id).limit(limit).all()


def get_target(target_id: int) -> TargetGroup | None:
    with session_scope() as session:
        return session.get(TargetGroup, target_id)


def toggle_target(target_id: int) -> bool | None:
    """Переключить is_active. Возвращает новое значение, либо None, если
    цель не найдена."""
    with session_scope() as session:
        target = session.get(TargetGroup, target_id)
        if target is None:
            return None
        target.is_active = not target.is_active
        return target.is_active
