"""Тесты анализа профиля нового участника (G15)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.exceptions import TelegramBadRequest

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
