"""Антифлуд (G06) — состояние только в памяти процесса (не в БД): счётчики
сбрасываются при перезапуске Guardian, что приемлемо — это защита от
всплеска здесь-и-сейчас, не журнал нарушений (тот уже есть в `warnings`).

F28-аудит: раздельно по каждой защищаемой группе (`(chat_id, user_id)`) —
раньше ключом был голый `user_id`, из-за чего активность пользователя в
ОДНОЙ группе (окно флуда, "последний текст") могла ложно сработать против
него в ДРУГОЙ группе, если он состоит в нескольких защищаемых группах
одновременно (найдено на аудите: keyword_filter/link_filter уже были
раздельны, этот файл — нет)."""

from __future__ import annotations

import time
from collections import defaultdict, deque


class FloodFilter:
    def __init__(self, max_messages: int, window_seconds: int) -> None:
        self._max_messages = max_messages
        self._window_seconds = window_seconds
        self._timestamps: dict[tuple[int, int], deque[float]] = defaultdict(deque)
        self._last_text: dict[tuple[int, int], str] = {}

    def update_limits(self, max_messages: int, window_seconds: int) -> None:
        """Применить новые пороги без потери накопленного состояния —
        вызывается периодической джобой `bot.py::_reload_filters`, чтобы
        изменения `flood_max_messages`/`flood_window_seconds` из
        `bot_config` (веб-админка или будущие Telegram-команды) применялись
        без пересоздания синглтона и без потери текущих окон пользователей."""
        self._max_messages = max_messages
        self._window_seconds = window_seconds

    def check_flood(self, chat_id: int, user_id: int, now: float | None = None) -> bool:
        """True, если пользователь превысил `max_messages` за `window_seconds`
        ИМЕННО в этой группе."""
        now = now if now is not None else time.monotonic()
        timestamps = self._timestamps[(chat_id, user_id)]
        timestamps.append(now)
        while timestamps and now - timestamps[0] > self._window_seconds:
            timestamps.popleft()
        return len(timestamps) > self._max_messages

    def check_duplicate(self, chat_id: int, user_id: int, text: str) -> bool:
        """True, если текст совпадает с предыдущим сообщением того же
        пользователя В ЭТОЙ ЖЕ группе (повтор подряд)."""
        key = (chat_id, user_id)
        previous = self._last_text.get(key)
        self._last_text[key] = text
        return previous is not None and previous == text
