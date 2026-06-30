"""CRUD-логика источников (F01, F12, F15, F16).

Переиспользуется `cli.py` (команды add-source/set-source-*) и веб-админкой
(`webui/app.py`, роуты `/sources`) — единая точка истины вместо дублирования
SQLAlchemy-запросов в обоих местах (Фаза 5.3, см. план).
"""

from __future__ import annotations

from tg_repost.db.models import Source
from tg_repost.db.session import session_scope


def normalize_username(raw: str) -> str:
    """Привести @name / https://t.me/name к виду 'name' (чистая функция)."""
    raw = raw.strip()
    raw = raw.removeprefix("https://t.me/").removeprefix("t.me/")
    raw = raw.lstrip("@")
    return raw


def add_source(channel: str) -> tuple[Source, bool]:
    """Добавить источник или реактивировать существующий.

    Возвращает (Source, created) — created=False, если запись уже была
    (и была лишь реактивирована).
    """
    username = normalize_username(channel)
    with session_scope() as session:
        existing = session.query(Source).filter(Source.channel_username == username).one_or_none()
        if existing:
            existing.is_active = True
            session.flush()
            session.refresh(existing)
            return existing, False
        source = Source(channel_username=username, is_active=True)
        session.add(source)
        session.flush()
        session.refresh(source)
        return source, True


def list_sources(limit: int = 500) -> list[Source]:
    """Источники (активные и неактивные), по id, не более `limit` штук."""
    with session_scope() as session:
        return session.query(Source).order_by(Source.id).limit(limit).all()


def get_source(source_id: int) -> Source | None:
    with session_scope() as session:
        return session.get(Source, source_id)


def find_source_by_username(channel: str) -> Source | None:
    username = normalize_username(channel)
    with session_scope() as session:
        return session.query(Source).filter(Source.channel_username == username).one_or_none()


def deactivate_source(source_id: int) -> bool:
    """Мягкое удаление (is_active=False). False, если источник не найден."""
    with session_scope() as session:
        source = session.get(Source, source_id)
        if source is None:
            return False
        source.is_active = False
        return True


def set_source_style(source_id: int, style: str) -> bool:
    """F15 — стиль рерайта для источника. False, если источник не найден."""
    with session_scope() as session:
        source = session.get(Source, source_id)
        if source is None:
            return False
        source.style_profile = style
        return True


def set_source_enrich(source_id: int, mode: str) -> bool:
    """F16 — добор источников: mode = 'on' | 'off' | 'default'."""
    mapping: dict[str, bool | None] = {"on": True, "off": False, "default": None}
    if mode not in mapping:
        raise ValueError(f"Неизвестный режим: {mode}")
    with session_scope() as session:
        source = session.get(Source, source_id)
        if source is None:
            return False
        source.enrich_sources = mapping[mode]
        return True


def set_source_targets(source_id: int, chat_ids_csv: str | None) -> bool:
    """F12 — переопределение целевых групп. Пустая строка/None — очистить
    (публикация во все активные). Бросает ValueError, если CSV содержит
    нечисловой мусор."""
    with session_scope() as session:
        source = session.get(Source, source_id)
        if source is None:
            return False
        if not chat_ids_csv or not chat_ids_csv.strip():
            source.target_chat_ids = None
            return True
        ids = [c.strip() for c in chat_ids_csv.split(",") if c.strip()]
        for c in ids:
            int(c)  # бросит ValueError при нечисловом мусоре
        source.target_chat_ids = ",".join(ids)
        return True
