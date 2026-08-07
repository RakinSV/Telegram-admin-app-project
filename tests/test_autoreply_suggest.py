"""Автоответчик (F45), онбординг (F46) и предложка (F47).

Ключевое, что защищаем:
* автоответчик срабатывает по СЛОВУ, а не по подстроке, и не превращается в
  болтуна (пауза + игнор ботов);
* предложка попадает в ТУ ЖЕ очередь модерации, что и обычные посты — новый
  здесь только источник поступления.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from engage.handlers import suggest
from guardian import settings_store
from guardian.config import invalidate_settings_cache
from guardian.handlers import autoreply
from tg_repost.db.models import Post, PostStatus
from tg_repost.db.session import session_scope

CHAT = -100222
RULES_JSON = (
    '[{"triggers": ["правила", "rules"], "reply": "Правила в закрепе"},'
    ' {"triggers": ["стрим"], "reply": "Стрим по пятницам"}]'
)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for key in ("AUTOREPLY_ENABLED", "AUTOREPLY_RULES", "AUTOREPLY_COOLDOWN_SECONDS"):
        monkeypatch.delenv(key, raising=False)
    autoreply._last_reply.clear()
    settings_store.sync_protected_chat_ids([CHAT])
    invalidate_settings_cache()
    with session_scope() as session:
        session.query(Post).delete()
    yield
    autoreply._last_reply.clear()
    settings_store.sync_protected_chat_ids([])
    invalidate_settings_cache()
    with session_scope() as session:
        session.query(Post).delete()


def _msg(text: str, *, chat_id: int = CHAT, is_bot: bool = False):
    return SimpleNamespace(
        chat=SimpleNamespace(id=chat_id),
        from_user=SimpleNamespace(id=7, is_bot=is_bot, username="u", full_name="U"),
        text=text, caption=None, reply=AsyncMock(),
    )


# --- разбор правил ---


def test_parse_rules_valid():
    rules = autoreply.parse_rules(RULES_JSON)
    assert len(rules) == 2
    assert rules[0].reply == "Правила в закрепе"


def test_parse_rules_broken_json_is_not_fatal():
    """Кривой JSON — автоответчик молчит, а не роняет бота."""
    assert autoreply.parse_rules("{не json") == []


def test_parse_rules_skips_incomplete_entries():
    assert autoreply.parse_rules('[{"triggers": []}, {"reply": "без триггеров"}]') == []


def test_parse_rules_empty_setting():
    assert autoreply.parse_rules("   ") == []


# --- сопоставление ---


def test_match_by_whole_word():
    rules = autoreply.parse_rules(RULES_JSON)
    assert autoreply.find_match("а где правила?", rules) is not None


def test_no_match_on_substring():
    """«стрим» не должен стрелять на «экстримальный» — это и есть разница
    между полезным автоответчиком и раздражающим."""
    rules = autoreply.parse_rules(RULES_JSON)
    assert autoreply.find_match("это экстримальный спорт", rules) is None


def test_match_is_case_insensitive():
    rules = autoreply.parse_rules(RULES_JSON)
    assert autoreply.find_match("ПРАВИЛА где?", rules) is not None


def test_no_match_returns_none():
    rules = autoreply.parse_rules(RULES_JSON)
    assert autoreply.find_match("привет всем", rules) is None


# --- поведение хендлера ---


async def test_replies_when_enabled(monkeypatch):
    monkeypatch.setenv("AUTOREPLY_ENABLED", "true")
    monkeypatch.setenv("AUTOREPLY_RULES", RULES_JSON)
    invalidate_settings_cache()
    message = _msg("где правила?")
    await autoreply.on_message(message, AsyncMock())
    message.reply.assert_awaited_once()


async def test_silent_when_disabled():
    message = _msg("где правила?")
    await autoreply.on_message(message, AsyncMock())
    message.reply.assert_not_awaited()


async def test_cooldown_prevents_spam(monkeypatch):
    """Десять человек подряд спросят одно и то же — бот ответит один раз."""
    monkeypatch.setenv("AUTOREPLY_ENABLED", "true")
    monkeypatch.setenv("AUTOREPLY_RULES", RULES_JSON)
    monkeypatch.setenv("AUTOREPLY_COOLDOWN_SECONDS", "600")
    invalidate_settings_cache()

    first, second = _msg("где правила?"), _msg("а правила где?")
    await autoreply.on_message(first, AsyncMock())
    await autoreply.on_message(second, AsyncMock())
    first.reply.assert_awaited_once()
    second.reply.assert_not_awaited()


async def test_replies_right_after_machine_boot(monkeypatch):
    """Первый ответ не должен зависеть от аптайма машины.

    `time.monotonic()` считается от старта системы, поэтому сразу после
    загрузки он сам по себе меньше кулдауна. Пока «ещё не отвечали»
    кодировалось нулём, проверка `monotonic() - 0 < cooldown` была истиной и
    бот молчал первые 10 минут после каждого рестарта. На машине с большим
    аптаймом этого не видно — баг поймал CI на свежем раннере.
    """
    monkeypatch.setenv("AUTOREPLY_ENABLED", "true")
    monkeypatch.setenv("AUTOREPLY_RULES", RULES_JSON)
    monkeypatch.setenv("AUTOREPLY_COOLDOWN_SECONDS", "600")
    invalidate_settings_cache()
    # Машина поднялась 30 секунд назад — меньше кулдауна в 600 секунд.
    monkeypatch.setattr(autoreply.time, "monotonic", lambda: 30.0)

    message = _msg("где правила?")
    await autoreply.on_message(message, AsyncMock())
    message.reply.assert_awaited_once()


async def test_ignores_other_bots(monkeypatch):
    """Иначе два бота устроят бесконечный обмен репликами."""
    monkeypatch.setenv("AUTOREPLY_ENABLED", "true")
    monkeypatch.setenv("AUTOREPLY_RULES", RULES_JSON)
    invalidate_settings_cache()
    message = _msg("где правила?", is_bot=True)
    await autoreply.on_message(message, AsyncMock())
    message.reply.assert_not_awaited()


async def test_ignores_unprotected_chat(monkeypatch):
    monkeypatch.setenv("AUTOREPLY_ENABLED", "true")
    monkeypatch.setenv("AUTOREPLY_RULES", RULES_JSON)
    invalidate_settings_cache()
    message = _msg("где правила?", chat_id=-100999)
    await autoreply.on_message(message, AsyncMock())
    message.reply.assert_not_awaited()


# --- предложка (F47) ---


def test_suggestion_lands_in_moderation_queue():
    """Новый только источник поступления: дальше пост идёт обычным путём."""
    text = "Интересная новость про безопасность, которую стоит опубликовать в канале."
    post_id = suggest.create_suggested_post(text, author_id=42, author_name="@someone")
    assert post_id is not None
    with session_scope() as session:
        post = session.get(Post, post_id)
        assert post is not None
        assert post.status == PostStatus.REWRITTEN  # готов к модерации
        assert post.rewritten_text == text
        # Автор виден владельцу: публиковать чужой текст вслепую — плохая идея.
        assert "@someone" in (post.status_reason or "")


def test_short_suggestion_rejected():
    assert suggest.create_suggested_post("норм", 42, "@u") is None


def test_long_suggestion_is_clipped():
    post_id = suggest.create_suggested_post("Я" * 5000, 42, "@u")
    assert post_id is not None
    with session_scope() as session:
        post = session.get(Post, post_id)
        assert post is not None
        assert len(post.rewritten_text or "") == suggest.MAX_SUGGESTION_LEN


async def test_onboarding_failure_is_not_fatal():
    """Telegram не даёт писать первым — отказ это ожидаемый случай, не сбой."""
    bot = AsyncMock()
    bot.send_message.side_effect = RuntimeError("bot can't initiate conversation")
    assert await suggest.send_onboarding(bot, 42) is False


async def test_onboarding_sends_text():
    bot = AsyncMock()
    assert await suggest.send_onboarding(bot, 42) is True
    assert "/invite" in bot.send_message.await_args.args[1]
