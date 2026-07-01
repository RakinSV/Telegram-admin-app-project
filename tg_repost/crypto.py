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
    """Добавить `NAME=value` в конец `.env`-файла (создать, если его нет).

    Используется для одноразовой генерации бутстрап-ключей (WEBUI_MASTER_KEY,
    WEBUI_SESSION_SECRET) при первом запуске setup-визарда. Не трогает
    существующее содержимое файла — только дописывает новую строку. Вызывающий
    код отвечает за то, чтобы не вызывать это повторно для уже заданного имени
    (см. `tg_repost.config.invalidate_settings_cache` для применения изменения
    без перезапуска процесса).
    """
    path = Path(env_path)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    needs_newline = bool(existing) and not existing.endswith("\n")
    with path.open("a", encoding="utf-8") as fh:
        if needs_newline:
            fh.write("\n")
        fh.write(f"{name}={value}\n")
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
