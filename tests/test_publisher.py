"""Тесты публикации (F08, F12) — чистые функции роутинга целей и поведение
`publish_post` при частичном/полном сбое (аудит ведения групп)."""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock

from telegram.error import RetryAfter, TimedOut

from tg_repost import post_targets_repo, sources_repo, targets_repo
from tg_repost.db.models import Post, PostKind, PostStatus, PostTarget, Source, TargetGroup
from tg_repost.db.session import session_scope
from tg_repost.telegram.publisher import (
    _retry_after_delay,
    publish_post,
    resolve_target_labels_for_post,
    resolve_targets_for_post,
)


def test_retry_after_delay_extracts_retry_after_seconds():
    exc = RetryAfter(retry_after=30)
    assert _retry_after_delay(exc) == 30


def test_retry_after_delay_returns_none_for_unrelated_exceptions():
    assert _retry_after_delay(TimedOut()) is None
    assert _retry_after_delay(ValueError("network error")) is None


def _clean() -> None:
    with session_scope() as session:
        session.query(PostTarget).delete()
        session.query(Post).delete()
        session.query(Source).delete()
        session.query(TargetGroup).delete()


def _make_post(**kwargs) -> Post:
    with session_scope() as session:
        post = Post(
            kind=PostKind.SOURCE, original_text="orig",
            status=PostStatus.APPROVED, **kwargs,
        )
        session.add(post)
        session.flush()
        pid = post.id
    with session_scope() as session:
        return session.get(Post, pid)


# --- resolve_targets_for_post ---

def test_resolve_targets_no_source_returns_all_active():
    _clean()
    targets_repo.add_target(-100111, "A")
    targets_repo.add_target(-100222, "B")
    post = _make_post()
    assert sorted(resolve_targets_for_post(post.id)) == [-100222, -100111]
    _clean()


def test_resolve_targets_inactive_group_excluded_from_all():
    _clean()
    active, _ = targets_repo.add_target(-100111, "A")
    inactive, _ = targets_repo.add_target(-100222, "B")
    targets_repo.toggle_target(inactive.id)
    post = _make_post()
    assert resolve_targets_for_post(post.id) == [-100111]
    _clean()


def test_resolve_targets_honors_source_override():
    _clean()
    targets_repo.add_target(-100111, "A")
    targets_repo.add_target(-100222, "B")
    source, _ = sources_repo.add_source("@chan1")
    sources_repo.set_source_targets(source.id, str(-100111))
    post = _make_post(source_id=source.id)
    assert resolve_targets_for_post(post.id) == [-100111]
    _clean()


def test_resolve_targets_override_all_inactive_returns_empty_not_fallback():
    """Регресс-тест на находку аудита ведения групп: раньше при полностью
    неактивном override публикация тихо уходила ВО ВСЕ группы — теперь
    возвращается пустой список (публикация отменяется), а не фолбэк."""
    _clean()
    target, _ = targets_repo.add_target(-100111, "A")
    targets_repo.add_target(-100222, "B")
    targets_repo.toggle_target(target.id)  # -100111 стал неактивен
    source, _ = sources_repo.add_source("@chan2")
    sources_repo.set_source_targets(source.id, str(-100111))
    post = _make_post(source_id=source.id)
    assert resolve_targets_for_post(post.id) == []
    _clean()


# --- resolve_target_labels_for_post ---

def test_resolve_target_labels_uses_titles_falls_back_to_chat_id():
    _clean()
    targets_repo.add_target(-100111, "Моя группа")
    targets_repo.add_target(-100222, None)
    post = _make_post()
    labels = resolve_target_labels_for_post(post.id)
    assert "Моя группа" in labels
    assert "-100222" in labels
    _clean()


def test_resolve_target_labels_empty_when_nowhere_to_post():
    _clean()
    post = _make_post()
    assert resolve_target_labels_for_post(post.id) == []
    _clean()


# --- publish_post ---

