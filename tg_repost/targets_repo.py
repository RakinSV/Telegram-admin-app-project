"""CRUD-логика целевых групп публикации (F08, F12).

Переиспользуется `cli.py` (add-target/list-targets) и веб-админкой
(`webui/app.py`, роуты `/targets`), Фаза 5.3.
"""

from __future__ import annotations

from tg_repost import languages
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


def set_language(target_id: int, language: str) -> str | None:
    """Задать язык публикации группы. Возвращает применённый код (нормализо-
    ванный) либо None, если цели нет.

    Неизвестный код молча приводится к языку по умолчанию, а не отвергается:
    единственный источник значений — выпадающий список в админке, и падать
    из-за подделанной формы тут не на чем.
    """
    normalized = languages.normalize(language)
    with session_scope() as session:
        target = session.get(TargetGroup, target_id)
        if target is None:
            return None
        target.language = normalized
        return normalized


def toggle_guardian(target_id: int) -> bool | None:
    """F28: переключить use_guardian. Возвращает новое значение, либо None,
    если цель не найдена. Список защищаемых чатов в guardian.bot_config
    синхронизируется ОТДЕЛЬНО вызывающим кодом (см.
    `webui/crud_routes.py::targets_toggle_guardian`) — эта функция только
    меняет tg_repost-сторону, ничего не знает про Guardian."""
    with session_scope() as session:
        target = session.get(TargetGroup, target_id)
        if target is None:
            return None
        target.use_guardian = not target.use_guardian
        return target.use_guardian


def list_guardian_chat_ids() -> list[int]:
    """F28: chat_id всех целей с use_guardian=True — источник истины для
    guardian.bot_config.protected_chat_ids."""
    with session_scope() as session:
        rows = (
            session.query(TargetGroup.chat_id)
            .filter(TargetGroup.use_guardian.is_(True))
            .all()
        )
        return [r[0] for r in rows]


def list_guardian_targets() -> list[tuple[int, str]]:
    """F28: (chat_id, отображаемое_имя) всех целей с use_guardian=True —
    для селектора группы на страницах Guardian в веб-админке (стоп-слова/
    домены/доверенные теперь раздельны по каждой группе)."""
    with session_scope() as session:
        rows = (
            session.query(TargetGroup.chat_id, TargetGroup.title)
            .filter(TargetGroup.use_guardian.is_(True))
            .order_by(TargetGroup.id)
            .all()
        )
        return [(chat_id, title or f"id{chat_id}") for chat_id, title in rows]


def sync_guardian_can_moderate(chat_id: int, can_moderate: bool | None) -> bool:
    """F28.10: актуализировать `TargetGroup.guardian_can_moderate` — вызывается
    ИЗ ОТДЕЛЬНОГО процесса Guardian (см. `guardian/handlers/chat_member.py`),
    кросс-пакетный импорт `tg_repost.targets_repo`, симметрично тому, как
    `webui/guardian_routes.py` читает/пишет БД Guardian в обратную сторону.
    No-op (False), если чат ещё не цель — Guardian мог получить админку в
    чате, который репост-бот никуда не публикует."""
    with session_scope() as session:
        target = session.query(TargetGroup).filter(TargetGroup.chat_id == chat_id).one_or_none()
        if target is None:
            return False
        target.guardian_can_moderate = can_moderate
        return True


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
