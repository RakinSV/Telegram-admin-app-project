"""CRUD-логика целевых групп публикации (F08, F12).

Переиспользуется `cli.py` (add-target/list-targets) и веб-админкой
(`webui/app.py`, роуты `/targets`), Фаза 5.3.
"""

from __future__ import annotations

from tg_repost.db.models import TargetGroup
from tg_repost.db.session import session_scope
from tg_repost.text_sanitize import strip_bidi_control_chars


def add_target(chat_id: int, title: str | None = None) -> tuple[TargetGroup, bool]:
    """Добавить целевую группу или реактивировать существующую.

    Возвращает (TargetGroup, created). `title` санитизируется от zero-width/
    bidi-трюков — часто приходит напрямую из чужого чата (см. targets.html,
    кнопка «Добавить как цель» из discovered_chats)."""
    title = strip_bidi_control_chars(title)
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


def sync_can_post(chat_id: int, can_post: bool | None) -> bool:
    """Актуализировать `TargetGroup.can_post` для уже добавленной цели
    (F08-доп., аудит ведения групп раунд 3) — вызывается из того же
    `my_chat_member`-апдейта, что и `discovered_chats_repo.record_discovered_chat`,
    но здесь это НЕ upsert: если чат ещё не цель — просто no-op (False),
    ничего не создаём. Возвращает True, если цель была найдена и обновлена."""
    with session_scope() as session:
        target = session.query(TargetGroup).filter(TargetGroup.chat_id == chat_id).one_or_none()
        if target is None:
            return False
        target.can_post = can_post
        return True
