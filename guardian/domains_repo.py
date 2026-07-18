"""CRUD whitelist доменов для фильтра ссылок (G04), раздельно по каждой
защищаемой группе (F28) — хранится в отдельной таблице `allowed_domains`,
общий слой для Telegram-команд и веб-админки tg_repost (см.
`stopwords_repo.py` про разделение ответственности и симметричную схему).

Раньше хранился ОДНИМ общим JSON-списком внутри `bot_config['allowed_domains']`
— перенесено в таблицу миграцией 0002_per_chat_lists, `updated_by` переиме-
нован в `added_by` для единообразия со `StopWord` (у отдельных строк нет
единого "updated_at" списка, есть `added_at` на каждую запись)."""

from __future__ import annotations

from guardian.db.models import AllowedDomain
from guardian.db.session import session_scope


def list_allowed_domains(chat_id: int) -> list[str]:
    with session_scope() as session:
        return [
            row.domain
            for row in session.query(AllowedDomain)
            .filter(AllowedDomain.chat_id == chat_id)
            .order_by(AllowedDomain.domain)
            .all()
        ]


def add_allowed_domain(domain: str, chat_id: int, updated_by: str) -> str:
    """Вернуть нормализованный домен (без `www.`, lowercase), реально
    добавленный в whitelist ЭТОЙ группы — пустая строка, если после
    нормализации нечего добавлять (входная строка пуста/состоит из
    пробелов/была одним `www.`) или домен уже был в списке — вызывающий
    код (веб-роут/Telegram-команда) обязан проверить непустоту перед тем
    как считать операцию успешной."""
    domain = domain.strip().lower().removeprefix("www.")
    if not domain:
        return ""
    with session_scope() as session:
        exists = (
            session.query(AllowedDomain)
            .filter(AllowedDomain.domain == domain, AllowedDomain.chat_id == chat_id)
            .one_or_none()
        )
        if exists is not None:
            return ""
        session.add(AllowedDomain(domain=domain, chat_id=chat_id, added_by=updated_by))
    return domain


def remove_allowed_domain(domain: str, chat_id: int, updated_by: str) -> bool:
    """True, если домен реально был в списке ЭТОЙ группы (и удалён).
    `updated_by` в сигнатуре только ради симметрии вызова с
    `add_allowed_domain` — удаление не оставляет "кто изменил" запись per
    row (строка целиком исчезает), в отличие от добавления."""
    del updated_by
    domain = domain.strip().lower().removeprefix("www.")
    with session_scope() as session:
        deleted = (
            session.query(AllowedDomain)
            .filter(AllowedDomain.domain == domain, AllowedDomain.chat_id == chat_id)
            .delete()
        )
        return deleted > 0
