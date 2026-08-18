"""«Редакционная кухня» (F50): трансляция хода редакции в чат.

Два уровня: чистый callback в `rewriter/editorial.py` (какие шаги и в каком
порядке отдаются) и Telegram-сторона в `telegram/newsroom.py` (режимы
многословности, цепочка реплаев, устойчивость к сбою отправки).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from tg_repost.config import invalidate_settings_cache
from tg_repost.rewriter import editorial
from tg_repost.rewriter.client import RewriteResult
from tg_repost.telegram import newsroom


@pytest.fixture(autouse=True)
def _clean_settings(monkeypatch):
    for key in (
        "EDITORIAL_MAX_ROUNDS", "EDITORIAL_WEB_VERIFY_ENABLED",
        "EDITORIAL_NEWSROOM_ENABLED", "EDITORIAL_NEWSROOM_CHAT_ID",
        "EDITORIAL_NEWSROOM_VERBOSITY",
    ):
        monkeypatch.delenv(key, raising=False)
    invalidate_settings_cache()
    yield
    invalidate_settings_cache()


def _result(text: str, tokens: int = 10) -> RewriteResult:
    return RewriteResult(text=text, prompt_tokens=tokens, completion_tokens=tokens)


def _client_with_revision() -> AsyncMock:
    """Клиент, у которого редактор придирается и журналист правит."""
    client = AsyncMock()
    client.rewrite = AsyncMock(return_value=_result("черновик"))
    client.rewrite_with_prompt = AsyncMock(side_effect=[
        _result("ВЕРДИКТ: ПРАВИТЬ\n1. выдумана цифра"),
        _result("исправленный текст"),
    ])
    return client


# --- уровень editorial.py: какие шаги отдаются ---


async def test_steps_emitted_in_order_when_editor_asks_changes(monkeypatch):
    monkeypatch.setenv("EDITORIAL_MAX_ROUNDS", "1")
    monkeypatch.setenv("EDITORIAL_WEB_VERIFY_ENABLED", "false")
    invalidate_settings_cache()
    seen: list[tuple[str, str]] = []

    async def on_step(stage: str, text: str) -> None:
        seen.append((stage, text))

    await editorial.editorial_rewrite(
        _client_with_revision(), original="источник", link_content="",
        prompt_name="default", language=None, on_step=on_step,
    )
    assert [s for s, _ in seen] == [
        editorial.STEP_DRAFT, editorial.STEP_REVIEW,
        editorial.STEP_REVISION, editorial.STEP_VERDICT,
    ]
    assert seen[0][1] == "черновик"
    assert "выдумана цифра" in seen[1][1]
    assert seen[2][1] == "исправленный текст"


async def test_approved_emits_draft_and_verdict_only(monkeypatch):
    monkeypatch.setenv("EDITORIAL_MAX_ROUNDS", "1")
    invalidate_settings_cache()
    client = AsyncMock()
    client.rewrite = AsyncMock(return_value=_result("черновик"))
    client.rewrite_with_prompt = AsyncMock(return_value=_result("ВЕРДИКТ: OK"))
    seen: list[str] = []

    async def on_step(stage: str, text: str) -> None:
        del text
        seen.append(stage)

    await editorial.editorial_rewrite(
        client, original="источник", link_content="", prompt_name="default",
        language=None, on_step=on_step,
    )
    assert seen == [editorial.STEP_DRAFT, editorial.STEP_VERDICT]


async def test_callback_failure_never_breaks_rewrite(monkeypatch):
    """Трансляция — диагностика, а не пайплайн: упавший Telegram не должен
    стоить поста."""
    monkeypatch.setenv("EDITORIAL_MAX_ROUNDS", "1")
    monkeypatch.setenv("EDITORIAL_WEB_VERIFY_ENABLED", "false")
    invalidate_settings_cache()

    async def broken(stage: str, text: str) -> None:
        del stage, text
        raise RuntimeError("Telegram недоступен")

    res = await editorial.editorial_rewrite(
        _client_with_revision(), original="источник", link_content="",
        prompt_name="default", language=None, on_step=broken,
    )
    assert res.text == "исправленный текст"
    assert res.rounds_used == 1


# --- уровень newsroom.py: режимы и отправка ---


_FIRST_MESSAGE_ID = 500


def _fake_bot() -> MagicMock:
    """Бот, выдающий предсказуемые message_id начиная с _FIRST_MESSAGE_ID."""
    bot = MagicMock()
    counter = iter(range(_FIRST_MESSAGE_ID, _FIRST_MESSAGE_ID + 100))

    async def _send(**kwargs: object) -> MagicMock:
        del kwargs
        return MagicMock(message_id=next(counter))

    bot.send_message = AsyncMock(side_effect=_send)
    return bot


def test_callback_is_none_when_disabled():
    assert newsroom.build_newsroom_callback(_fake_bot(), 1) is None


def test_callback_is_none_without_chat_id(monkeypatch):
    monkeypatch.setenv("EDITORIAL_NEWSROOM_ENABLED", "true")
    invalidate_settings_cache()
    assert newsroom.build_newsroom_callback(_fake_bot(), 1) is None


async def test_verbosity_all_sends_every_stage(monkeypatch):
    monkeypatch.setenv("EDITORIAL_NEWSROOM_ENABLED", "true")
    monkeypatch.setenv("EDITORIAL_NEWSROOM_CHAT_ID", "-100500")
    monkeypatch.setenv("EDITORIAL_NEWSROOM_VERBOSITY", "all")
    invalidate_settings_cache()
    bot = _fake_bot()
    cb = newsroom.build_newsroom_callback(bot, 42)
    assert cb is not None

    await cb(editorial.STEP_DRAFT, "черновик")
    await cb(editorial.STEP_REVIEW, "замечания")
    await cb(editorial.STEP_VERDICT, "готово")
    assert bot.send_message.await_count == 3
    first = bot.send_message.await_args_list[0].kwargs
    assert first["chat_id"] == -100500
    assert "пост #42" in first["text"]
    assert first["reply_to_message_id"] is None  # первое — корень цепочки
    # остальные реплаятся к корню, чтобы в чате была ветка обсуждения
    for call in bot.send_message.await_args_list[1:]:
        assert call.kwargs["reply_to_message_id"] == _FIRST_MESSAGE_ID


async def test_verbosity_problems_stays_silent_when_editor_approves(monkeypatch):
    monkeypatch.setenv("EDITORIAL_NEWSROOM_ENABLED", "true")
    monkeypatch.setenv("EDITORIAL_NEWSROOM_CHAT_ID", "-100500")
    monkeypatch.setenv("EDITORIAL_NEWSROOM_VERBOSITY", "problems")
    invalidate_settings_cache()
    bot = _fake_bot()
    cb = newsroom.build_newsroom_callback(bot, 7)
    assert cb is not None

    await cb(editorial.STEP_DRAFT, "черновик")
    await cb(editorial.STEP_VERDICT, "✓ Редактор одобрил без правок.")
    bot.send_message.assert_not_awaited()  # хорошему посту разбор не нужен


async def test_verbosity_problems_flushes_held_draft_on_review(monkeypatch):
    """Черновик придержан до рецензии: на его момент ещё неизвестно, будут ли
    замечания. Появились — показываем и черновик, и разбор."""
    monkeypatch.setenv("EDITORIAL_NEWSROOM_ENABLED", "true")
    monkeypatch.setenv("EDITORIAL_NEWSROOM_CHAT_ID", "-100500")
    monkeypatch.setenv("EDITORIAL_NEWSROOM_VERBOSITY", "problems")
    invalidate_settings_cache()
    bot = _fake_bot()
    cb = newsroom.build_newsroom_callback(bot, 7)
    assert cb is not None

    await cb(editorial.STEP_DRAFT, "черновик")
    bot.send_message.assert_not_awaited()
    await cb(editorial.STEP_REVIEW, "1. слабый лид")
    assert bot.send_message.await_count == 2  # придержанный черновик + рецензия
    texts = [c.kwargs["text"] for c in bot.send_message.await_args_list]
    assert "черновик" in texts[0]
    assert "слабый лид" in texts[1]


async def test_verbosity_summary_sends_only_verdict(monkeypatch):
    monkeypatch.setenv("EDITORIAL_NEWSROOM_ENABLED", "true")
    monkeypatch.setenv("EDITORIAL_NEWSROOM_CHAT_ID", "-100500")
    monkeypatch.setenv("EDITORIAL_NEWSROOM_VERBOSITY", "summary")
    invalidate_settings_cache()
    bot = _fake_bot()
    cb = newsroom.build_newsroom_callback(bot, 7)
    assert cb is not None

    await cb(editorial.STEP_DRAFT, "черновик")
    await cb(editorial.STEP_REVIEW, "замечания")
    await cb(editorial.STEP_VERDICT, "Готово: раундов правки 1")
    assert bot.send_message.await_count == 1
    assert "Готово" in bot.send_message.await_args_list[0].kwargs["text"]


async def test_unknown_verbosity_falls_back_to_problems(monkeypatch):
    monkeypatch.setenv("EDITORIAL_NEWSROOM_ENABLED", "true")
    monkeypatch.setenv("EDITORIAL_NEWSROOM_CHAT_ID", "-100500")
    monkeypatch.setenv("EDITORIAL_NEWSROOM_VERBOSITY", "опечатка")
    invalidate_settings_cache()
    bot = _fake_bot()
    cb = newsroom.build_newsroom_callback(bot, 7)
    assert cb is not None
    await cb(editorial.STEP_DRAFT, "черновик")
    bot.send_message.assert_not_awaited()  # ведёт себя как problems


async def test_send_failure_is_swallowed(monkeypatch):
    monkeypatch.setenv("EDITORIAL_NEWSROOM_ENABLED", "true")
    monkeypatch.setenv("EDITORIAL_NEWSROOM_CHAT_ID", "-100500")
    monkeypatch.setenv("EDITORIAL_NEWSROOM_VERBOSITY", "all")
    invalidate_settings_cache()
    bot = MagicMock()
    bot.send_message = AsyncMock(side_effect=RuntimeError("chat not found"))
    cb = newsroom.build_newsroom_callback(bot, 7)
    assert cb is not None
    await cb(editorial.STEP_DRAFT, "черновик")  # не должно бросить


async def test_long_text_is_clipped_under_telegram_limit(monkeypatch):
    monkeypatch.setenv("EDITORIAL_NEWSROOM_ENABLED", "true")
    monkeypatch.setenv("EDITORIAL_NEWSROOM_CHAT_ID", "-100500")
    monkeypatch.setenv("EDITORIAL_NEWSROOM_VERBOSITY", "all")
    invalidate_settings_cache()
    bot = _fake_bot()
    cb = newsroom.build_newsroom_callback(bot, 7)
    assert cb is not None

    await cb(editorial.STEP_DRAFT, "🔥" * 5000)  # эмодзи вне BMP = 2 единицы каждый
    from tg_repost.telegram.text_utils import tg_len

    sent = bot.send_message.await_args_list[0].kwargs["text"]
    assert tg_len(sent) <= newsroom._MESSAGE_LIMIT
    assert sent.endswith("…")
