"""Тесты умного расписания (F19): агрегация, рекомендация часов и
автоприменение к POSTING_SLOTS (доделка Фазы 4, аудит Фазы 5+)."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from tg_repost.config import get_settings, invalidate_settings_cache
from tg_repost.db.models import AppSetting, Post, PostKind, PostStat, PostStatus, Secret
from tg_repost.db.session import session_scope
from tg_repost.scheduler.smart_schedule import (
    ScheduleRecommendation,
    aggregate_views_by_hour,
    apply_recommended_slots,
    auto_apply_slots_job,
    compute_recommended_slots,
    recommend_hours,
)
from tg_repost.webui import settings_store


def test_aggregate_views_by_hour_sums_same_hour():
    samples = [(10, 100), (10, 50), (14, 30)]
    assert aggregate_views_by_hour(samples) == {10: 150, 14: 30}


def test_aggregate_views_by_hour_ignores_invalid_hour():
    assert aggregate_views_by_hour([(25, 10), (-1, 5), (10, 20)]) == {10: 20}


def test_aggregate_views_by_hour_negative_views_clamped_to_zero():
    assert aggregate_views_by_hour([(10, -5)]) == {10: 0}


def test_aggregate_views_by_hour_empty():
    assert aggregate_views_by_hour([]) == {}


def test_recommend_hours_top_n():
    totals = {10: 100, 14: 300, 19: 200}
    assert recommend_hours(totals, top_n=2) == ["14:00", "19:00"]


def test_recommend_hours_tie_break_by_hour_ascending():
    totals = {19: 100, 10: 100}
    assert recommend_hours(totals, top_n=2) == ["10:00", "19:00"]


def test_recommend_hours_empty():
    assert recommend_hours({}, top_n=3) == []


def test_recommend_hours_formats_two_digit_hour():
    assert recommend_hours({9: 5}, top_n=1) == ["09:00"]


def _clear_source_posts() -> None:
    """Изоляция между DB-тестами этого файла: один и тот же sqlite:///:memory:
    engine-синглтон используется всем pytest-процессом (см. tests/conftest.py)."""
    with session_scope() as session:
        session.query(PostStat).delete()
        session.query(Post).filter(Post.kind == PostKind.SOURCE).delete()


def test_compute_recommended_slots_uses_correct_utc_hour_regardless_of_local_tz():
    """Регрессия на найденный код-ревью баг: SQLite не сохраняет tzinfo, и
    `posted_at` читается из БД как naive datetime. Старый код делал
    `.astimezone(timezone.utc)`, что трактует naive значение как ЛОКАЛЬНОЕ
    время сервера и сдвигает час на величину локального офсета (например,
    23:00 UTC превращалось в 18:00 на машине с офсетом -5). Фикс —
    `.replace(tzinfo=timezone.utc)`. Здесь сохраняем заведомо точное UTC-время
    и проверяем, что рекомендованный час не съезжает — тест должен падать на
    старом коде на любой машине, чья локальная таймзона отличается от UTC.
    """
    _clear_source_posts()
    fixed_hour_utc = 23
    posted_at = datetime(2026, 1, 1, fixed_hour_utc, 0, 0, tzinfo=timezone.utc)

    with session_scope() as session:
        # min_posts по умолчанию (SMART_SCHEDULE_MIN_POSTS=20) — создаём с запасом.
        for _ in range(25):
            post = Post(kind=PostKind.SOURCE, status=PostStatus.POSTED, posted_at=posted_at)
            session.add(post)
            session.flush()
            session.add(PostStat(post_id=post.id, view_count=10))

    rec = compute_recommended_slots(window_days=3650, top_n=1, min_posts=20)
    assert rec.enough_data
    assert rec.recommended_slots == [f"{fixed_hour_utc:02d}:00"]


def test_compute_recommended_slots_counts_posts_not_distinct_timestamps():
    """Регрессия: posts_analyzed раньше дедуплицировал по ЗНАЧЕНИЮ posted_at,
    а не по id поста — несколько постов с одинаковым (до секунды) временем
    публикации схлопывались в один, занижая posts_analyzed. Здесь все 25
    постов делят один и тот же posted_at, но posts_analyzed должен быть 25.
    """
    _clear_source_posts()
    posted_at = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
    with session_scope() as session:
        for _ in range(25):
            post = Post(kind=PostKind.SOURCE, status=PostStatus.POSTED, posted_at=posted_at)
            session.add(post)
            session.flush()
            session.add(PostStat(post_id=post.id, view_count=1))

    rec = compute_recommended_slots(window_days=3650, top_n=1, min_posts=20)
    assert rec.posts_analyzed == 25


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    """Изоляция для тестов apply_recommended_slots/auto_apply_slots_job:
    `posting_slots`/`smart_schedule_auto_apply` пишутся в `app_settings`
    (общий sqlite-engine на весь pytest-процесс, см. tests/conftest.py).
    chdir на tmp_path — на случай, если settings_store когда-нибудь решит
    писать .env (сейчас не пишет для не-секретных полей, но паттерн
    единообразен с test_settings_store.py)."""
    monkeypatch.chdir(tmp_path)
    with session_scope() as session:
        session.query(AppSetting).delete()
        session.query(Secret).delete()
    invalidate_settings_cache()
    yield
    with session_scope() as session:
        session.query(AppSetting).delete()
        session.query(Secret).delete()
    invalidate_settings_cache()


def _rec(slots: list[str], enough_data: bool = True) -> ScheduleRecommendation:
    return ScheduleRecommendation(
        enough_data=enough_data, posts_analyzed=25, min_required=20,
        recommended_slots=slots,
    )


def test_apply_recommended_slots_no_data_returns_false():
    assert apply_recommended_slots(_rec(["10:00"], enough_data=False)) is False


def test_apply_recommended_slots_empty_slots_returns_false():
    assert apply_recommended_slots(_rec([])) is False


def test_apply_recommended_slots_applies_when_different():
    settings_store.save_setting("posting_slots", ["09:00"], "csv_list")
    invalidate_settings_cache()
    assert apply_recommended_slots(_rec(["14:00", "20:00"])) is True
    assert get_settings().posting_slots == ["14:00", "20:00"]


def test_apply_recommended_slots_noop_when_same():
    settings_store.save_setting("posting_slots", ["10:00", "18:00"], "csv_list")
    invalidate_settings_cache()
    assert apply_recommended_slots(_rec(["18:00", "10:00"])) is False


async def test_auto_apply_slots_job_noop_when_disabled():
    settings_store.save_setting("smart_schedule_auto_apply", False, "bool")
    settings_store.save_setting("posting_slots", ["09:00"], "csv_list")
    invalidate_settings_cache()
    _clear_source_posts()
    await auto_apply_slots_job()
    assert get_settings().posting_slots == ["09:00"]


async def test_auto_apply_slots_job_applies_and_resyncs_when_enabled(monkeypatch):
    settings_store.save_setting("smart_schedule_auto_apply", True, "bool")
    settings_store.save_setting("posting_slots", ["09:00"], "csv_list")
    settings_store.save_setting("smart_schedule_min_posts", 20, "int")
    # Окно анализа по умолчанию (21 день) не покрыло бы фиксированную
    # историческую дату ниже относительно текущей "сегодня" — расширяем,
    # как и в test_compute_recommended_slots_uses_correct_utc_hour_*.
    settings_store.save_setting("smart_schedule_window_days", 3650, "int")
    invalidate_settings_cache()
    _clear_source_posts()

    fixed_hour_utc = 14
    posted_at = datetime(2026, 1, 1, fixed_hour_utc, 0, 0, tzinfo=timezone.utc)
    with session_scope() as session:
        for _ in range(25):
            post = Post(kind=PostKind.SOURCE, status=PostStatus.POSTED, posted_at=posted_at)
            session.add(post)
            session.flush()
            session.add(PostStat(post_id=post.id, view_count=10))

    resync_mock = AsyncMock()
    monkeypatch.setattr("tg_repost.webui.supervisor.resync_scheduler_jobs", resync_mock)

    await auto_apply_slots_job()

    assert get_settings().posting_slots == [f"{fixed_hour_utc:02d}:00"]
    resync_mock.assert_awaited_once()


async def test_auto_apply_slots_job_skips_resync_when_no_change(monkeypatch):
    """Если рекомендация совпадает с уже действующими слотами —
    resync_scheduler_jobs не должен вызываться вообще (не нужно дёргать
    планировщик, когда состав джобов не изменился)."""
    settings_store.save_setting("smart_schedule_auto_apply", True, "bool")
    settings_store.save_setting("smart_schedule_min_posts", 20, "int")
    # Окно анализа по умолчанию (21 день) не покрыло бы фиксированную
    # историческую дату ниже относительно текущей "сегодня" — расширяем,
    # как и в test_compute_recommended_slots_uses_correct_utc_hour_*.
    settings_store.save_setting("smart_schedule_window_days", 3650, "int")
    invalidate_settings_cache()
    _clear_source_posts()

    fixed_hour_utc = 14
    posted_at = datetime(2026, 1, 1, fixed_hour_utc, 0, 0, tzinfo=timezone.utc)
    with session_scope() as session:
        for _ in range(25):
            post = Post(kind=PostKind.SOURCE, status=PostStatus.POSTED, posted_at=posted_at)
            session.add(post)
            session.flush()
            session.add(PostStat(post_id=post.id, view_count=10))

    settings_store.save_setting("posting_slots", [f"{fixed_hour_utc:02d}:00"], "csv_list")
    invalidate_settings_cache()

    resync_mock = AsyncMock()
    monkeypatch.setattr("tg_repost.webui.supervisor.resync_scheduler_jobs", resync_mock)

    await auto_apply_slots_job()

    resync_mock.assert_not_awaited()
