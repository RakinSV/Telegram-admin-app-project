"""Три поломки пайплайна, найденные по жалобе «ловит посты, дальше тишина».

Разбор логов стенда 2026-08-23. Провайдер был настроен верно, рерайт работал,
и всё равно владелец не видел НИЧЕГО. Три причины, каждая своя:

1. ОТПРАВКА ЖДАЛА ВСЮ ПАЧКУ. `pipeline_tick` вызывал рерайт пачки из пяти
   постов и только ПОТОМ отправку на модерацию. При семи минутах на пост
   первый готовый ждал остальных четырёх — полчаса тишины на ровном месте.
   В базе это было видно прямо: один пост `rewritten`, ноль
   `pending_approval`.

2. ЗАВИСШИЕ ПОСТЫ НИКТО НЕ ВОЗВРАЩАЛ. Статус `rewriting` — это отметка «пост
   занят». Процесс перезапустился посреди рерайта, и отметка осталась
   навсегда: пост не в очереди, не готов и не упал, его просто нет. На стенде
   таких нашлось ШЕСТЬ, самый старый висел 31 день. У очереди задач возврат
   арендованного упавшим процессом есть с самого начала, у рерайта его забыли.

3. ЗАТОР БЫЛ НЕВИДИМ. Единственный признак — предупреждение APScheduler
   «maximum number of running instances reached», которое не говорит ни что
   застряло, ни как давно, ни сколько ждёт очередь.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tg_repost.db.models import Post, PostKind, PostStatus
from tg_repost.db.session import session_scope
from tg_repost.scheduler import jobs, pipeline_state


@pytest.fixture(autouse=True)
def clean_posts():
    """Чистим посты И ВСЁ, ЧТО НА НИХ ССЫЛАЕТСЯ.

    Внешние ключи в SQLite по умолчанию декоративны (`PRAGMA foreign_keys=0`),
    поэтому удаление поста оставляет варианты сиротами — и следующий файл
    тестов видит чужие строки. На этом сразу упал `test_post_variants`:
    порознь проходил, в общем прогоне нет.
    """
    _wipe()
    pipeline_state.reset()
    yield
    _wipe()
    pipeline_state.reset()


def _wipe() -> None:
    from tg_repost.db.models import PostCoverVariant, PostRewriteVariant

    with session_scope() as session:
        session.query(PostRewriteVariant).delete()
        session.query(PostCoverVariant).delete()
        session.query(Post).delete()


def _make_post(status: PostStatus, *, minutes_ago: int = 0) -> int:
    when = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    with session_scope() as session:
        post = Post(kind=PostKind.SOURCE, original_text="исходный текст",
                    status=status, created_at=when, updated_at=when)
        session.add(post)
        session.flush()
        return post.id


# --- 1. Готовый пост уходит сразу ---


@pytest.mark.asyncio
async def test_ready_post_is_dispatched_before_the_batch_finishes(monkeypatch):
    """ГЛАВНАЯ ПРОВЕРКА: отправка идёт ПОСЛЕ КАЖДОГО поста, а не после пачки.

    Гоняем НАСТОЯЩУЮ `rewrite_new_posts` — проверять собственную симуляцию
    цикла бессмысленно: она пройдёт и на сломанном коде.

    Считаем, сколько постов было отправлено к моменту начала рерайта каждого
    следующего. Если отправка стоит после пачки, все три отправки случатся в
    конце, и последовательность будет 0, 0, 0.
    """
    from tg_repost.rewriter.client import RewriteResult

    # Выключаем всё тяжёлое: проверяется порядок действий, а не рерайт.
    for name, value in {
        "FETCH_LINK_CONTENT_ENABLED": "false",
        "EDITORIAL_ENABLED": "false",
        "REWRITE_VARIANT_COUNT": "1",
        "COVER_ENABLED": "false",
        "REWRITE_MIN_SOURCE_CHARS": "0",
        "CLUSTER_GRACE_MINUTES": "0",
    }.items():
        monkeypatch.setenv(name, value)
    from tg_repost.config import invalidate_settings_cache
    invalidate_settings_cache()

    for _ in range(3):
        _make_post(PostStatus.NEW, minutes_ago=1)

    dispatched: list[int] = []
    seen_before_each: list[int] = []

    class FakeRewriter:
        async def rewrite(self, *args, **kwargs):
            seen_before_each.append(len(dispatched))
            return RewriteResult(text="готовый текст", prompt_tokens=1,
                                 completion_tokens=1)

        async def complete(self, *args, **kwargs):
            return ""

    async def dispatch() -> None:
        with session_scope() as session:
            ready = session.query(Post).filter(
                Post.status == PostStatus.REWRITTEN
            ).all()
            for post in ready:
                dispatched.append(post.id)
                post.set_status(PostStatus.PENDING_APPROVAL)

    await jobs.rewrite_new_posts(FakeRewriter(), batch=3, after_each=dispatch)

    invalidate_settings_cache()

    assert len(dispatched) == 3, f"отправлены не все: {dispatched}"
    assert seen_before_each == [0, 1, 2], (
        "к началу каждого следующего поста должен быть отправлен предыдущий; "
        f"получилось {seen_before_each} — отправка снова ждёт всю пачку"
    )


@pytest.mark.asyncio
async def test_dispatch_failure_does_not_stop_the_rest(monkeypatch):
    """Сбой отправки одного поста не должен ронять рерайт остальных: пост уже
    готов и лежит в очереди, следующий проход его подберёт."""
    from tg_repost.rewriter.client import RewriteResult

    for name, value in {
        "FETCH_LINK_CONTENT_ENABLED": "false",
        "EDITORIAL_ENABLED": "false",
        "REWRITE_VARIANT_COUNT": "1",
        "COVER_ENABLED": "false",
        "REWRITE_MIN_SOURCE_CHARS": "0",
        "CLUSTER_GRACE_MINUTES": "0",
    }.items():
        monkeypatch.setenv(name, value)
    from tg_repost.config import invalidate_settings_cache
    invalidate_settings_cache()

    for _ in range(3):
        _make_post(PostStatus.NEW, minutes_ago=1)

    rewritten: list[int] = []
    attempts: list[int] = []

    class FakeRewriter:
        async def rewrite(self, *args, **kwargs):
            rewritten.append(1)
            return RewriteResult(text="готовый текст", prompt_tokens=1,
                                 completion_tokens=1)

        async def complete(self, *args, **kwargs):
            return ""

    async def failing_dispatch() -> None:
        attempts.append(1)
        raise RuntimeError("Telegram недоступен")

    await jobs.rewrite_new_posts(FakeRewriter(), batch=3,
                                 after_each=failing_dispatch)

    invalidate_settings_cache()

    assert len(rewritten) == 3, (
        f"рерайт остановился на первом сбое отправки: сделано {len(rewritten)} из 3"
    )
    assert len(attempts) == 3


# --- 2. Возврат зависших постов ---


def test_stuck_rewriting_post_returns_to_the_queue():
    """ТОТ САМЫЙ СЛУЧАЙ: на стенде шесть постов висели в «рерайтится», самый
    старый 31 день. Никто их не возвращал."""
    stuck = _make_post(PostStatus.REWRITING,
                       minutes_ago=jobs.STUCK_REWRITING_MINUTES + 10)

    jobs._release_stuck_posts()

    with session_scope() as session:
        post = session.get(Post, stuck)
        assert post.status == PostStatus.NEW, "пост так и остался занятым навсегда"
        assert post.status_reason, "причина возврата не записана"


def test_recently_started_rewrite_is_left_alone():
    """Обратная проверка: пост, который рерайтится ПРЯМО СЕЙЧАС, трогать
    нельзя — иначе начнётся второй рерайт поверх идущего, и владелец получит
    два счёта за один пост."""
    fresh = _make_post(PostStatus.REWRITING, minutes_ago=1)

    jobs._release_stuck_posts()

    with session_scope() as session:
        assert session.get(Post, fresh).status == PostStatus.REWRITING


def test_release_touches_only_rewriting():
    """Посты в других состояниях возврат не задевает."""
    ids = {
        status: _make_post(status, minutes_ago=10_000)
        for status in (PostStatus.NEW, PostStatus.REWRITTEN,
                       PostStatus.PENDING_APPROVAL, PostStatus.POSTED)
    }

    jobs._release_stuck_posts()

    with session_scope() as session:
        for status, post_id in ids.items():
            assert session.get(Post, post_id).status == status, f"тронут {status}"


# --- 3. Затор виден ---


def test_state_reports_a_running_tick():
    pipeline_state.tick_started()
    pipeline_state.post_started(42)

    state = pipeline_state.current()

    assert state.running
    assert state.current_post_id == 42
    assert state.running_seconds is not None and state.running_seconds >= 0


def test_state_clears_after_the_tick():
    pipeline_state.tick_started()
    pipeline_state.post_started(42)

    pipeline_state.record_tick(12.5)
    state = pipeline_state.current()

    assert not state.running
    assert state.current_post_id is None
    assert state.last_duration_seconds == 12.5
    assert state.running_seconds is None


def test_dashboard_shows_the_stall(monkeypatch):
    """ДОСТИЖИМОСТЬ: сведения бесполезны, если их негде увидеть.

    Раньше единственным признаком затора было предупреждение APScheduler в
    логе — владелец в логи не смотрит, он смотрит на дашборд.
    """
    from tests.test_app_routes import _bootstrap, _client

    client = _client()
    _bootstrap(client)

    # Такт «идёт» уже полчаса.
    monkeypatch.setattr(
        pipeline_state, "current",
        lambda: pipeline_state.TickState(
            running=True,
            started_at=datetime.now(timezone.utc) - timedelta(minutes=30),
            current_post_id=777,
            last_duration_seconds=None,
            last_finished_at=None,
        ),
    )

    page = client.get("/")

    assert "777" in page.text, "на дашборде не видно, какой пост держит такт"
    assert "30" in page.text, "не видно, как давно идёт такт"


def test_dashboard_stays_quiet_when_the_tick_is_short(monkeypatch):
    """Обратная проверка: обычный быстрый такт не должен пугать владельца
    предупреждением на дашборде."""
    from tests.test_app_routes import _bootstrap, _client

    client = _client()
    _bootstrap(client)

    monkeypatch.setattr(
        pipeline_state, "current",
        lambda: pipeline_state.TickState(
            running=True,
            started_at=datetime.now(timezone.utc) - timedelta(seconds=5),
            current_post_id=1,
            last_duration_seconds=None,
            last_finished_at=None,
        ),
    )

    page = client.get("/")

    assert "Пайплайн занят дольше обычного" not in page.text
