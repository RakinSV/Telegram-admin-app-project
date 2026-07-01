"""CRUD whitelist доменов для фильтра ссылок (G04) — хранится в `bot_config`
(ключ `allowed_domains`, JSON-список), общий слой для Telegram-команд и
веб-админки tg_repost (см. `stopwords_repo.py` про разделение ответственности)."""

from __future__ import annotations

import json

from guardian.db.models import BotConfig
from guardian.db.session import session_scope

_KEY = "allowed_domains"


def list_allowed_domains() -> list[str]:
    with session_scope() as session:
        row = session.query(BotConfig).filter(BotConfig.key == _KEY).one_or_none()
        return sorted(json.loads(row.value)) if row is not None else []


def add_allowed_domain(domain: str, updated_by: str) -> str:
    """Вернуть нормализованный домен (без `www.`, lowercase), реально
    добавленный в whitelist — пустая строка, если после нормализации нечего
    добавлять (входная строка пуста/состоит из пробелов/была одним `www.`) —
    вызывающий код (веб-роут/Telegram-команда) обязан проверить непустоту
    перед тем как считать операцию успешной."""
    domain = domain.strip().lower().removeprefix("www.")
    if not domain:
        return ""
    with session_scope() as session:
        row = session.query(BotConfig).filter(BotConfig.key == _KEY).one_or_none()
        current = set(json.loads(row.value)) if row is not None else set()
        current.add(domain)
        value = json.dumps(sorted(current))
        if row is None:
            session.add(BotConfig(key=_KEY, value=value, updated_by=updated_by))
        else:
            row.value = value
            row.updated_by = updated_by
    return domain


def remove_allowed_domain(domain: str, updated_by: str) -> bool:
    """True, если домен реально был в списке (и удалён)."""
    domain = domain.strip().lower().removeprefix("www.")
    with session_scope() as session:
        row = session.query(BotConfig).filter(BotConfig.key == _KEY).one_or_none()
        if row is None:
            return False
        current = set(json.loads(row.value))
        if domain not in current:
            return False
        current.discard(domain)
        row.value = json.dumps(sorted(current))
        row.updated_by = updated_by
        return True
