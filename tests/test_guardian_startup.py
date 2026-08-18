"""Поведение Guardian, когда его ещё не настроили (найдено на стенде).

Контейнер поднимается заново по политике `restart: unless-stopped`. Мгновенный
выход из-за незаполненного токена превращался в цикл перезапусков раз в
десяток секунд: лог забит одной и той же строкой, а настоящие сообщения в нём
тонут. На стенде это выглядело как «Guardian сломан», хотя сломан он не был —
ему просто не дали токен.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from guardian import bot as guardian_bot


@pytest.fixture
def _unconfigured():
    """Guardian без токена — ровно то состояние, в котором он на стенде."""
    settings = guardian_bot.get_guardian_settings().model_copy(
        update={"guardian_bot_token": ""},
    )
    with patch.object(guardian_bot, "get_guardian_settings", return_value=settings):
        yield settings


async def test_unconfigured_guardian_waits_before_exiting(_unconfigured):
    """Пауза перед выходом — это не лечение, а гигиена лога.

    Токен всё равно вводит владелец; смысл ожидания в том, чтобы контейнер не
    перезапускался раз в десяток секунд, пока он этого не сделал.
    """
    sleeper = AsyncMock()
    with patch.object(guardian_bot.asyncio, "sleep", sleeper):
        await guardian_bot.main()

    assert sleeper.await_count == 1
    waited = sleeper.await_args.args[0]
    assert waited >= 30, f"пауза {waited} с слишком короткая, лог останется забит"


async def test_unconfigured_guardian_does_not_start_polling(_unconfigured):
    """Без токена опрашивать нечего — и пытаться нельзя: aiogram упадёт на
    построении бота, а в логе появится трассировка вместо внятной причины."""
    with patch.object(guardian_bot.asyncio, "sleep", AsyncMock()), \
            patch.object(guardian_bot, "Dispatcher") as dispatcher:
        await guardian_bot.main()

    assert dispatcher.call_count == 0


# --- то же самое для Engage ---


@pytest.fixture
def _unconfigured_engage():
    from engage import bot as engage_bot

    settings = engage_bot.get_engage_settings().model_copy(
        update={"engage_bot_token": ""},
    )
    with patch.object(engage_bot, "get_engage_settings", return_value=settings):
        yield settings


async def test_unconfigured_engage_waits_before_exiting(_unconfigured_engage):
    """Третий бот — та же политика перезапуска, та же беда с логом.

    Engage вдобавок ДОЛГО не был развёрнут на стенде вовсе, и цикл
    перезапусков был бы первым, что владелец там увидит.
    """
    from engage import bot as engage_bot

    sleeper = AsyncMock()
    with patch.object(engage_bot.asyncio, "sleep", sleeper):
        await engage_bot.main()

    assert sleeper.await_count == 1
    assert sleeper.await_args.args[0] >= 30


async def test_unconfigured_engage_does_not_build_a_bot(_unconfigured_engage):
    from engage import bot as engage_bot

    with patch.object(engage_bot.asyncio, "sleep", AsyncMock()), \
            patch.object(engage_bot, "_build_bot") as build:
        await engage_bot.main()

    assert build.call_count == 0
