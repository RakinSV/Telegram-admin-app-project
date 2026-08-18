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
