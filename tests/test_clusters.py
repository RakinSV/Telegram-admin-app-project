"""Сюжеты: одна новость из нескольких источников (F51).

Две группы тестов:

1. **Регрессия дыры в RSS.** До F51 приём поста был скопирован в две ветки, и
   RSS-копия считала `content_hash`, но никогда его не сверяла — одна новость
   из пяти лент давала пять постов. Тест `test_rss_...` падает на том коде.
2. **Сборка сюжета.** Семантический повтор не выбрасывается, а цепляется к
   первому пришедшему посту как дополнительный источник.
"""

from __future__ import annotations

import pytest

from tg_repost import clusters_repo, ingest, sources_repo
from tg_repost.config import invalidate_settings_cache
from tg_repost.db.models import Post, PostKind, PostStatus, Source, StoryCluster
from tg_repost.db.session import session_scope
from tg_repost.rewriter.client import RewriteResult
from tg_repost.rss import poller as rss_poller
from tg_repost.rss.feed import parse_feed
from tg_repost.scheduler import jobs
from tg_repost.webui import settings_store


def _reset() -> None:
    """Общая на весь прогон in-memory БД (см. conftest) — состояние между
    тестами не сбрасывается само, а стоп-слова и посты тут текут особенно
    больно: чужое стоп-слово молча отфильтровывает наши новости."""
    settings_store.save_setting("filter_stop_words", "", "str")
    settings_store.save_setting("filter_required_words", "", "str")
    settings_store.save_setting("cluster_grace_minutes", 0, "int")
    invalidate_settings_cache()
    with session_scope() as s:
        # Порядок важен: Post ссылается и на Source, и на StoryCluster.
        s.query(Post).delete()
        s.query(StoryCluster).delete()
        s.query(Source).delete()


@pytest.fixture(autouse=True)
def _clean():
    _reset()
    yield
    _reset()

# Одна и та же новость, но в двух лентах у неё разные guid — как в жизни.
def _feed(guid: str, text: str = "Критическая уязвимость в libfoo") -> bytes:
    return f"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>Feed</title>
<item>
  <title>{text}</title>
  <link>https://example.com/{guid}</link>
  <guid>https://example.com/{guid}</guid>
  <description>Одинаковое описание инцидента.</description>
