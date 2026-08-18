"""Тестовое окружение: подставляем безопасные значения настроек.

Часть модулей читает `get_settings()` на этапе импорта (например `db.session`
создаёт engine). Чтобы юнит-тесты не требовали реального `.env`, выставляем
фиктивные переменные и БД в памяти ДО импорта пакета.
"""

import os

os.environ.setdefault("TG_API_ID", "1")
os.environ.setdefault("TG_API_HASH", "test")
os.environ.setdefault("TG_BOT_TOKEN", "test")
os.environ.setdefault("TG_OWNER_USER_ID", "1")
os.environ.setdefault("OPENAI_API_KEY", "test")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("GUARDIAN_BOT_TOKEN", "test")
os.environ.setdefault("GUARDIAN_GROUP_ID", "-100123")
os.environ.setdefault("GUARDIAN_DATABASE_URL", "sqlite:///:memory:")

# Схема для тестов, которые читают/пишут БД напрямую (Фаза 4: ads/growth).
# sqlite:///:memory: в этом процессе использует один и тот же engine-синглтон
# (tg_repost.db.session.engine создаётся один раз при первом импорте), поэтому
# таблицы достаточно создать один раз здесь, до сбора тестов.
from tg_repost.db.models import Base
from tg_repost.db.session import engine

Base.metadata.create_all(engine)

# Та же логика для guardian — отдельная БД/engine (guardian.db.session), но
# тот же паттерн "создать схему один раз до сбора тестов".
from guardian.db.models import Base as GuardianBase  # noqa: E402
from guardian.db.session import engine as guardian_engine  # noqa: E402

GuardianBase.metadata.create_all(guardian_engine)


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_login_lockout():
    """Сбросить счётчик неудачных входов перед каждым тестом.

    ПОЧЕМУ ЭТО ЗДЕСЬ, А НЕ В ОДНОМ ФАЙЛЕ. Счётчик живёт в словаре уровня
    модуля и общий на весь процесс, а ключ у всех тестов один и тот же —
    `testclient`. Достаточно одному файлу проверить защиту от перебора
    (пять неудачных попыток — блокировка), и КАЖДЫЙ следующий файл, который
    логинится, получает 401 вместо входа.

    Найдено прогоном с перемешанным порядком файлов: пять проверок конкурсов
    падали не из-за конкурсов, а из-за соседа, проверявшего блокировку.
    Молча это выглядит как «тест сломался на ровном месте».
    """
    from tg_repost.webui import auth

    auth._failed_attempts.clear()
    yield
    auth._failed_attempts.clear()


@pytest.fixture(autouse=True)
def _isolated_runtime_singletons():
    """Живые компоненты и их статусы — на каждый тест свои.

    ПОЧЕМУ ЭТО ЗДЕСЬ. `supervisor._components` и `runtime_state._state` —
    переменные уровня модуля, одни на весь процесс: система по устройству
    однопроцессная, и для боя это правильно. Но в тестах это означает, что
    подставленный бот или поднятый планировщик переживают файл и достаются
    следующему.

    Найдено прогонами с перемешанным порядком файлов: проверка «без
    запущенных компонентов кнопка отвечает понятной ошибкой» падала, потому
    что компоненты были запущены — соседним файлом, десять минут назад.
    Такое падение выглядит как поломка на ровном месте и ищется дольше всего.
    """
    from tg_repost.webui import runtime_state, supervisor

    original_components = supervisor._components
    original_state = dict(runtime_state._state)
    supervisor._components = supervisor.RunningComponents()
    yield
    supervisor._components = original_components
    runtime_state._state.clear()
    runtime_state._state.update(original_state)


@pytest.fixture(autouse=True)
def _clean_audit_log():
    """Журнал действий — на каждый тест свой.

    ЕГО НИКТО НЕ ЧИСТИЛ, и записи копились через все файлы. Беда не в объёме:
    `list_audit_log()` отдаёт максимум 200 строк, и как только журнал
    переполнялся, проверка вида «записей стало больше, чем было» переставала
    работать — 200 не больше 200.

    Найдено прогонами с перемешанным порядком файлов: проверка записи факта
    показа секрета падала на двух сидах из трёх, причём в самом коде показа
    секрета ничего не менялось.
    """
    from tg_repost.db.models import AuditLog
    from tg_repost.db.session import session_scope

    with session_scope() as session:
        session.query(AuditLog).delete()
    yield


@pytest.fixture(autouse=True)
def _clean_guardian_config():
    """Конфиг Guardian (`bot_config`) — на каждый тест свой.

    ЭТО НЕ ПРОСТО ГИГИЕНА. `get_guardian_settings()` отдаёт ОДИН И ТОТ ЖЕ
    объект, пока таблица пуста, и СВЕЖУЮ КОПИЮ на каждый вызов, как только в
    ней появляется хоть одна строка (`model_copy`). То есть строка,
    оставленная одним файлом, меняет саму механику получения настроек для
    всех следующих — и патчи, поставленные на объект, перестают действовать.

    Найдено прогонами с перемешанным порядком файлов: файл проверок чистки и
    жалоб падал ЦЕЛИКОМ (десять проверок), причём в коде чистки не менялось
    ничего.
    """
    from guardian.db.models import BotConfig
    from guardian.db.session import session_scope as guardian_session_scope

    with guardian_session_scope() as session:
        session.query(BotConfig).delete()
    yield
