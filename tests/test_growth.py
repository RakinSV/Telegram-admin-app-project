"""Тесты growth-трекера (F22, каркас): дельта подписчиков по снимкам."""

from datetime import datetime, timedelta, timezone

from tg_repost.scheduler.growth import compute_growth_delta


def test_compute_growth_delta_basic():
    now = datetime.now(timezone.utc)
    snapshots = [(now, 100), (now + timedelta(hours=1), 120)]
    assert compute_growth_delta(snapshots) == (100, 120, 20)


def test_compute_growth_delta_sorts_unsorted_input():
    now = datetime.now(timezone.utc)
    snapshots = [(now + timedelta(hours=1), 120), (now, 100)]
    assert compute_growth_delta(snapshots) == (100, 120, 20)


def test_compute_growth_delta_insufficient_data():
    assert compute_growth_delta([]) is None
    assert compute_growth_delta([(datetime.now(timezone.utc), 50)]) is None


def test_compute_growth_delta_negative_delta():
    now = datetime.now(timezone.utc)
    snapshots = [(now, 200), (now + timedelta(hours=1), 150)]
    assert compute_growth_delta(snapshots) == (200, 150, -50)


def test_compute_growth_delta_three_snapshots_uses_first_and_last():
    now = datetime.now(timezone.utc)
    snapshots = [
        (now, 100),
        (now + timedelta(hours=1), 999),
        (now + timedelta(hours=2), 130),
    ]
    assert compute_growth_delta(snapshots) == (100, 130, 30)
