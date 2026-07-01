"""CRUD стоп-слов (G03) — общий слой для Telegram-команд (`handlers/admin.py`)
и веб-админки tg_repost (`tg_repost/webui/guardian_routes.py`). Чистый доступ
к БД, без Telegram-side-effects (уведомление в лог-канал — забота вызывающей
стороны, см. docstring `handlers/admin.py`)."""

from __future__ import annotations

from guardian.db.models import StopWord
from guardian.db.session import session_scope


def list_stopwords() -> list[str]:
    with session_scope() as session:
        return [
            row.word for row in session.query(StopWord).order_by(StopWord.word).all()
        ]


def add_stopword(word: str, added_by: str) -> bool:
    """True, если слово реально добавлено (False — уже было)."""
    word = word.strip().lower()
    if not word:
        return False
    with session_scope() as session:
        if (
            session.query(StopWord).filter(StopWord.word == word).one_or_none()
            is not None
        ):
            return False
        session.add(StopWord(word=word, added_by=added_by))
        return True


def remove_stopword(word: str) -> bool:
    """True, если что-то реально удалено."""
    word = word.strip().lower()
    with session_scope() as session:
        deleted = session.query(StopWord).filter(StopWord.word == word).delete()
        return deleted > 0
