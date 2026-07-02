"""Настройка логирования (F10).

Структурированный вывод в stdout и в файл `logs/tg_repost.log`. Подключается
один раз из `main.py` / `cli.py` через `setup_logging()`.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from logging.handlers import RotatingFileHandler

_LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_configured = False

# user:pass@ в URL прокси (socks5://user:pass@host:port, BOT_API_PROXY_URL) —
# ни `httpx`/`socksio`, ни `aiohttp_socks` не гарантируют, что их исключения
# при сбое подключения/авторизации через прокси НИКОГДА не отразят исходный
# URL целиком; код на нашей стороне логирует такие исключения как обычный
# %s, exc (найдено security-ревью). Используется в местах, где ошибка МОЖЕТ
# быть связана с прокси-подключением.
_PROXY_CREDS_RE = re.compile(r"://[^/@\s:]+:[^/@\s]+@")


def sanitize_proxy_error(text: str) -> str:
    """Вырезать логин:пароль из текста ошибки (см. `_PROXY_CREDS_RE`)."""
    return _PROXY_CREDS_RE.sub("://***:***@", text)


def ensure_utf8_stdout() -> None:
    """Перевести stdout/stderr в UTF-8.

    На Windows консоль по умолчанию бывает в cp1251 — тогда печать кириллицы и
    эмодзи (в логах и CLI) падает с UnicodeEncodeError. Безопасно вызывать
    многократно.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def setup_logging(level: str = "INFO") -> None:
    """Инициализировать корневой логгер. Повторные вызовы — no-op."""
    global _configured
    if _configured:
        return

    ensure_utf8_stdout()
    os.makedirs("logs", exist_ok=True)

    root = logging.getLogger()
    root.setLevel(level.upper())

    formatter = logging.Formatter(_LOG_FORMAT)

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(formatter)
    root.addHandler(stream)

    file_handler = RotatingFileHandler(
        "logs/tg_repost.log",
        maxBytes=5_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # SSE-хендлер веб-админки (F23, Фаза 5.4) — рассылает записи подписчикам
    # /logs/stream. Регистрируется всегда (в т.ч. для cli.py), но без живых
    # подписчиков просто копит ring-buffer в памяти — дёшево и безопасно.
    from tg_repost.webui.log_broadcast import SSELogHandler

    sse_handler = SSELogHandler()
    sse_handler.setFormatter(formatter)
    root.addHandler(sse_handler)

    # Приглушаем болтливые библиотеки.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telethon").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Получить именованный логгер."""
    return logging.getLogger(name)