def _fake_bot(*, fail_chat_ids: frozenset[int] = frozenset()) -> AsyncMock:
    bot = AsyncMock()

    async def _send_message(chat_id, text, **kwargs):  # noqa: ARG001
        if chat_id in fail_chat_ids:
            raise TimedOut()
        msg = AsyncMock()
        msg.message_id = 1000
        return msg

    bot.send_message = AsyncMock(side_effect=_send_message)
    return bot


async def test_publish_post_partial_failure_marks_posted_not_failed(monkeypatch):
    """Регресс-тест: раньше сбой в ОДНОЙ из нескольких целей валил ВЕСЬ пост
    в FAILED, даже если он уже успел уйти в другую — при последующем ретрае
    (FAILED -> REWRITING -> ... -> POSTED) это отправило бы дубль в группу,
    которая уже всё получила."""
    monkeypatch.setattr("tg_repost.retry.asyncio.sleep", AsyncMock())
    _clean()
    targets_repo.add_target(-100111, "OK")
    targets_repo.add_target(-100222, "Broken")
    post = _make_post()
    bot = _fake_bot(fail_chat_ids=frozenset({-100222}))

    await publish_post(bot, post.id)

    with session_scope() as session:
        updated = session.get(Post, post.id)
        assert updated.status == PostStatus.POSTED
        assert updated.posted_chat_id == -100111
        assert updated.posted_message_id == 1000
        assert "-100222" in (updated.status_reason or "")
    _clean()


async def test_publish_post_all_targets_fail_marks_failed(monkeypatch):
    monkeypatch.setattr("tg_repost.retry.asyncio.sleep", AsyncMock())
    _clean()
    targets_repo.add_target(-100111, "Broken")
    post = _make_post()
    bot = _fake_bot(fail_chat_ids=frozenset({-100111}))

    await publish_post(bot, post.id)

    with session_scope() as session:
        updated = session.get(Post, post.id)
        assert updated.status == PostStatus.FAILED
        assert updated.posted_message_id is None
    _clean()


async def test_publish_post_no_active_targets_marks_failed():
    _clean()
    post = _make_post()
    bot = _fake_bot()

    await publish_post(bot, post.id)

    with session_scope() as session:
        updated = session.get(Post, post.id)
        assert updated.status == PostStatus.FAILED
        assert updated.status_reason == "нет активных целевых групп"
    _clean()


async def test_publish_post_override_all_inactive_marks_failed_with_specific_reason():
    _clean()
    target, _ = targets_repo.add_target(-100111, "A")
    targets_repo.toggle_target(target.id)
    source, _ = sources_repo.add_source("@chan3")
    sources_repo.set_source_targets(source.id, str(-100111))
    post = _make_post(source_id=source.id)
    bot = _fake_bot()

    await publish_post(bot, post.id)

    with session_scope() as session:
        updated = session.get(Post, post.id)
        assert updated.status == PostStatus.FAILED
        assert updated.status_reason == "персональные цели источника заданы, но все неактивны"
    _clean()


async def test_publish_post_all_success_marks_posted_without_partial_reason(monkeypatch):
    monkeypatch.setattr("tg_repost.retry.asyncio.sleep", AsyncMock())
    _clean()
    targets_repo.add_target(-100111, "A")
    targets_repo.add_target(-100222, "B")
    post = _make_post()
    bot = _fake_bot()

    await publish_post(bot, post.id)

    with session_scope() as session:
        updated = session.get(Post, post.id)
        assert updated.status == PostStatus.POSTED
        assert updated.status_reason is None
    _clean()


async def test_publish_post_retry_after_full_failure_clears_stale_reason(monkeypatch):
    """Регресс-тест (повторное ревью): пост, ранее упавший целиком (FAILED
    с reason), ретраится и на этот раз уходит во ВСЕ группы успешно —
    старый reason не должен остаться висеть на уже опубликованном посте."""
    monkeypatch.setattr("tg_repost.retry.asyncio.sleep", AsyncMock())
    _clean()
    targets_repo.add_target(-100111, "A")
    with session_scope() as session:
        stuck = Post(
            kind=PostKind.SOURCE, original_text="orig",
            status=PostStatus.FAILED, status_reason="публикация не удалась ни в одну группу",
        )
        session.add(stuck)
        session.flush()
        post_id = stuck.id
    with session_scope() as session:
        stuck = session.get(Post, post_id)
        stuck.set_status(PostStatus.APPROVED)  # имитация ретрая через approve_post
    bot = _fake_bot()

    await publish_post(bot, post_id)

    with session_scope() as session:
        updated = session.get(Post, post_id)
        assert updated.status == PostStatus.POSTED
        assert updated.status_reason is None
    _clean()


