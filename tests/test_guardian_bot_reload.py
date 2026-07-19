"""Регрессионный тест на находку код-ревью: `_reload_filters` (периодическая
джоба `bot.py`, ловит изменения стоп-слов/доменов/порогов антифлуда,
сделанные из ДРУГОГО процесса — веб-админки tg_repost) раньше не трогала
`flood_filter` вообще — `/guardian/settings/flood` молча ничего не применял
без перезапуска Guardian, хотя страница настроек утверждает "применяются
сразу"."""

from __future__ import annotations

import pytest

from guardian import settings_store
from guardian.bot import _reload_filters
from guardian.config import invalidate_settings_cache
from guardian.db.models import BotConfig
from guardian.db.session import session_scope
from guardian.handlers import messages as messages_handlers


@pytest.fixture(autouse=True)
def _isolated():
    with session_scope() as session:
        session.query(BotConfig).delete()
    invalidate_settings_cache()
    yield
    with session_scope() as session:
        session.query(BotConfig).delete()
    invalidate_settings_cache()
    messages_handlers.flood_filter.update_limits(
        max_messages=messages_handlers._settings.flood_max_messages,
        window_seconds=messages_handlers._settings.flood_window_seconds,
    )


def test_reload_filters_applies_updated_flood_thresholds():
    settings_store.save_setting("flood_max_messages", 1, "int")
    settings_store.save_setting("flood_window_seconds", 5, "int")

    _reload_filters()

    ff = messages_handlers.flood_filter
    assert ff._max_messages == 1
    assert ff._window_seconds == 5
    # Поведенчески: второе сообщение в окне уже превышает новый (низкий) порог.
    assert ff.check_flood(-100123, user_id=1, now=0.0) is False
    assert ff.check_flood(-100123, user_id=1, now=0.5) is True
