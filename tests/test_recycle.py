"""Повтор выстреливших постов — recycling (F55).

Каждое из четырёх правил отбора закрывает свой способ испортить ленту, и
на каждое здесь есть тест:

1. только `kind=SOURCE` — иначе повтор сам станет кандидатом и текст будет
   крутиться бесконечно;
2. не повторять дважды;
3. минимальный возраст — вчерашнее повторять бессмысленно;
4. порог просмотров — повторяем выстрелившее, а не всё подряд.

Плюс главное: повтор идёт в МОДЕРАЦИЮ, а не в публикацию.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tg_repost.db.models import Post, PostKind, PostStat, PostStatus
from tg_repost.db.session import session_scope
from tg_repost.scheduler import recycle

CHAT = -100999


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(PostStat).delete()
            session.query(Post).delete()

    _wipe()
    yield
    _wipe()


def _posted(
    *,
    days_ago: int,
    views: int | None = 100,
    kind: PostKind = PostKind.SOURCE,
    text: str = "готовый текст",
) -> int:
    """Опубликованный пост с последним снимком метрик."""
    with session_scope() as session:
        post = Post(
            kind=kind,
            original_text="оригинал",
            rewritten_text=text,
            status=PostStatus.POSTED,
            posted_chat_id=CHAT,
            posted_at=_utcnow() - timedelta(days=days_ago),
        )
        session.add(post)
        session.flush()
        post_id = post.id
        if views is not None:
            session.add(
                PostStat(
                    post_id=post_id, view_count=views, reaction_count=0,
                    forward_count=0, captured_at=_utcnow() - timedelta(days=days_ago),
                )
            )
        return post_id


def _select(**overrides) -> list[int]:
    params = {
        "window_days": 30, "min_age_days": 7, "min_views": 0, "top_n": 5,
    }
    params.update(overrides)
    return recycle.select_recycle_candidates(**params)  # type: ignore[arg-type]


# --- правило 1: повтор не становится кандидатом ---


def test_recycle_post_is_never_a_candidate():
    """Иначе один и тот же текст крутился бы в ленте бесконечно.

    Самый важный тест файла: повтор — тоже опубликованный пост нужного
    возраста с просмотрами, то есть по всем прочим признакам он идеальный
    кандидат. Спасает только фильтр по `kind`.
    """
    _posted(days_ago=10, kind=PostKind.RECYCLE, views=99999)

    assert _select() == []


def test_digest_and_ad_are_not_candidates():
    """Дайджест и реклама — тоже не оригиналы."""
    _posted(days_ago=10, kind=PostKind.DIGEST, views=5000)
    _posted(days_ago=10, kind=PostKind.AD, views=5000)

    assert _select() == []


# --- правило 2: не повторять дважды ---


def test_already_recycled_post_is_excluded():
    original = _posted(days_ago=10, views=500)
    assert _select() == [original]

    recycle.create_recycle_post(original)

    assert _select() == []


def test_exclusion_survives_rejection_of_the_repeat():
    """Владелец отклонил повтор — оригинал всё равно закрыт.

    Спорное место, поэтому фиксируем осознанно: отклонение означает «этот
    пост повторять не надо», и возвращать его в кандидаты значило бы
    предлагать одно и то же на каждом проходе планировщика.
    """
    original = _posted(days_ago=10, views=500)
    repeat_id = recycle.create_recycle_post(original)
    assert repeat_id is not None

    with session_scope() as session:
        repeat = session.get(Post, repeat_id)
        assert repeat is not None
        repeat.status = PostStatus.REJECTED

    assert _select() == []


# --- правило 3: минимальный возраст ---


def test_too_fresh_post_is_not_recycled():
    _posted(days_ago=2, views=1000)

    assert _select(min_age_days=7) == []


def test_post_outside_window_is_not_recycled():
    _posted(days_ago=90, views=1000)

    assert _select(window_days=30) == []


def test_post_inside_window_and_old_enough_is_selected():
    post_id = _posted(days_ago=10, views=1000)

    assert _select(window_days=30, min_age_days=7) == [post_id]


def test_contradictory_window_settings_yield_nothing(caplog):
    """Минимальный возраст больше окна — кандидатов не будет никогда.

    Со стороны это выглядит как «фича не работает», поэтому предупреждение
    в лог обязательно.
    """
    _posted(days_ago=10, views=1000)

    with caplog.at_level("WARNING"):
        assert _select(window_days=5, min_age_days=7) == []

    assert any("окно пустое" in r.message for r in caplog.records)


# --- правило 4: порог просмотров ---


def test_below_threshold_is_not_recycled():
    _posted(days_ago=10, views=50)

    assert _select(min_views=500) == []


def test_post_without_metrics_counts_as_zero_views():
    """«Не знаем, выстрелил ли» — не повод повторять."""
    _posted(days_ago=10, views=None)

    assert _select(min_views=1) == []


def test_post_without_metrics_passes_when_no_threshold():
    post_id = _posted(days_ago=10, views=None)

    assert _select(min_views=0) == [post_id]


# --- ранжирование ---


def test_candidates_ranked_by_views_desc():
    weak = _posted(days_ago=10, views=100)
    strong = _posted(days_ago=10, views=900)
    middle = _posted(days_ago=10, views=500)

    assert _select() == [strong, middle, weak]


def test_top_n_limits_result():
    _posted(days_ago=10, views=100)
    strong = _posted(days_ago=10, views=900)

    assert _select(top_n=1) == [strong]


def test_equal_views_ordered_by_id_for_reproducibility():
    first = _posted(days_ago=10, views=300)
    second = _posted(days_ago=10, views=300)

    assert _select() == [first, second]


# --- создание повтора ---


def test_repeat_goes_to_moderation_not_published():
    """Повтор без подтверждения владельца превращает ленту в самоповтор."""
    original = _posted(days_ago=10, views=500)

    repeat_id = recycle.create_recycle_post(original)

    with session_scope() as session:
        repeat = session.get(Post, repeat_id)
        assert repeat is not None
        assert repeat.status == PostStatus.REWRITTEN  # не POSTED и не APPROVED
        assert repeat.kind == PostKind.RECYCLE
        assert repeat.recycled_from_id == original
        assert repeat.posted_at is None


def test_repeat_reuses_ready_text_without_rewrite():
    original = _posted(days_ago=10, views=500, text="уже отрерайченный текст")

    repeat_id = recycle.create_recycle_post(original)

    with session_scope() as session:
        repeat = session.get(Post, repeat_id)
        assert repeat is not None
        assert repeat.rewritten_text == "уже отрерайченный текст"


def test_repeat_does_not_copy_content_hash():
    """Копия хэша сделала бы будущую ошибку тихой.

    `content_hash` служит дедупликации на приёме: повтор с тем же хэшем
    был бы отсеян как «точный дубль», то есть фича ломала бы сама себя.
    """
    with session_scope() as session:
        post = Post(
            kind=PostKind.SOURCE, original_text="о", rewritten_text="т",
            content_hash="deadbeef", status=PostStatus.POSTED,
            posted_chat_id=CHAT, posted_at=_utcnow() - timedelta(days=10),
        )
        session.add(post)
        session.flush()
        original = post.id

    repeat_id = recycle.create_recycle_post(original)

    with session_scope() as session:
        repeat = session.get(Post, repeat_id)
        assert repeat is not None
        assert repeat.content_hash is None


def test_missing_original_returns_none():
    assert recycle.create_recycle_post(999999) is None


def test_original_without_text_is_skipped():
    with session_scope() as session:
        post = Post(
            kind=PostKind.SOURCE, original_text=None, rewritten_text=None,
            status=PostStatus.POSTED, posted_chat_id=CHAT,
            posted_at=_utcnow() - timedelta(days=10),
        )
        session.add(post)
        session.flush()
        empty_id = post.id

    assert recycle.create_recycle_post(empty_id) is None


# --- джоб ---


def test_job_does_nothing_when_disabled(monkeypatch):
    """Выключено — значит не создаёт ничего. Фича меняет ленту, поэтому
    по умолчанию она выключена, и это должно быть защищено тестом."""
    from tg_repost.config import get_settings

    monkeypatch.setattr(get_settings(), "recycle_enabled", False, raising=False)
    _posted(days_ago=10, views=1000)

    assert recycle.run_recycle_job() == 0
    with session_scope() as session:
        assert session.query(Post).filter(Post.kind == PostKind.RECYCLE).count() == 0


def test_job_creates_repeats_when_enabled(monkeypatch):
    from tg_repost.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "recycle_enabled", True, raising=False)
    monkeypatch.setattr(settings, "recycle_top_n", 1, raising=False)
    monkeypatch.setattr(settings, "recycle_window_days", 30, raising=False)
    monkeypatch.setattr(settings, "recycle_min_age_days", 7, raising=False)
    monkeypatch.setattr(settings, "recycle_min_views", 0, raising=False)
    _posted(days_ago=10, views=100)
    strong = _posted(days_ago=10, views=900)

    assert recycle.run_recycle_job() == 1

    with session_scope() as session:
        repeat = session.query(Post).filter(Post.kind == PostKind.RECYCLE).one()
        assert repeat.recycled_from_id == strong


def test_job_is_idempotent_across_runs(monkeypatch):
    """Второй проход планировщика не должен повторять то же самое."""
    from tg_repost.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "recycle_enabled", True, raising=False)
    monkeypatch.setattr(settings, "recycle_top_n", 5, raising=False)
    monkeypatch.setattr(settings, "recycle_window_days", 30, raising=False)
    monkeypatch.setattr(settings, "recycle_min_age_days", 7, raising=False)
    monkeypatch.setattr(settings, "recycle_min_views", 0, raising=False)
    _posted(days_ago=10, views=900)
    _posted(days_ago=10, views=800)

    assert recycle.run_recycle_job() == 2
    assert recycle.run_recycle_job() == 0
