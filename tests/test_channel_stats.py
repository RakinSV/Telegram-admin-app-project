"""Статистика канала через MTProto Stats API (F56).

Тесты делятся надвое:

* разбор ответа Telegram — чистая функция, проверяется без сети;
* поведение сборщика, когда что-то идёт не так. Второе важнее: отсутствие
  прав администратора — не сбой, а состояние, которое чинит владелец, и
  оно обязано быть отличимо от настоящей ошибки.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tg_repost.db.models import ChannelStatsSnapshot, TargetGroup
from tg_repost.db.session import session_scope
from tg_repost.scheduler import channel_stats

CHAT = -100424242


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def _clean():
    """Чистим ВСЕ цели, а не только свою.

    `collect_channel_stats` по своей природе обходит все активные целевые
    каналы, поэтому тест обязан контролировать весь список: цель, оставшаяся
    от соседнего файла, добавляет в отчёт лишний канал и ломает счётчики.
    Поймано тем, что тесты проходили по отдельности и падали в общем прогоне.
    """
    def _wipe():
        with session_scope() as session:
            session.query(ChannelStatsSnapshot).delete()
            session.query(TargetGroup).delete()

    _wipe()
    yield
    _wipe()


def _stats_response(
    *, views: int = 300, shares: int = 20, reactions: int = 40,
    notif_part: int = 600, notif_total: int = 1000,
) -> SimpleNamespace:
    """Ответ Telegram в том виде, в каком его отдаёт Telethon."""
    return SimpleNamespace(
        views_per_post=SimpleNamespace(current=views, previous=0),
        shares_per_post=SimpleNamespace(current=shares, previous=0),
        reactions_per_post=SimpleNamespace(current=reactions, previous=0),
        enabled_notifications=SimpleNamespace(part=notif_part, total=notif_total),
    )


def _client(side_effect=None, response=None) -> AsyncMock:
    client = AsyncMock()
    client.get_entity = AsyncMock(return_value=SimpleNamespace(id=CHAT))
    if side_effect is not None:
        client.side_effect = side_effect
    else:
        client.return_value = response if response is not None else _stats_response()
    return client


def _add_target() -> None:
    with session_scope() as session:
        session.add(TargetGroup(chat_id=CHAT, title="Канал", is_active=True))


# --- разбор ответа ---


def test_parses_scalar_fields():
    parsed = channel_stats.parse_broadcast_stats(_stats_response())

    assert parsed["views_per_post"] == 300
    assert parsed["shares_per_post"] == 20
    assert parsed["reactions_per_post"] == 40


def test_computes_notification_percentage():
    """Telegram отдаёт долю двумя числами, а не готовым процентом."""
    parsed = channel_stats.parse_broadcast_stats(
        _stats_response(notif_part=600, notif_total=1000)
    )

    assert parsed["notifications_enabled_pct"] == 60.0


def test_zero_total_does_not_divide_by_zero():
    """У канала без подписчиков `total` равен нулю — это реальный случай."""
    parsed = channel_stats.parse_broadcast_stats(
        _stats_response(notif_part=0, notif_total=0)
    )

    assert parsed["notifications_enabled_pct"] is None


def test_missing_fields_become_none_not_zero():
    """Telegram может не отдать поле. «Нет данных» — не «ноль просмотров»."""
    parsed = channel_stats.parse_broadcast_stats(SimpleNamespace())

    assert parsed == {
        "views_per_post": None,
        "shares_per_post": None,
        "reactions_per_post": None,
        "notifications_enabled_pct": None,
    }


# --- сбор ---


async def test_collects_snapshot_for_active_target():
    _add_target()

    report = await channel_stats.collect_channel_stats(_client())

    assert report.collected == 1
    with session_scope() as session:
        row = session.query(ChannelStatsSnapshot).one()
        assert row.chat_id == CHAT
        assert row.notifications_enabled_pct == 60.0
        assert row.tenant_id == 1  # ключ арендатора проставляется по умолчанию


async def test_inactive_target_is_skipped():
    with session_scope() as session:
        session.add(TargetGroup(chat_id=CHAT, title="Канал", is_active=False))

    report = await channel_stats.collect_channel_stats(_client())

    assert report.collected == 0


async def test_missing_admin_rights_is_not_counted_as_failure():
    """Главный тест файла.

    Нет прав администратора — это не сбой, а состояние, которое владелец
    ЧИНИТ, выдав боту права. Сваленное в общий счётчик ошибок, оно выглядит
    как «что-то сломалось» и живёт в логах годами, ничего не меняя.
    """
    _add_target()
    client = _client(side_effect=Exception("CHAT_ADMIN_REQUIRED"))

    report = await channel_stats.collect_channel_stats(client)

    assert report.no_rights == [CHAT]
    assert report.failed == []
    assert report.collected == 0


async def test_megagroup_is_reported_separately():
    """У мегагруппы другой метод статистики — это не ошибка сбора."""
    _add_target()
    client = _client(side_effect=Exception("BROADCAST_REQUIRED"))

    report = await channel_stats.collect_channel_stats(client)

    assert report.not_a_channel == [CHAT]
    assert report.failed == []


async def test_real_error_is_reported_as_failure():
    _add_target()
    client = _client(side_effect=Exception("Connection reset by peer"))

    report = await channel_stats.collect_channel_stats(client)

    assert report.failed == [CHAT]
    assert report.no_rights == []


async def test_one_broken_channel_does_not_stop_the_rest():
    other = -100999999
    with session_scope() as session:
        session.add(TargetGroup(chat_id=CHAT, title="A", is_active=True))
        session.add(TargetGroup(chat_id=other, title="Б", is_active=True))

    calls = {"n": 0}

    def _flaky(*_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise Exception("Connection reset by peer")
        return _stats_response()

    client = AsyncMock()
    client.get_entity = AsyncMock(return_value=SimpleNamespace(id=CHAT))
    client.side_effect = _flaky

    report = await channel_stats.collect_channel_stats(client)

    assert report.collected == 1
    assert len(report.failed) == 1


# --- динамика ---


def _snapshot(pct: float, *, days_ago: int) -> None:
    with session_scope() as session:
        session.add(
            ChannelStatsSnapshot(
                chat_id=CHAT,
                notifications_enabled_pct=pct,
                captured_at=_utcnow() - timedelta(days=days_ago),
            )
        )


def test_single_snapshot_is_not_a_trend():
    """Одна точка — это не динамика, и показывать её как динамику нельзя."""
    _snapshot(60.0, days_ago=1)

    assert channel_stats.mute_trend(CHAT).enough_data is False


def test_falling_share_is_alarming():
    """Ради этого фича и делалась: люди ещё подписаны, но уже не читают."""
    _snapshot(70.0, days_ago=20)
    _snapshot(61.0, days_ago=1)

    trend = channel_stats.mute_trend(CHAT)

    assert trend.delta == -9.0
    assert trend.is_alarming is True


def test_small_fluctuation_is_not_alarming():
    """Десятые доли — шум округления.

    Тревога по шуму приучает владельца не смотреть на предупреждения, и
    тогда настоящее падение он тоже пропустит.
    """
    _snapshot(60.5, days_ago=20)
    _snapshot(60.1, days_ago=1)

    assert channel_stats.mute_trend(CHAT).is_alarming is False


def test_growing_share_is_not_alarming():
    _snapshot(50.0, days_ago=20)
    _snapshot(70.0, days_ago=1)

    trend = channel_stats.mute_trend(CHAT)

    assert trend.delta == 20.0
    assert trend.is_alarming is False


def test_snapshots_outside_window_ignored():
    _snapshot(90.0, days_ago=100)
    _snapshot(60.0, days_ago=1)

    assert channel_stats.mute_trend(CHAT, window_days=30).enough_data is False


def test_null_percentages_are_excluded():
    """Снимок без доли уведомлений не участвует в динамике."""
    with session_scope() as session:
        session.add(
            ChannelStatsSnapshot(
                chat_id=CHAT, notifications_enabled_pct=None,
                captured_at=_utcnow() - timedelta(days=10),
            )
        )
    _snapshot(60.0, days_ago=1)

    assert channel_stats.mute_trend(CHAT).enough_data is False


def test_trend_uses_first_and_last_not_min_and_max():
    """Динамика — это «было → стало», а не размах колебаний."""
    _snapshot(60.0, days_ago=20)
    _snapshot(95.0, days_ago=10)
    _snapshot(58.0, days_ago=1)

    trend = channel_stats.mute_trend(CHAT)

    assert trend.first_pct == 60.0
    assert trend.last_pct == 58.0
    assert trend.delta == -2.0


# --- вывод в /stats ---


def test_stats_block_warns_about_silent_churn():
    from tg_repost import targets_repo
    from tg_repost.scheduler.stats import _mute_lines

    targets_repo.add_target(CHAT, title="Канал")
    _snapshot(70.0, days_ago=20)
    _snapshot(55.0, days_ago=1)

    text = "\n".join(_mute_lines(CHAT, window_days=30))

    assert "ТИХИЙ ОТТОК" in text
    assert "15.0" in text


def test_stats_block_silent_without_enough_data():
    from tg_repost.scheduler.stats import _mute_lines

    _snapshot(70.0, days_ago=1)

    assert _mute_lines(CHAT, window_days=30) == []
