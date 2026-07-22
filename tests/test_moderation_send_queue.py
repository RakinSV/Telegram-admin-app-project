"""Очередь отправки на модерацию: устойчивость к посту, который Telegram
отвергает стабильно.

Найдено вживую (88.112): пачка берётся ограниченной и от старых к новым, и
десяток постов с неподъёмной подписью занимал её целиком — на модерацию не
приходило НИЧЕГО, включая свежие RSS-записи. Бот при этом исправно работал,
поэтому со стороны выглядело как «RSS не работает».
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tg_repost.db.models import Post, PostKind, PostStatus
from tg_repost.db.session import session_scope
from tg_repost.telegram import moderation_bot


@pytest.fixture(autouse=True)
def _clean():
    def _wipe() -> None:
        moderation_bot._send_failures.clear()
        with session_scope() as s:
            s.query(Post).delete()

    _wipe()
    yield
    _wipe()


def _make_post(text: str = "текст") -> int:
    with session_scope() as session:
        post = Post(
            kind=PostKind.SOURCE, original_text=text, rewritten_text=text,
            status=PostStatus.REWRITTEN, content_hash=text,
        )
        session.add(post)
        session.flush()
        return post.id


def _status(post_id: int) -> PostStatus:
    with session_scope() as session:
        return session.get(Post, post_id).status


def _app(send_effect=None) -> SimpleNamespace:
    bot = AsyncMock()
    if send_effect is not None:
        bot.send_message.side_effect = send_effect
    else:
        bot.send_message.return_value = SimpleNamespace(message_id=777)
    return SimpleNamespace(bot=bot)


async def test_successful_send_moves_post_to_pending_approval():
    post_id = _make_post()
    await moderation_bot.send_pending_for_approval(_app())
    assert _status(post_id) == PostStatus.PENDING_APPROVAL


async def test_post_telegram_keeps_rejecting_is_failed_not_retried_forever():
    """Иначе он вечно занимает место в пачке и загораживает очередь."""
    post_id = _make_post()
    app = _app(send_effect=RuntimeError("Message caption is too long"))

    for _ in range(moderation_bot._MAX_SEND_ATTEMPTS - 1):
        await moderation_bot.send_pending_for_approval(app)
        assert _status(post_id) == PostStatus.REWRITTEN, "рано сдаваться — сбой может быть разовым"

    await moderation_bot.send_pending_for_approval(app)
    assert _status(post_id) == PostStatus.FAILED

    with session_scope() as session:
        # Причина видна в админке, а не только в логах контейнера.
        assert "caption is too long" in (session.get(Post, post_id).status_reason or "")


async def test_temporary_failure_does_not_burn_the_attempt_budget():
    """Разовый таймаут не должен приближать пост к `failed`: счётчик обнуляется
    успехом, иначе редкие сетевые сбои со временем убили бы здоровый пост."""
    post_id = _make_post()
    calls = {"n": 0}

    async def _flaky(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("Timed out")
        return SimpleNamespace(message_id=1)

    app = _app(send_effect=_flaky)
    await moderation_bot.send_pending_for_approval(app)
    assert _status(post_id) == PostStatus.REWRITTEN
    await moderation_bot.send_pending_for_approval(app)
    assert _status(post_id) == PostStatus.PENDING_APPROVAL
    assert post_id not in moderation_bot._send_failures


async def test_broken_post_stops_blocking_the_ones_behind_it():
    """Главная проверка: свежий пост доезжает до модерации, несмотря на
    застрявший впереди него."""
    broken_id = _make_post("сломанный")
    good_id = _make_post("нормальный")

    async def _send(**kwargs):
        if "сломанный" in kwargs.get("text", ""):
            raise RuntimeError("Message caption is too long")
        return SimpleNamespace(message_id=1)

    app = _app(send_effect=_send)
    for _ in range(moderation_bot._MAX_SEND_ATTEMPTS):
        await moderation_bot.send_pending_for_approval(app)

    assert _status(broken_id) == PostStatus.FAILED
    assert _status(good_id) == PostStatus.PENDING_APPROVAL


async def test_manual_retry_gives_the_post_a_full_attempt_budget():
    """Найдено на аудите: счётчик неудачных отправок жил в памяти и НЕ
    сбрасывался ручным ретраем — пост, потративший часть попыток, уходил в
    failed с первой же неудачи после возврата в очередь."""
    post_id = _make_post()
    app = _app(send_effect=RuntimeError("Message caption is too long"))

    await moderation_bot.send_pending_for_approval(app)
    assert moderation_bot._send_failures.get(post_id) == 1

    moderation_bot.forget_send_failures(post_id)
    assert post_id not in moderation_bot._send_failures
