"""CRUD стоп-слов (G03) — общий слой для Telegram-команд (`handlers/admin.py`)
и веб-админки tg_repost (`tg_repost/webui/guardian_routes.py`). Чистый доступ
к БД, без Telegram-side-effects (уведомление в лог-канал — забота вызывающей
стороны, см. docstring `handlers/admin.py`).

F28: списки раздельно по каждой защищаемой группе (`chat_id` — обязательный
параметр везде ниже, не глобальный список)."""

from __future__ import annotations

from guardian.db.models import StopWord
from guardian.db.session import session_scope


def list_stopwords(chat_id: int) -> list[str]:
    with session_scope() as session:
        return [
            row.word
            for row in session.query(StopWord)
            .filter(StopWord.chat_id == chat_id)
            .order_by(StopWord.word)
            .all()
        ]


def add_stopword(word: str, chat_id: int, added_by: str) -> bool:
    """True, если слово реально добавлено (False — уже было в ЭТОЙ группе)."""
    word = word.strip().lower()
    if not word:
        return False
    with session_scope() as session:
        if (
            session.query(StopWord)
            .filter(StopWord.word == word, StopWord.chat_id == chat_id)
            .one_or_none()
            is not None
        ):
            return False
        session.add(StopWord(word=word, chat_id=chat_id, added_by=added_by))
        return True


def remove_stopword(word: str, chat_id: int) -> bool:
    """True, если что-то реально удалено (в ЭТОЙ группе)."""
    word = word.strip().lower()
    with session_scope() as session:
        deleted = (
            session.query(StopWord)
            .filter(StopWord.word == word, StopWord.chat_id == chat_id)
            .delete()
        )
        return deleted > 0
