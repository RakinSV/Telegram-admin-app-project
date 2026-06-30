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

# Схема для тестов, которые читают/пишут БД напрямую (Фаза 4: ads/growth).
# sqlite:///:memory: в этом процессе использует один и тот же engine-синглтон
# (tg_repost.db.session.engine создаётся один раз при первом импорте), поэтому
# таблицы достаточно создать один раз здесь, до сбора тестов.
from tg_repost.db.models import Base  # noqa: E402
from tg_repost.db.session import engine  # noqa: E402

Base.metadata.create_all(engine)
