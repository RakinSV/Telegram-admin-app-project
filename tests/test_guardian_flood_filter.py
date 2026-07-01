"""Тесты антифлуда Guardian (G06) — состояние только в памяти, без БД."""

from guardian.filters.flood_filter import FloodFilter


def test_flood_filter_under_limit_not_flagged():
    ff = FloodFilter(max_messages=5, window_seconds=10)
    for i in range(5):
        assert ff.check_flood(user_id=1, now=float(i)) is False


def test_flood_filter_over_limit_flagged():
    ff = FloodFilter(max_messages=3, window_seconds=10)
    results = [ff.check_flood(user_id=1, now=float(i)) for i in range(5)]
    assert results == [False, False, False, True, True]


def test_flood_filter_old_messages_expire_out_of_window():
    ff = FloodFilter(max_messages=2, window_seconds=5)
    assert ff.check_flood(user_id=1, now=0.0) is False
    assert ff.check_flood(user_id=1, now=1.0) is False
    # Далеко за пределами окна — старые timestamps должны "истечь".
    assert ff.check_flood(user_id=1, now=100.0) is False


def test_flood_filter_separate_users_independent():
    ff = FloodFilter(max_messages=1, window_seconds=10)
    assert ff.check_flood(user_id=1, now=0.0) is False
    assert ff.check_flood(user_id=2, now=0.0) is False
    assert ff.check_flood(user_id=1, now=0.5) is True
    assert ff.check_flood(user_id=2, now=0.5) is True


def test_flood_filter_duplicate_detection():
    ff = FloodFilter(max_messages=100, window_seconds=10)
    assert ff.check_duplicate(user_id=1, text="привет") is False
    assert ff.check_duplicate(user_id=1, text="привет") is True
    assert ff.check_duplicate(user_id=1, text="другое сообщение") is False


def test_flood_filter_duplicate_independent_per_user():
    ff = FloodFilter(max_messages=100, window_seconds=10)
    assert ff.check_duplicate(user_id=1, text="текст") is False
    assert ff.check_duplicate(user_id=2, text="текст") is False
