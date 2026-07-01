"""Настройка логирования Guardian — тот же паттерн, что
`tg_repost.logging_conf`, отдельный файл лога (`logs/guardian.log`), т.к.
Guardian — отдельный процесс/контейнер (см. guardian/GUARDIAN.md)."""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

_LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_configured = False


def ensure_utf8_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def setup_logging(level: str = "INFO") -> None:
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
        "logs/guardian.log",
        maxBytes=5_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
