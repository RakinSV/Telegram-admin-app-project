"""Тесты сводки статистики (F14): compute_stats_summary (Фаза 5.3 рефакторинг
text/data split, по образцу smart_schedule.py/growth.py) и авто-реакция на
негативные реакции (F25)."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tg_repost import post_targets_repo
from tg_repost.config import invalidate_settings_cache
from tg_repost.db.models import AppSetting, Post, PostKind, PostStat, PostStatus, PostTarget, Secret
from tg_repost.db.session import session_scope
from tg_repost.scheduler import stats as stats_module
from tg_repost.scheduler.stats import (
    _count_negative_reactions,
    _handle_negative_reactions,
    collect_stats,
    compute_stats_summary,
    stats_summary,
)
from tg_repost.webui import settings_store


def _clear_posts() -> None:
    with session_scope() as session:
        session.query(PostStat).delete()
        session.query(PostTarget).delete()
        session.query(Post).delete()


def test_compute_stats_summary_no_posts():
    _clear_posts()
    summary = compute_stats_summary(window_days=7)
    assert summary.published == 0
    assert summary.counted == 0
    assert summary.total_views == 0
    assert summary.avg_views == 0.0
    assert summary.top_post_id is None


def test_compute_stats_summary_aggregates_views_and_finds_top_post():
    _clear_posts()
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        low = Post(kind=PostKind.SOURCE, status=PostStatus.POSTED, posted_at=now)
        high = Post(kind=PostKind.SOURCE, status=PostStatus.POSTED, posted_at=now)
        session.add_all([low, high])
        session.flush()
        session.add(PostStat(post_id=low.id, view_count=10))
        session.add(PostStat(post_id=high.id, view_count=100))
        low_id, high_id = low.id, high.id

    summary = compute_stats_summary(window_days=7)
    assert summary.published == 2
    assert summary.counted == 2
    assert summary.total_views == 110
    assert summary.avg_views == 55.0
    assert summary.top_post_id == high_id
    assert summary.top_post_views == 100
    assert low_id != high_id  # обе записи реально различны


def test_compute_stats_summary_uses_latest_snapshot_per_post():
    _clear_posts()
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        post = Post(kind=PostKind.SOURCE, status=PostStatus.POSTED, posted_at=now)
        session.add(post)
        session.flush()
        session.add(PostStat(post_id=post.id, view_count=5, captured_at=now - timedelta(hours=2)))
        session.add(PostStat(post_id=post.id, view_count=50, captured_at=now))

    summary = compute_stats_summary(window_days=7)
    assert summary.counted == 1
    assert summary.total_views == 50


def test_compute_stats_summary_ignores_posts_outside_window():
    _clear_posts()
    old = datetime.now(timezone.utc) - timedelta(days=30)
    with session_scope() as session:
        post = Post(kind=PostKind.SOURCE, status=PostStatus.POSTED, posted_at=old)
        session.add(post)

    summary = compute_stats_summary(window_days=7)
    assert summary.published == 0


def test_stats_summary_text_no_posts():
    _clear_posts()
    text = stats_summary(window_days=7)
    assert "нет" in text


def test_stats_summary_text_includes_top_post():
    _clear_posts()
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        post = Post(kind=PostKind.SOURCE, status=PostStatus.POSTED, posted_at=now)
        session.add(post)
        session.flush()
        session.add(PostStat(post_id=post.id, view_count=42))
        post_id = post.id

    text = stats_summary(window_days=7)
    assert f"#{post_id}" in text
    assert "42" in text


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    """Изоляция для тестов F25 (пишут negative_reaction_threshold/
    auto_delete_on_negative в app_settings — общий sqlite-engine на весь
    pytest-процесс, см. tests/conftest.py)."""
    monkeypatch.chdir(tmp_path)
    with session_scope() as session:
        session.query(AppSetting).delete()
        session.query(Secret).delete()
    invalidate_settings_cache()
    stats_module._auto_delete_limiter = None
    yield
    with session_scope() as session:
        session.query(AppSetting).delete()
        session.query(Secret).delete()
    invalidate_settings_cache()
    stats_module._auto_delete_limiter = None


def _fake_message(reaction_counts: dict[str, int], views: int = 100, forwards: int = 5):
    """Подделка Telethon-сообщения с реакциями (F25) — структура, достаточная
    для `_count_reactions`/`_count_negative_reactions`: `.reactions.results[i]`
    с `.reaction.emoticon`/`.count`."""
    results = [
        SimpleNamespace(reaction=SimpleNamespace(emoticon=emoji), count=count)
        for emoji, count in reaction_counts.items()
    ]
    return SimpleNamespace(
        views=views, forwards=forwards,
        reactions=SimpleNamespace(results=results) if results else None,
    )


def test_count_negative_reactions_none():
    assert _count_negative_reactions(_fake_message({})) == 0


def test_count_negative_reactions_only_positive():
    assert _count_negative_reactions(_fake_message({"👍": 10, "❤": 5})) == 0


def test_count_negative_reactions_sums_negative_emoji():
    assert _count_negative_reactions(_fake_message({"👍": 10, "👎": 3, "💩": 2})) == 5


def test_count_negative_reactions_ignores_custom_emoji_without_emoticon():
    """`ReactionCustomEmoji` (кастомные эмодзи-реакции) не имеет `.emoticon` —
    не должен считаться негативным без явного сопоставления."""
    results = [SimpleNamespace(reaction=SimpleNamespace(), count=100)]
    msg = SimpleNamespace(reactions=SimpleNamespace(results=results))
    assert _count_negative_reactions(msg) == 0


def _make_posted_post(**kwargs) -> int:
    with session_scope() as session:
        post = Post(kind=PostKind.SOURCE, status=PostStatus.POSTED, **kwargs)
        session.add(post)
        session.flush()
        return post.id


def _make_posted_post_with_target(chat_id: int, message_id: int, **kwargs) -> int:
    """F31: `collect_stats` теперь читает цели из `post_targets` (F29), а не
    из `Post.posted_chat_id`/`posted_message_id` напрямую — тесты, гоняющие
    `collect_stats` целиком, должны создать саму строку post_targets."""
    post_id = _make_posted_post(**kwargs)
    post_targets_repo.record_targets(post_id, [(chat_id, message_id, None)])
    return post_id


async def test_handle_negative_reactions_sets_flag_and_notifies():
    post_id = _make_posted_post()
    application = AsyncMock()

    await _handle_negative_reactions(application, post_id, chat_id=-100123, message_id=42, negative_count=7)

    with session_scope() as session:
        assert session.get(Post, post_id).negative_alert_sent is True
    application.bot.send_message.assert_awaited_once()
    application.bot.delete_message.assert_not_awaited()  # auto_delete выключен по умолчанию


async def test_handle_negative_reactions_does_not_set_flag_on_send_failure():
    """Критичный фикс (код-ревью Фазы 5+): раньше флаг ставился ДО отправки
    уведомления — если send_message падал, владелец тихо никогда не
    узнавал, а флаг уже стоял, блокируя повторную попытку. Теперь при
    неудачной отправке флаг НЕ ставится."""
    post_id = _make_posted_post()
    application = AsyncMock()
    application.bot.send_message.side_effect = RuntimeError("Telegram API недоступен")

    await _handle_negative_reactions(application, post_id, chat_id=-100123, message_id=42, negative_count=7)

    with session_scope() as session:
        assert session.get(Post, post_id).negative_alert_sent is False
    application.bot.delete_message.assert_not_awaited()


async def test_handle_negative_reactions_does_not_notify_twice():
    post_id = _make_posted_post(negative_alert_sent=True)
    application = AsyncMock()

    await _handle_negative_reactions(application, post_id, chat_id=-100123, message_id=42, negative_count=7)

    application.bot.send_message.assert_not_awaited()


async def test_handle_negative_reactions_auto_deletes_when_enabled():
    settings_store.save_setting("auto_delete_on_negative", True, "bool")
    invalidate_settings_cache()
    post_id = _make_posted_post()
    application = AsyncMock()

    await _handle_negative_reactions(application, post_id, chat_id=-100123, message_id=42, negative_count=7)

    application.bot.delete_message.assert_awaited_once_with(chat_id=-100123, message_id=42)
    with session_scope() as session:
        assert "авто-удалён" in session.get(Post, post_id).status_reason


async def test_handle_negative_reactions_respects_hourly_delete_cap():
    """Регрессия/security-фикс: потолок авто-удалений в час защищает от
    массового необратимого удаления при скоординированном всплеске
    негативных реакций (бригадинг) — при достижении потолка пост всё равно
    уведомляется, но НЕ удаляется автоматически."""
    settings_store.save_setting("auto_delete_on_negative", True, "bool")
    settings_store.save_setting("max_auto_deletes_per_hour", 1, "int")
    invalidate_settings_cache()

    post_id_1 = _make_posted_post()
    post_id_2 = _make_posted_post()
    application = AsyncMock()

    # Первый пост — лимит ещё свободен, удаляется.
    await _handle_negative_reactions(application, post_id_1, chat_id=-100123, message_id=1, negative_count=7)
    application.bot.delete_message.assert_awaited_once()

    # Второй пост в том же часовом окне — лимит исчерпан, НЕ удаляется, но
    # уведомление всё равно отправляется с честным текстом.
    application.bot.delete_message.reset_mock()
    await _handle_negative_reactions(application, post_id_2, chat_id=-100123, message_id=2, negative_count=7)
    application.bot.delete_message.assert_not_awaited()
    application.bot.send_message.assert_awaited()
    last_call_text = application.bot.send_message.call_args.kwargs["text"]
    assert "ПРОПУЩЕНО" in last_call_text

    with session_scope() as session:
        post2 = session.get(Post, post_id_2)
        assert post2.negative_alert_sent is True  # уведомлён, флаг всё равно ставится
        assert post2.status_reason is None  # но НЕ помечен как удалённый


async def test_handle_negative_reactions_missing_post_noop():
    application = AsyncMock()
    await _handle_negative_reactions(application, 999999, chat_id=-100123, message_id=42, negative_count=7)
    application.bot.send_message.assert_not_awaited()


async def test_handle_negative_reactions_no_application_does_not_raise():
    """Регрессия: раньше `negative_alert_sent` ставился ДО попытки
    уведомления — если бот не запущен (application=None), владелец никогда
    не узнавал о посте, а флаг уже стоял, блокируя повторную попытку на
    следующем цикле. Теперь флаг НЕ ставится, пока уведомление реально не
    доставлено — следующий цикл сбора статистики попробует снова."""
    post_id = _make_posted_post()
    await _handle_negative_reactions(None, post_id, chat_id=-100123, message_id=42, negative_count=7)
    with session_scope() as session:
        assert session.get(Post, post_id).negative_alert_sent is False


async def test_collect_stats_triggers_negative_alert_when_threshold_exceeded():
    _clear_posts()
    settings_store.save_setting("negative_reaction_threshold", 3, "int")
    invalidate_settings_cache()
    now = datetime.now(timezone.utc)
    post_id = _make_posted_post_with_target(-100123, 42, posted_at=now)

    client = AsyncMock()
    client.get_messages.return_value = _fake_message({"👎": 5})
    application = AsyncMock()

    captured = await collect_stats(client, application)

    assert captured == 1
    application.bot.send_message.assert_awaited_once()
    with session_scope() as session:
        assert session.get(Post, post_id).negative_alert_sent is True


async def test_collect_stats_no_alert_when_threshold_zero():
    _clear_posts()
    settings_store.save_setting("negative_reaction_threshold", 0, "int")
    invalidate_settings_cache()
    now = datetime.now(timezone.utc)
    _make_posted_post_with_target(-100123, 42, posted_at=now)

    client = AsyncMock()
    client.get_messages.return_value = _fake_message({"👎": 999})
    application = AsyncMock()

    await collect_stats(client, application)

    application.bot.send_message.assert_not_awaited()


async def test_collect_stats_no_alert_below_threshold():
    _clear_posts()
    settings_store.save_setting("negative_reaction_threshold", 10, "int")
    invalidate_settings_cache()
    now = datetime.now(timezone.utc)
    _make_posted_post_with_target(-100123, 42, posted_at=now)

    client = AsyncMock()
    client.get_messages.return_value = _fake_message({"👎": 3})
    application = AsyncMock()

    await collect_stats(client, application)

    application.bot.send_message.assert_not_awaited()


# --- F31: метрики суммируются по ВСЕМ успешным целям поста ---


async def test_collect_stats_sums_metrics_across_multiple_targets():
    _clear_posts()
    now = datetime.now(timezone.utc)
    post_id = _make_posted_post(posted_at=now)
    post_targets_repo.record_targets(
        post_id, [(-100111, 1, None), (-100222, 2, None)]
    )

    client = AsyncMock()
    client.get_messages.side_effect = [
        _fake_message({"👍": 3}, views=100, forwards=5),
        _fake_message({"👍": 2}, views=50, forwards=1),
    ]

    captured = await collect_stats(client, None)

    assert captured == 1
    with session_scope() as session:
        stat = session.query(PostStat).filter(PostStat.post_id == post_id).one()
        assert stat.view_count == 150
        assert stat.forward_count == 6
        assert stat.reaction_count == 5


async def test_collect_stats_skips_post_with_no_successful_targets():
    _clear_posts()
    now = datetime.now(timezone.utc)
    post_id = _make_posted_post(posted_at=now)
    post_targets_repo.record_targets(post_id, [(-100111, None, "TimedOut")])

    client = AsyncMock()
    captured = await collect_stats(client, None)

    assert captured == 0
    client.get_messages.assert_not_awaited()


async def test_collect_stats_ignores_failed_target_alongside_successful_one():
    _clear_posts()
    now = datetime.now(timezone.utc)
    post_id = _make_posted_post(posted_at=now)
    post_targets_repo.record_targets(
        post_id, [(-100111, 1, None), (-100222, None, "TimedOut")]
    )

    client = AsyncMock()
    client.get_messages.return_value = _fake_message({}, views=100, forwards=5)

    captured = await collect_stats(client, None)

    assert captured == 1
    client.get_messages.assert_awaited_once_with(-100111, ids=1)
