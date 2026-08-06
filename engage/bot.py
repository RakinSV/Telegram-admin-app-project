"""Точка входа Engage — бота вовлечения участников (F42–F47).

Запуск: python -m engage.bot

Отдельный процесс со своим токеном, но с ОБЩЕЙ с tg_repost базой (почему —
см. `engage/config.py`). Миграции не свои: таблицы Engage живут в цепочке
tg_repost и применяются его же entrypoint'ом — двух alembic-цепочек на одну
БД быть не должно.
"""

from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from engage.config import get_engage_settings
from engage.handlers import start
from tg_repost import proxy as proxy_module
from tg_repost.config import get_settings
from tg_repost.logging_conf import get_logger, setup_logging

logger = get_logger(__name__)


def _build_bot(token: str) -> Bot:
    """Собрать бота, при необходимости через прокси.

    Прокси берётся из ЕДИНОГО раздела tg_repost (галочка «использовать для
    Telegram») — Engage ходит в тот же Telegram, что и остальные два процесса,
    и заводить ему отдельную настройку значило бы гарантированно про неё
    забыть при смене прокси.
    """
    proxy_url = proxy_module.httpx_proxy_url(get_settings(), "telegram")
    session = AiohttpSession(proxy=proxy_url) if proxy_url else None
    return Bot(
        token=token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


async def main() -> None:
    setup_logging()
    settings = get_engage_settings()
    logger.info("Запуск Engage (бот вовлечения)...")

    if not settings.is_configured:
        logger.error(
            "ENGAGE_BOT_TOKEN не задан — Engage не может стартовать. Заведи "
            "ОТДЕЛЬНОГО бота у @BotFather (/newbot) и впиши токен в "
            "/settings, группа «Engage».",
        )
        return

    bot = _build_bot(settings.engage_bot_token)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(start.router)

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
