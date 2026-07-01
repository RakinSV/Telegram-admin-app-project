"""Одноразовый токен, гейтящий `/setup*` до создания администратора (F23,
аудит Фазы 5).

`/setup/telethon` может привязать живую Telethon-сессию БЕЗ пароля (пароль
задаётся позже, на том же экране) — самый «дорогой» неавторизованный
эндпоинт всей админки. Токен печатается в лог при старте процесса, пока
администратор не создан (см. `main.py`) — доступ к консоли/логам сервера
уже подразумевает доверие, поэтому это не ослабляет модель угроз, а сужает
окно для LAN/VPN-соседей без доступа к самой машине.

Токен живёт только в памяти процесса (не персистится) — после рестарта
генерируется заново, что нормально: он актуален только до первого /setup.
"""

from __future__ import annotations

import secrets

_token: str | None = None


def get_or_create_setup_token() -> str:
    """Вернуть текущий токен, сгенерировав его при первом обращении."""
    global _token
    if _token is None:
        _token = secrets.token_urlsafe(24)
    return _token


def verify_setup_token(candidate: str | None) -> bool:
    """Сверить токен константным по времени сравнением."""
    if not candidate:
        return False
    return secrets.compare_digest(candidate, get_or_create_setup_token())