async def test_publish_post_sends_to_multiple_targets_concurrently():
    """Регресс-тест (доп. фича по итогам ревью): цели публикуются
    ПАРАЛЛЕЛЬНО, а не по очереди — одна медленная группа не должна
    задерживать доставку в остальные. Три "медленные" цели с задержкой
    0.2с каждая: последовательно заняло бы >=0.6с, параллельно — ~0.2с."""
    _clean()
    targets_repo.add_target(-100111, "A")
    targets_repo.add_target(-100222, "B")
    targets_repo.add_target(-100333, "C")
    post = _make_post()

    bot = AsyncMock()

    async def _slow_send(chat_id, text, **kwargs):  # noqa: ARG001
        await asyncio.sleep(0.2)
        msg = AsyncMock()
        msg.message_id = 1000
        return msg

    bot.send_message = AsyncMock(side_effect=_slow_send)

    start = time.monotonic()
    await publish_post(bot, post.id)
    elapsed = time.monotonic() - start

    assert elapsed < 0.5  # с запасом; последовательно было бы >= 0.6с
    with session_scope() as session:
        updated = session.get(Post, post.id)
        assert updated.status == PostStatus.POSTED
    _clean()


# --- F29: post_targets записываются на каждую публикацию ---

async def test_publish_post_records_post_target_for_each_success(monkeypatch):
    monkeypatch.setattr("tg_repost.retry.asyncio.sleep", AsyncMock())
    _clean()
    targets_repo.add_target(-100111, "A")
    targets_repo.add_target(-100222, "B")
    post = _make_post()
    bot = _fake_bot()

    await publish_post(bot, post.id)

    rows = post_targets_repo.list_targets_for_post(post.id)
    assert {(r.chat_id, r.message_id, r.ok) for r in rows} == {
        (-100111, 1000, True), (-100222, 1000, True),
    }
    _clean()


async def test_publish_post_records_post_target_for_failure_too(monkeypatch):
    monkeypatch.setattr("tg_repost.retry.asyncio.sleep", AsyncMock())
    _clean()
    targets_repo.add_target(-100111, "OK")
    targets_repo.add_target(-100222, "Broken")
    post = _make_post()
    bot = _fake_bot(fail_chat_ids=frozenset({-100222}))

    await publish_post(bot, post.id)

    rows = {r.chat_id: r for r in post_targets_repo.list_targets_for_post(post.id)}
    assert rows[-100111].ok is True
    assert rows[-100111].message_id == 1000
    assert rows[-100222].ok is False
    assert rows[-100222].message_id is None
    assert rows[-100222].error
    _clean()


# --- F33: опросы публикуются через bot.send_poll ---


def _make_poll_post(**kwargs) -> Post:
    with session_scope() as session:
        post = Post(
            kind=PostKind.POLL, original_text="orig", status=PostStatus.APPROVED, **kwargs,
        )
        session.add(post)
        session.flush()
        pid = post.id
    with session_scope() as session:
        return session.get(Post, pid)