</item>
</channel></rss>""".encode()


def _posts() -> list[Post]:
    with session_scope() as s:
        return s.query(Post).all()


# --- регрессия: RSS обходил дедуп ---


@pytest.mark.asyncio
async def test_rss_same_news_from_two_feeds_is_not_queued_twice(monkeypatch):
    """Ядро проблемы: одна новость в разных лентах — один пост, а не два.

    `_known_guids` эту ситуацию не ловит: он сравнивает guid ВНУТРИ ленты, а
    здесь ленты разные. До F51 оба поста уходили в очередь и в рерайт.
    """
    settings_store.save_setting("rss_enabled", True, "bool")
    settings_store.save_setting("rss_first_poll_items", 10, "int")

    first, _ = sources_repo.add_rss_source("https://a.example/feed", "Лента А")
    second, _ = sources_repo.add_rss_source("https://b.example/feed", "Лента Б")

    async def _fake(url: str):
        # Разные guid — иначе тест проверял бы уже работавший guid-дедуп.
        return parse_feed(_feed("a-1") if "a.example" in url else _feed("b-1"))

    monkeypatch.setattr(rss_poller, "fetch_feed", _fake)

    created_a = await rss_poller.poll_one_source(first.id, "https://a.example/feed")
    created_b = await rss_poller.poll_one_source(second.id, "https://b.example/feed")

    assert created_a == 1, "первая лента должна дать пост"
    assert created_b == 0, "вторая лента принесла ту же новость — в очередь не берём"

    statuses = [p.status for p in _posts()]
    assert statuses.count(PostStatus.NEW) == 1
    assert statuses.count(PostStatus.DUPLICATE) == 1


@pytest.mark.asyncio
async def test_rss_stop_words_still_filter(monkeypatch):
    """Общий приём не должен растерять фильтр слов, который в RSS уже был."""
    settings_store.save_setting("rss_enabled", True, "bool")
    settings_store.save_setting("filter_stop_words", "казино", "str")
    source, _ = sources_repo.add_rss_source("https://c.example/feed", "Лента В")

    async def _fake(url: str):
        return parse_feed(_feed("c-1", "Реклама казино и ставок"))

    monkeypatch.setattr(rss_poller, "fetch_feed", _fake)
    created = await rss_poller.poll_one_source(source.id, "https://c.example/feed")

    assert created == 0
    assert [p.status for p in _posts()] == [PostStatus.FILTERED_OUT]


# --- сборка сюжета ---


def _ingest(text: str, embedding: list[float], link: str) -> ingest.IngestResult:
    with session_scope() as session:
        return ingest.ingest_post(
            session, source_id=None, text=text, source_link=link, embedding=embedding,
        )


def test_semantic_repeat_builds_cluster_instead_of_vanishing():
    """Повтор из другого источника — подтверждение, а не мусор."""
    first = _ingest("Ракета стартовала утром", [1.0, 0.0], "https://a/1")
    second = _ingest("Утром состоялся запуск ракеты", [1.0, 0.0], "https://b/1")

    assert first.queued
    assert not second.queued
    assert second.cluster_id is not None, "повтор должен быть привязан к сюжету"

    with session_scope() as s:
        cluster = s.get(StoryCluster, second.cluster_id)
        assert cluster is not None
        assert cluster.primary_post_id == first.post_id
        assert cluster.member_count == 2


def test_third_source_joins_the_same_cluster():
    """Сюжет растёт, а не плодит по кластеру на каждую пару."""
    first = _ingest("Землетрясение в Тихом океане", [0.0, 1.0], "https://a/2")
    second = _ingest("В Тихом океане произошло землетрясение", [0.0, 1.0], "https://b/2")
    third = _ingest("Подземные толчки в Тихом океане", [0.0, 1.0], "https://c/2")

    assert second.cluster_id == third.cluster_id
    with session_scope() as s:
        assert s.get(StoryCluster, second.cluster_id).member_count == 3
        assert s.get(Post, first.post_id).cluster_id == second.cluster_id


def test_unrelated_news_does_not_join_cluster():
    """Порог должен разделять сюжеты, иначе всё склеится в один ком."""
    first = _ingest("Курс валют вырос", [1.0, 0.0], "https://a/3")
    other = _ingest("Открылся новый мост", [0.0, 1.0], "https://b/3")

    assert first.queued and other.queued
    assert other.cluster_id is None


def test_exact_copypaste_is_dropped_not_clustered():
    """Буквальный копипаст — не независимое подтверждение, а тот же текст.

    Считать его «вторым источником» значило бы врать редактору-фактчекеру о
    количестве подтверждений.
    """
    text = "Дословно одинаковый текст новости"
    first = _ingest(text, [1.0, 0.0], "https://a/4")
    copy = _ingest(text, [1.0, 0.0], "https://b/4")

    assert first.queued
    assert not copy.queued
    assert copy.cluster_id is None
    assert copy.reason == "точный дубль по хэшу"


def test_sources_for_returns_other_members_only():
    """Рерайту отдаём ДРУГИЕ источники: свой текст редакции уже известен."""
    first = _ingest("Компания отчиталась о прибыли", [1.0, 1.0], "https://a/5")
    second = _ingest("Отчёт компании показал прибыль", [1.0, 1.0], "https://b/5")

    sources = clusters_repo.sources_for(second.cluster_id, exclude_post_id=first.post_id)

    assert [s.post_id for s in sources] == [second.post_id]
    assert sources[0].link == "https://b/5"
    assert "прибыль" in sources[0].text


def test_size_of_without_cluster_is_zero():
    """Новость пришла из одного места — сюжета нет, и это норма, не ошибка."""
    assert clusters_repo.size_of(None) == 0


# --- блок источников для промпта ---


def test_sources_block_is_empty_without_cluster():
    """Пустая строка, а не заголовок без содержимого: иначе редактор увидел бы
    «Другие источники» и ни одного источника под ним."""
    assert clusters_repo.build_sources_block(None) == ""


def test_sources_block_lists_other_sources_with_links():
    first = _ingest("Банк поднял ставку", [1.0, 0.5], "https://a/6")
    second = _ingest("Ставка банка повышена", [1.0, 0.5], "https://b/6")

    block = clusters_repo.build_sources_block(
        second.cluster_id, exclude_post_id=first.post_id
    )

    assert "Другие источники" in block
    assert "https://b/6" in block
    assert "Ставка банка повышена" in block


def test_sources_block_is_capped():
    """Сюжет из десяти лент раздул бы промпт и счёт за токены, а пользы после
    третьего пересказа того же события почти нет."""
    ids = [_ingest(f"Событие, версия {i}", [1.0, 0.25], f"https://s{i}/7") for i in range(7)]
    block = clusters_repo.build_sources_block(ids[-1].cluster_id)

    # Каждый источник начинается с маркера «[N]» на новой строке.
    assert block.count("\n[") == clusters_repo.MAX_SOURCES_IN_PROMPT
    assert "[5]" not in block


# --- пауза на сбор сюжета ---


class _FakeRewriter:
    async def rewrite(self, *args, **kwargs):
        return RewriteResult(text="рерайт", prompt_tokens=1, completion_tokens=1)


def _plain_post(text: str) -> int:
    with session_scope() as session:
        post = Post(kind=PostKind.SOURCE, original_text=text, status=PostStatus.NEW)
        session.add(post)
        session.flush()
        return post.id


def _status(post_id: int) -> PostStatus:
    with session_scope() as session:
        return session.get(Post, post_id).status


@pytest.mark.asyncio
async def test_grace_period_holds_a_fresh_post():
    """Смысл паузы: не хватать пост раньше, чем подтянутся другие источники."""
    settings_store.save_setting("cluster_grace_minutes", 10, "int")
    invalidate_settings_cache()
    post_id = _plain_post("Только что пришедшая новость")

    await jobs.rewrite_new_posts(_FakeRewriter(), batch=5)

    assert _status(post_id) == PostStatus.NEW, "свежий пост не должен уйти в рерайт"


@pytest.mark.asyncio
async def test_without_grace_post_is_taken_immediately():
    """Ноль — это именно «без ожидания», а не «ждать вечно»."""
    settings_store.save_setting("cluster_grace_minutes", 0, "int")
    invalidate_settings_cache()
    post_id = _plain_post("Новость, которую можно брать сразу")

    await jobs.rewrite_new_posts(_FakeRewriter(), batch=5)

    assert _status(post_id) != PostStatus.NEW
