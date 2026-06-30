"""Тесты авто-дайджеста (F20): ранжирование постов по просмотрам."""

from tg_repost.scheduler.digest import rank_posts_by_views


def test_rank_posts_by_views_basic():
    rows = [(1, 10), (2, 50), (3, 30)]
    assert rank_posts_by_views(rows, top_n=2) == [2, 3]


def test_rank_posts_by_views_tie_break_by_id():
    rows = [(3, 10), (1, 10), (2, 10)]
    assert rank_posts_by_views(rows, top_n=3) == [1, 2, 3]


def test_rank_posts_by_views_top_n_limits():
    rows = [(1, 5), (2, 1)]
    assert rank_posts_by_views(rows, top_n=1) == [1]


def test_rank_posts_by_views_empty():
    assert rank_posts_by_views([], top_n=5) == []


def test_rank_posts_by_views_top_n_larger_than_rows():
    rows = [(1, 5)]
    assert rank_posts_by_views(rows, top_n=10) == [1]