async def test_publish_post_poll_calls_send_poll_not_send_message(monkeypatch):
    monkeypatch.setattr("tg_repost.retry.asyncio.sleep", AsyncMock())
    _clean()
    targets_repo.add_target(-100111, "A")
    post = _make_poll_post(
        rewritten_text="Любимый цвет?",
        poll_options=json.dumps(["Красный", "Синий"]),
        poll_is_anonymous=False,
        poll_allows_multiple_answers=True,
    )

    bot = AsyncMock()
    poll_msg = AsyncMock()
    poll_msg.message_id = 2000
    bot.send_poll = AsyncMock(return_value=poll_msg)

    await publish_post(bot, post.id)

    bot.send_poll.assert_awaited_once_with(
        chat_id=-100111, question="Любимый цвет?", options=["Красный", "Синий"],
        is_anonymous=False, allows_multiple_answers=True,
    )
    bot.send_message.assert_not_awaited()
    with session_scope() as session:
        updated = session.get(Post, post.id)
        assert updated.status == PostStatus.POSTED
        assert updated.posted_message_id == 2000
    _clean()


async def test_publish_post_poll_ignores_media_path(monkeypatch):
    """Защита в глубину (см. publisher.py docstring): если у POLL-поста
    каким-то образом задан media_path, публикация всё равно идёт через
    send_poll, не send_photo."""
    monkeypatch.setattr("tg_repost.retry.asyncio.sleep", AsyncMock())
    _clean()
    targets_repo.add_target(-100111, "A")
    post = _make_poll_post(
        rewritten_text="Q?",
        poll_options=json.dumps(["a", "b"]),
        media_path="/tmp/should-be-ignored.jpg",
    )

    bot = AsyncMock()
    poll_msg = AsyncMock()
    poll_msg.message_id = 2001
    bot.send_poll = AsyncMock(return_value=poll_msg)

    await publish_post(bot, post.id)

    bot.send_poll.assert_awaited_once()
    bot.send_photo.assert_not_awaited()
    _clean()


# --- F34: inline-кнопка "источник" на опубликованном посте ---


async def test_publish_post_adds_source_button_when_enabled_and_link_present(monkeypatch):
    from tg_repost.webui import settings_store

    monkeypatch.setattr("tg_repost.retry.asyncio.sleep", AsyncMock())
    _clean()
    settings_store.save_setting("post_source_button_enabled", True, "bool")
    settings_store.save_setting("post_source_button_label", "Читать полностью", "str")
    try:
        targets_repo.add_target(-100111, "A")
        post = _make_post(source_link="https://example.com/orig")
        bot = _fake_bot()

        await publish_post(bot, post.id)

        kwargs = bot.send_message.call_args.kwargs
        markup = kwargs["reply_markup"]
        assert markup.inline_keyboard[0][0].text == "Читать полностью"
        assert markup.inline_keyboard[0][0].url == "https://example.com/orig"
    finally:
        with session_scope() as session:
            from tg_repost.db.models import AppSetting
            session.query(AppSetting).delete()
        from tg_repost.config import invalidate_settings_cache
        invalidate_settings_cache()
    _clean()


async def test_publish_post_no_button_when_disabled(monkeypatch):
    monkeypatch.setattr("tg_repost.retry.asyncio.sleep", AsyncMock())
    _clean()
    targets_repo.add_target(-100111, "A")
    post = _make_post(source_link="https://example.com/orig")
    bot = _fake_bot()

    await publish_post(bot, post.id)

    assert bot.send_message.call_args.kwargs["reply_markup"] is None
    _clean()


# --- Аудит: публикация с media_path (send_photo) — ранее нулевое покрытие ---


def _make_media_post(tmp_path, text: str, **kwargs) -> Post:
    image_path = tmp_path / "cover.jpg"
    image_path.write_bytes(b"fake-jpeg-bytes")
    with session_scope() as session:
        post = Post(
            kind=PostKind.SOURCE, original_text=text, rewritten_text=text,
            status=PostStatus.APPROVED, media_path=str(image_path), **kwargs,
        )
        session.add(post)
        session.flush()
        pid = post.id
    with session_scope() as session:
        return session.get(Post, pid)


