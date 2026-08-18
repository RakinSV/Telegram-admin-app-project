"""Тесты анализа профиля нового участника (G15)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramBadRequest

from guardian.config import get_guardian_settings
from guardian.services.profile_analyzer import compute_profile_score


def _bot(total_count: int = 1, bio: str = "") -> AsyncMock:
    bot = AsyncMock()
    bot.get_user_profile_photos = AsyncMock(return_value=SimpleNamespace(total_count=total_count))
    bot.get_chat = AsyncMock(return_value=SimpleNamespace(bio=bio))
    return bot


async def test_clean_profile_scores_zero():
    bot = _bot(total_count=1, bio="просто человек")
    score = await compute_profile_score(bot, user_id=100, username="realuser")
    assert score == 0


async def test_no_username_adds_one():
    bot = _bot()
    score = await compute_profile_score(bot, user_id=100, username=None)
    assert score == 1


async def test_new_account_id_adds_one():
    bot = _bot()
    score = await compute_profile_score(bot, user_id=8_000_000_000, username="user")
    assert score == 1


async def test_no_photo_adds_one():
    bot = _bot(total_count=0)
    score = await compute_profile_score(bot, user_id=100, username="user")
    assert score == 1


async def test_suspicious_bio_adds_two():
    bot = _bot(bio="Заработок от 1000$ в день, пиши")
    score = await compute_profile_score(bot, user_id=100, username="user")
    assert score == 2


async def test_all_signals_accumulate():
    bot = _bot(total_count=0, bio="crypto инвестиции")
    score = await compute_profile_score(bot, user_id=8_000_000_000, username=None)
    assert score == 1 + 1 + 1 + 2  # no username + new id + no photo + bio


async def test_photo_api_error_does_not_crash_or_add_score():
    bot = AsyncMock()
    bot.get_user_profile_photos = AsyncMock(side_effect=TelegramBadRequest(method=None, message="err"))
    bot.get_chat = AsyncMock(return_value=SimpleNamespace(bio=""))
    score = await compute_profile_score(bot, user_id=100, username="user")
    assert score == 0  # ошибка одного сигнала не ломает остальные


async def test_bio_api_error_does_not_crash_or_add_score():
    bot = AsyncMock()
    bot.get_user_profile_photos = AsyncMock(return_value=SimpleNamespace(total_count=1))
    bot.get_chat = AsyncMock(side_effect=TelegramBadRequest(method=None, message="err"))
    score = await compute_profile_score(bot, user_id=100, username="user")
    assert score == 0


# --- F52: Premium как сигнал доверия ---


@pytest.fixture
def _premium_on(monkeypatch):
    """Включить смягчение. По умолчанию оно ВЫКЛЮЧЕНО, поэтому каждый тест,
    который его проверяет, обязан включать явно — иначе тест зелёный по
    случайности, а не по существу."""
    # ПАТЧИМ ФУНКЦИЮ В МОДУЛЕ, А НЕ ОБЪЕКТ. `get_guardian_settings()` отдаёт
    # один и тот же объект только пока таблица `bot_config` пуста; стоит там
    # появиться строке — и каждый вызов возвращает свежую копию, а патч,
    # поставленный на прежний объект, исчезает вместе с ним. Найдено прогоном
    # с перемешанным порядком файлов: тест падал из-за соседа, а не из-за кода.
    from guardian.services import profile_analyzer

    settings = get_guardian_settings().model_copy(
        update={"premium_trust_enabled": True, "premium_trust_bonus": 2},
    )
    monkeypatch.setattr(profile_analyzer, "get_guardian_settings", lambda: settings)
    return settings


async def test_premium_ignored_when_disabled():
    """Главная защита фичи: выключено — значит не влияет вообще.

    Смягчение ослабляет капчу, поэтому «по умолчанию выключено» — это не
    вкусовая настройка, а требование. Если этот тест позеленеет при
    сломанном флаге, все остальные тесты Premium станут бессмысленны.
    """
    bot = _bot(total_count=0, bio="crypto инвестиции")
    score = await compute_profile_score(
        bot, user_id=8_000_000_000, username=None, is_premium=True,
    )
    assert score == 5  # ровно столько же, сколько без Premium


async def test_premium_softens_score(_premium_on):
    bot = _bot(total_count=0, bio="crypto инвестиции")
    score = await compute_profile_score(
        bot, user_id=8_000_000_000, username=None, is_premium=True,
    )
    assert score == 3  # 5 - 2


async def test_premium_never_goes_below_zero(_premium_on):
    """Чистый Premium-профиль даёт 0, а не -2.

    Отрицательный запас означал бы, что участник может «внести» его в
    будущие проверки и фактически обойти капчу — то есть смягчение
    превратилось бы в пропуск, чего F52 делать не должна.
    """
    bot = _bot(total_count=1, bio="просто человек")
    score = await compute_profile_score(
        bot, user_id=100, username="realuser", is_premium=True,
    )
    assert score == 0


async def test_premium_does_not_fully_cancel_strong_signals(_premium_on):
    """Смягчение гасит один сильный сигнал, но не все сразу.

    Профиль без username, без фото, новый и с рекламной био остаётся выше
    порога подозрительности (3) даже с Premium — иначе спамеру достаточно
    было бы купить подписку.
    """
    bot = _bot(total_count=0, bio="заработок от 1000$")
    score = await compute_profile_score(
        bot, user_id=8_000_000_000, username=None, is_premium=True,
    )
    assert score >= get_guardian_settings().profile_suspicion_threshold


async def test_non_premium_unaffected_when_enabled(_premium_on):
    bot = _bot(total_count=0)
    score = await compute_profile_score(
        bot, user_id=100, username="user", is_premium=False,
    )
    assert score == 1
