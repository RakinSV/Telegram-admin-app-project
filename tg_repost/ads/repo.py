"""CRUD-логика брифов нативной рекламы (F21).

Отдельно от `injector.py` (выбор/генерация рекламного поста, F21 пайплайн) —
это управление списком брифов, переиспользуется `cli.py` и веб-админкой
(`webui/app.py`, роуты `/ads`), Фаза 5.3.
"""

from __future__ import annotations

from tg_repost.db.models import AdBrief
from tg_repost.db.session import session_scope


def add_brief(brief_text: str, max_uses: int | None = None) -> AdBrief:
    with session_scope() as session:
        brief = AdBrief(brief_text=brief_text, is_active=True, max_uses=max_uses)
        session.add(brief)
        session.flush()
        session.refresh(brief)
        return brief


def list_briefs(limit: int = 500) -> list[AdBrief]:
    with session_scope() as session:
        return session.query(AdBrief).order_by(AdBrief.id).limit(limit).all()


def get_brief(brief_id: int) -> AdBrief | None:
    with session_scope() as session:
        return session.get(AdBrief, brief_id)


def disable_brief(brief_id: int) -> bool:
    with session_scope() as session:
        brief = session.get(AdBrief, brief_id)
        if brief is None:
            return False
        brief.is_active = False
        return True