async def test_publish_post_with_media_sends_photo_with_caption(monkeypatch, tmp_path):
    monkeypatch.setattr("tg_repost.retry.asyncio.sleep", AsyncMock())
    _clean()
    targets_repo.add_target(-100111, "A")
    post = _make_media_post(tmp_path, "короткая подпись")

    bot = AsyncMock()
    photo_msg = AsyncMock()
    photo_msg.message_id = 3000
    bot.send_photo = AsyncMock(return_value=photo_msg)

    await publish_post(bot, post.id)

    bot.send_photo.assert_awaited_once()
    kwargs = bot.send_photo.call_args.kwargs
    assert kwargs["chat_id"] == -100111
    assert kwargs["caption"] == "короткая подпись"
    assert kwargs["photo"] == b"fake-jpeg-bytes"
    bot.send_message.assert_not_awaited()  # текст короче лимита подписи — хвоста нет
    with session_scope() as session:
        updated = session.get(Post, post.id)
        assert updated.status == PostStatus.POSTED
        assert updated.posted_message_id == 3000
    _clean()


async def test_publish_post_with_media_long_text_sends_tail_message(monkeypatch, tmp_path):
    """Текст длиннее лимита подписи (1024 симв.) — подпись обрезается,
    остаток досылается ОТДЕЛЬНЫМ сообщением (см. publisher.py::_send_one)."""
    monkeypatch.setattr("tg_repost.retry.asyncio.sleep", AsyncMock())
    _clean()
    targets_repo.add_target(-100111, "A")
    long_text = "а" * 1500
    post = _make_media_post(tmp_path, long_text)

    bot = AsyncMock()
    photo_msg = AsyncMock()
    photo_msg.message_id = 3001
    bot.send_photo = AsyncMock(return_value=photo_msg)
    tail_msg = AsyncMock()
    tail_msg.message_id = 3002
    bot.send_message = AsyncMock(return_value=tail_msg)

    await publish_post(bot, post.id)

    caption = bot.send_photo.call_args.kwargs["caption"]
    assert len(caption) == 1024
    assert caption == long_text[:1024]
    bot.send_message.assert_awaited_once()
    tail_kwargs = bot.send_message.call_args.kwargs
    assert tail_kwargs["chat_id"] == -100111
    assert tail_kwargs["text"] == long_text[1024:]
    # message_id первого успешного результата — от send_photo, не от хвоста.
    with session_scope() as session:
        updated = session.get(Post, post.id)
        assert updated.posted_message_id == 3001
    _clean()


async def test_publish_post_with_media_applies_source_button_to_photo(monkeypatch, tmp_path):
    from tg_repost.webui import settings_store

    monkeypatch.setattr("tg_repost.retry.asyncio.sleep", AsyncMock())
    _clean()
    settings_store.save_setting("post_source_button_enabled", True, "bool")
    settings_store.save_setting("post_source_button_label", "Читать полностью", "str")
    try:
        targets_repo.add_target(-100111, "A")
        post = _make_media_post(tmp_path, "текст", source_link="https://example.com/orig")

        bot = AsyncMock()
        photo_msg = AsyncMock()
        photo_msg.message_id = 3003
        bot.send_photo = AsyncMock(return_value=photo_msg)

        await publish_post(bot, post.id)

        markup = bot.send_photo.call_args.kwargs["reply_markup"]
        assert markup.inline_keyboard[0][0].text == "Читать полностью"
        assert markup.inline_keyboard[0][0].url == "https://example.com/orig"
    finally:
        with session_scope() as session:
            from tg_repost.db.models import AppSetting
            session.query(AppSetting).delete()
        from tg_repost.config import invalidate_settings_cache
        invalidate_settings_cache()
    _clean()


async def test_publish_post_no_button_when_no_source_link(monkeypatch):
    from tg_repost.webui import settings_store

    monkeypatch.setattr("tg_repost.retry.asyncio.sleep", AsyncMock())
    _clean()
    settings_store.save_setting("post_source_button_enabled", True, "bool")
    try:
        targets_repo.add_target(-100111, "A")
        post = _make_post()  # без source_link
        bot = _fake_bot()

        await publish_post(bot, post.id)

        assert bot.send_message.call_args.kwargs["reply_markup"] is None
    finally:
        with session_scope() as session:
            from tg_repost.db.models import AppSetting
            session.query(AppSetting).delete()
        from tg_repost.config import invalidate_settings_cache
        invalidate_settings_cache()
    _clean()
