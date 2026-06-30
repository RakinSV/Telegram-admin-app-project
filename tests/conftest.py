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
os.environ.setdefault("TG_TARGET_CHAT_ID", "-100")
os.environ.setdefault("OPENAI_API_KEY", "test")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
