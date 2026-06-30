"""Точка входа (Фаза 1, шаг 11; Фаза 5 — веб-админка).

Запускает в одном asyncio-цикле:
  - Веб-админку FastAPI (F23, Фаза 5) — ВСЕГДА, первой, на 127.0.0.1:8000.
    Не зависит от Telegram-секретов, нужен только database_url (есть дефолт).
  - Telethon listener (чтение источников, F02-F04) — только если
    `settings.is_minimally_configured`; иначе ждём, пока секреты зададут
    через веб-визард `/setup`.
  - Бот модерации python-telegram-bot (F07) — аналогично.
  - APScheduler-тик пайплайна (рерайт + модерация/постинг, F06/F08).

Жизненный цикл Telethon/бота/планировщика вынесен в `webui/supervisor.py`
(Фаза 5.2) — он же переиспользуется веб-роутами `/components` для рестарта
без перезапуска процесса.

Запуск:  python -m tg_repost.main
"""

from __future__ import annotations

import asyncio

import uvicorn

from tg_repost.config import get_settings
from tg_repost.logging_conf import get_logger, setup_logging
from tg_repost.webui.app import create_app
from tg_repost.webui.supervisor import get_components, start_components, stop_components

logger = get_logger(__name__)

WEBUI_HOST = "127.0.0.1"
WEBUI_PORT = 8000


async def run() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    logger.info("Запуск Telegram Content Repost System v0.1")

    # --- Веб-админка (Фаза 5) — стартует всегда, первой ---
    web_app = create_app()
    uv_config = uvicorn.Config(web_app, host=WEBUI_HOST, port=WEBUI_PORT, log_level="warning")
    uv_server = uvicorn.Server(uv_config)
    # uvicorn.Server.serve() сам перехватывает SIGINT/SIGTERM через
    # signal.signal() (см. Server.capture_signals() в исходниках uvicorn) —
    # старых версий с методом install_signal_handlers() в текущей версии нет
    # (mypy справедливо находит это при сборке). Поэтому НЕ регистрируем
    # собственный loop.add_signal_handler() — это бы боролось с uvicorn за
    # один и тот же сигнал непредсказуемым образом. Вместо этого отдаём
    # сигналы целиком uvicorn (хорошо протестированная логика) и сами следим
    # за `uv_server.should_exit`, чтобы синхронно остановить и Telegram-часть.
    web_task = asyncio.create_task(uv_server.serve())
    logger.info("Веб-админка: http://%s:%d", WEBUI_HOST, WEBUI_PORT)

    # --- Telethon listener / бот / планировщик — только если хватает секретов ---
    if settings.is_minimally_configured:
        await start_components(settings)
    else:
        logger.warning(
            "Минимальная конфигурация не завершена (TG_API_ID/HASH, "
            "TG_BOT_TOKEN, TG_OWNER_USER_ID, OPENAI_API_KEY) — Telethon/бот/"
            "планировщик не запущены. Открой http://%s:%d/setup",
            WEBUI_HOST, WEBUI_PORT,
        )

    # --- Ожидание остановки: web_task сам завершается, когда uvicorn
    # обработает SIGINT/SIGTERM (см. комментарий выше) и грациозно
    # остановится — никакого опроса не нужно. Если веб-сервер не смог
    # стартовать (например порт занят), web_task завершится с исключением
    # сразу — тоже корректно пройдём через finally и остановим Telegram-часть.
    try:
        await web_task
    except asyncio.CancelledError:
        pass
    finally:
        logger.info("Останавливаюсь…")
        if get_components().is_running:
            await stop_components()
        # web_task в норме уже завершён к этому моменту (мы его только что
        # дождались выше) — здесь страховка на случай, если run() был отменён
        # извне ДО того, как web_task сам успел доработать.
        if not web_task.done():
            uv_server.should_exit = True
            await web_task
        logger.info("Остановлено.")


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
