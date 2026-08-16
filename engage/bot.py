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
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from engage.config import get_engage_settings
from engage.handlers import (
    cabinet,
    contest,
    quiz,
    referral,
    shop,
    start,
    subscription,
    suggest,
    support,
)
from tg_repost.scheduler.subscriptions import revoke_expired_subscriptions
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


def build_reply_bot() -> Bot | None:
    """Бот Engage для разовой отправки из веб-админки (F68).

    `None` — токен не настроен. Отдельная функция, а не переиспользование
    работающего экземпляра: веб-процесс и процесс Engage разные, общего
    объекта у них нет, а поднимать ради одного сообщения весь диспетчер
    незачем.

    Отвечать нужно именно ЭТИМ ботом — тем, которому человек написал. Ответ
    от другого бота для него сообщение от неизвестного адресата, и половина
    решит, что это спам.
    """
    settings = get_engage_settings()
    if not settings.is_configured:
        return None
    return _build_bot(settings.engage_bot_token)


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
    dp.include_router(quiz.router)
    dp.include_router(referral.router)
    dp.include_router(contest.router)
    # F74: кнопка кабинета. Одна команда без состояния — порядок ей
    # безразличен, лишь бы до поддержки, которая глотает всё подряд.
    dp.include_router(cabinet.router)
    dp.include_router(suggest.router)
    # F49: платежи — до поддержки, но после предложки. Обработчик
    # `successful_payment` ловит служебное сообщение, а не текст, поэтому
    # предложке он не мешает; зато поставленный ПОСЛЕ поддержки он не
    # сработал бы вовсе — та ловит любое личное сообщение.
    dp.include_router(subscription.router)
    # F69: магазин. Свои фильтры по префиксу payload, поэтому с подпиской не
    # спорит: `sub:` и `ord:` разбираются разными обработчиками.
    dp.include_router(shop.router)
    # F68: поддержка — СТРОГО ПОСЛЕДНЯЯ. Она ловит любое личное сообщение,
    # не разобранное выше; поставь её раньше — и она проглотит текст, который
    # ждёт предложка (FSM-состояние в suggest.router), а обнаружится это по
    # тишине в ответ на обычные команды.
    dp.include_router(support.router)

    # Публикация созревших викторин (F43). Минутный тик: сама задержка
    # после поста задаётся настройкой quiz_delay_minutes, здесь только
    # частота проверки «не пора ли».
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        quiz.publish_pending_quizzes, IntervalTrigger(minutes=1),
        args=[bot], id="publish_quizzes",
    )
    # F42: подтверждение созревших рефералов. Раз в час достаточно —
    # срок измеряется днями, точность до минуты тут не нужна.
    scheduler.add_job(
        referral.confirm_referrals_job, IntervalTrigger(hours=1),
        id="confirm_referrals",
    )
    # F44: розыгрыш конкурсов, у которых вышел срок. Раз в 5 минут —
    # опоздание с итогами читается как «организатор тянет время».
    scheduler.add_job(
        contest.draw_due_contests, IntervalTrigger(minutes=5),
        args=[bot], id="draw_contests",
    )
    # F49: закрытие доступа по окончании подписки. Раз в час — у самой
    # проверки уже есть запас в несколько часов (продление приходит
    # отдельным апдейтом и может опоздать), поэтому частить нечем помочь, а
    # каждый проход это лишние обращения к Telegram.
    scheduler.add_job(
        revoke_expired_subscriptions, IntervalTrigger(hours=1),
        args=[bot], id="revoke_subscriptions",
    )
    scheduler.start()

    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
