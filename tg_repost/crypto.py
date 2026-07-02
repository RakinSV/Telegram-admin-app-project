"""Шифрование секретов at rest и генерация бутстрап-ключей (F23, Фаза 5).

Низкоуровневый модуль без зависимостей от `config.py`/`db/` — намеренно, чтобы
и `config.py` (оверлей настроек), и `webui/` могли его использовать без
циклических импортов. `Fernet` (симметричное аутентифицированное шифрование) —
пропорциональный выбор для одного владельца системы, без сырых
`cryptography.hazmat`-примитивов.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

# Сколько последних символов секрета показывать в маске (например "••••a1b2").
_MASK_VISIBLE_CHARS = 4
_MASK_BULLET = "•"


def generate_key() -> str:
    """Сгенерировать новый ключ Fernet (для WEBUI_MASTER_KEY/WEBUI_SESSION_SECRET)."""
    return Fernet.generate_key().decode("ascii")


def encrypt(plaintext: str, key: str) -> str:
    """Зашифровать строку ключом Fernet."""
    return Fernet(key.encode("ascii")).encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(token: str, key: str) -> str:
    """Расшифровать строку. Бросает `cryptography.fernet.InvalidToken` при
    неверном ключе или повреждённом токене."""
    return Fernet(key.encode("ascii")).decrypt(token.encode("ascii")).decode("utf-8")


def mask(plaintext: str) -> str:
    """Маска для отображения в UI: точки + последние символы (чистая функция).

    Секрет короче порога видимости маскируется полностью — иначе показ
    "последних 4 символов" 3-символьного значения раскрыл бы его целиком.
    """
    if len(plaintext) <= _MASK_VISIBLE_CHARS:
        return _MASK_BULLET * 4
    return _MASK_BULLET * 4 + plaintext[-_MASK_VISIBLE_CHARS:]


def append_env_var(name: str, value: str, env_path: str = ".env") -> None:
    """Добавить `NAME=value` в конец `.env`-файла (создать, если его нет) И
    сразу выставить `os.environ[name]` в этом же процессе.

    Используется для одноразовой генерации бутстрап-ключей (WEBUI_MASTER_KEY,
    WEBUI_SESSION_SECRET) при первом запуске setup-визарда. Не трогает
    существующее содержимое файла — только дописывает новую строку.

    КРИТИЧНО обновлять `os.environ` тут же, а не полагаться на то, что
    следующий `Settings()` перечитает файл: в Docker Compose `env_file: -
    .env` выставляет `os.environ` ОДИН РАЗ при старте контейнера (пустым
    плейсхолдером из `.env.example`, т.к. на тот момент ключ ещё не
    сгенерирован) — а pydantic-settings берёт `os.environ` ПРИОРИТЕТНЕЕ
    повторного чтения `.env`-файла (проверено эмпирически). Без этой строки
    сгенерированный ключ никогда не подхватывался бы ЭТИМ процессом: он
    записан на диск, но `Settings().webui_master_key` продолжал бы читаться
    как "" до перезапуска контейнера — из-за чего `ensure_master_key()`
    генерировал НОВЫЙ ключ на каждый следующий вызов, падая с `RuntimeError`,
    как только в БД появлялся хотя бы один секрет (найдено на реальном
    Docker-деплое: второе сохранение секрета падало 500-й, а первое
    "успешно" сохранённое значение было навсегда нерасшифровываемым —
    `_apply_secret_overrides` молча выходит при пустом `webui_master_key`).
    """
    path = Path(env_path)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    needs_newline = bool(existing) and not existing.endswith("\n")
    with path.open("a", encoding="utf-8") as fh:
        if needs_newline:
            fh.write("\n")
        fh.write(f"{name}={value}\n")
    os.environ[name] = value
    # `.env` содержит бутстрап-ключи шифрования секретов — на Linux/VPS
    # (см. роадмап в CLAUDE.md) права по умолчанию зависят от umask
    # процесса, а не гарантированно ограничены. На Windows `os.chmod` не
    # даёт POSIX-семантики (только снимает read-only), но и не вредит —
    # реальная защита там через NTFS ACL. Найдено при аудите Фазы 5.
    with contextlib.suppress(OSError):
        os.chmod(path, 0o600)


__all__ = [
    "InvalidToken",
    "append_env_var",
    "decrypt",
    "encrypt",
    "generate_key",
    "mask",
]
