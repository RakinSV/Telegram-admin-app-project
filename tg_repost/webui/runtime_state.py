"""Рантайм-статус долгоживущих компонентов для дашборда (F23, Фаза 5).

Простые модульные переменные — один процесс (веб-сервер встроен в тот же
asyncio-цикл, что и Telethon listener/бот/планировщик), межпроцессная
синхронизация не нужна. `main.py` обновляет статус при старте/остановке
компонентов; страницы веб-админки читают его для отображения.
"""

from __future__ import annotations

_state: dict[str, bool] = {"listener": False, "bot": False, "scheduler": False}


def set_component_status(name: str, running: bool) -> None:
    """Отметить компонент как запущенный/остановленный."""
    _state[name] = running


def get_component_status() -> dict[str, bool]:
    """Текущий статус всех известных компонентов (копия, без расшарки словаря)."""
    return dict(_state)
