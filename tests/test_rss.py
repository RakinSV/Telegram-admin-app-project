"""Тесты RSS как входящего источника: разбор ленты, дедупликация, защита
очереди при первом опросе. Без сети — `fetch_feed` подменяется.
"""

from __future__ import annotations

import pytest

from tg_repost import sources_repo
from tg_repost.config import invalidate_settings_cache
from tg_repost.db.models import AppSetting, Post, PostStatus, Source
from tg_repost.db.session import session_scope
from tg_repost.rss import poller as rss_poller
from tg_repost.rss import presets
from tg_repost.rss.feed import FeedItem, parse_feed, strip_html
from tg_repost.webui import settings_store

RSS_SAMPLE = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>Feed</title>
<item>
  <title>CVE-2026-0001 in libfoo</title>
  <link>https://example.com/cve-1</link>
  <guid>https://example.com/cve-1</guid>
  <description>&lt;p&gt;Heap overflow in &lt;b&gt;libfoo&lt;/b&gt;.&lt;/p&gt;</description>
</item>
<item>
  <title>Second advisory</title>
  <link>https://example.com/cve-2</link>
  <guid>tag:example.com,2026:2</guid>
  <description>Second one.</description>
</item>
</channel></rss>"""

ATOM_SAMPLE = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom feed</title>
  <entry>
    <title>Atom entry</title>
    <link href="https://example.com/atom-1"/>
    <id>urn:uuid:1</id>
    <content type="html">&lt;p&gt;Body from content.&lt;/p&gt;</content>
  </entry>
</feed>"""


@pytest.fixture(autouse=True)
def _clean():
    def _wipe() -> None:
        with session_scope() as s:
            s.query(Post).delete()
            s.query(Source).delete()
            s.query(AppSetting).filter(
                AppSetting.key.in_((
                    "rss_enabled", "rss_max_items_per_poll", "rss_first_poll_items",
                    "filter_stop_words",
                )),
            ).delete(synchronize_session=False)
        invalidate_settings_cache()

    _wipe()
    yield
    _wipe()


# --- разбор ---


def test_parse_rss_extracts_items():
    items = parse_feed(RSS_SAMPLE)
    assert [i.title for i in items] == ["CVE-2026-0001 in libfoo", "Second advisory"]
    assert items[0].link == "https://example.com/cve-1"
    assert "Heap overflow in libfoo" in items[0].summary


def test_parse_atom_reads_content_when_summary_absent():
    items = parse_feed(ATOM_SAMPLE)
    assert len(items) == 1
    assert items[0].summary == "Body from content."
    assert items[0].guid == "urn:uuid:1"


def test_guid_prefers_id_over_link():
    """guid — ключ дедупликации. У второй записи id отличается от ссылки, и
    брать надо именно его: ссылка может смениться при переезде статьи."""
    items = parse_feed(RSS_SAMPLE)
    assert items[1].guid == "tag:example.com,2026:2"


def test_strip_html_removes_tags_and_unescapes():
    assert strip_html("<p>a &amp; b</p><script>bad()</script>") == "a & b"


def test_parse_garbage_yields_no_items_instead_of_raising():
    assert parse_feed(b"not xml at all") == []


def test_post_text_puts_link_last_so_pipeline_can_fetch_article():
    """Ссылка в тексте — не украшение: её подхватит extract_article_urls, и
    рерайт пойдёт по ПОЛНОЙ статье, а не по куцему описанию из ленты."""
    from tg_repost.enrichment.link_content import extract_article_urls

    item = FeedItem("g", "Заголовок", "Описание", "https://example.com/full")
    text = item.as_post_text()
    assert text.startswith("Заголовок")
    assert extract_article_urls(text) == ["https://example.com/full"]


# --- опрос ---


def _add_feed(url="https://example.com/feed"):
    source, _ = sources_repo.add_rss_source(url, "Тестовая лента")
    return source.id


def _posts():
    with session_scope() as s:
        return s.query(Post).all()


@pytest.mark.asyncio
async def test_poll_creates_posts_from_feed(monkeypatch):
    settings_store.save_setting("rss_enabled", True, "bool")
    settings_store.save_setting("rss_first_poll_items", 10, "int")
    _add_feed()

    async def _fake(url):
        return parse_feed(RSS_SAMPLE)

    monkeypatch.setattr(rss_poller, "fetch_feed", _fake)
    created = await rss_poller.poll_rss_sources()

    assert created == 2
    texts = [p.original_text for p in _posts()]
    assert any("CVE-2026-0001" in t for t in texts)
    assert all(p.status == PostStatus.NEW for p in _posts())


@pytest.mark.asyncio
async def test_second_poll_does_not_duplicate_known_entries(monkeypatch):
    settings_store.save_setting("rss_enabled", True, "bool")
    settings_store.save_setting("rss_first_poll_items", 10, "int")
    _add_feed()

    async def _fake(url):
        return parse_feed(RSS_SAMPLE)

    monkeypatch.setattr(rss_poller, "fetch_feed", _fake)
    await rss_poller.poll_rss_sources()
    created_again = await rss_poller.poll_rss_sources()

    assert created_again == 0
    assert len(_posts()) == 2


@pytest.mark.asyncio
async def test_first_poll_takes_only_recent_items_not_whole_archive(monkeypatch):
    """Ключевая защита: в архиве ленты бывают тысячи записей, и завести их
    все постами значит забить очередь модерации и счёт за рерайт."""
    settings_store.save_setting("rss_enabled", True, "bool")
    settings_store.save_setting("rss_first_poll_items", 3, "int")
    _add_feed()

    async def _fake(url):
        return [
            FeedItem(f"guid-{i}", f"Запись {i}", "текст", f"https://example.com/{i}")
            for i in range(500)
        ]

    monkeypatch.setattr(rss_poller, "fetch_feed", _fake)
    created = await rss_poller.poll_rss_sources()

    assert created == 3, "первый опрос обязан ограничиться свежими записями"


@pytest.mark.asyncio
async def test_subsequent_polls_use_max_items_per_poll(monkeypatch):
    settings_store.save_setting("rss_enabled", True, "bool")
    settings_store.save_setting("rss_first_poll_items", 1, "int")
    settings_store.save_setting("rss_max_items_per_poll", 2, "int")
    _add_feed()

    batch = [
        FeedItem(f"g{i}", f"Запись {i}", "текст", f"https://example.com/{i}")
        for i in range(10)
    ]

    async def _fake(url):
        return batch

    monkeypatch.setattr(rss_poller, "fetch_feed", _fake)
    assert await rss_poller.poll_rss_sources() == 1   # первый опрос
    assert await rss_poller.poll_rss_sources() == 2   # дальше — обычный потолок


@pytest.mark.asyncio
async def test_stop_words_filter_applies_to_rss_too(monkeypatch):
    """RSS идёт по тому же пути, что и Telegram-посты, — включая фильтры."""
    settings_store.save_setting("rss_enabled", True, "bool")
    settings_store.save_setting("rss_first_poll_items", 10, "int")
    settings_store.save_setting("filter_stop_words", ["libfoo"], "csv_list")
    _add_feed()

    async def _fake(url):
        return parse_feed(RSS_SAMPLE)

    monkeypatch.setattr(rss_poller, "fetch_feed", _fake)
    created = await rss_poller.poll_rss_sources()

    assert created == 1  # вторая запись прошла, первая отсеяна
    statuses = {p.status for p in _posts()}
    assert PostStatus.FILTERED_OUT in statuses


@pytest.mark.asyncio
async def test_disabled_polling_does_nothing(monkeypatch):
    settings_store.save_setting("rss_enabled", False, "bool")
    _add_feed()

    async def _fake(url):
        raise AssertionError("опрос выключен — сети быть не должно")

    monkeypatch.setattr(rss_poller, "fetch_feed", _fake)
    assert await rss_poller.poll_rss_sources() == 0


@pytest.mark.asyncio
async def test_unreachable_feed_does_not_break_the_others(monkeypatch):
    settings_store.save_setting("rss_enabled", True, "bool")
    settings_store.save_setting("rss_first_poll_items", 10, "int")
    _add_feed("https://dead.example.com/feed")
    _add_feed("https://live.example.com/feed")

    async def _fake(url):
        return [] if "dead" in url else parse_feed(RSS_SAMPLE)

    monkeypatch.setattr(rss_poller, "fetch_feed", _fake)
    assert await rss_poller.poll_rss_sources() == 2


# --- источники ---


def test_add_rss_source_is_idempotent():
    first, created1 = sources_repo.add_rss_source("https://example.com/feed", "Лента")
    second, created2 = sources_repo.add_rss_source("https://example.com/feed")
    assert created1 is True
    assert created2 is False
    assert first.id == second.id


def test_add_rss_source_rejects_non_http_url():
    with pytest.raises(ValueError):
        sources_repo.add_rss_source("example.com/feed")


def test_rss_source_marked_with_kind():
    source, _ = sources_repo.add_rss_source("https://example.com/feed")
    assert source.kind == "rss"


# --- наборы лент ---


def test_presets_are_non_empty_and_use_https():
    feeds = presets.all_presets()
    assert len(feeds) >= 25
    assert all(f.url.startswith("https://") for f in feeds)
    assert all(f.title.strip() for f in feeds)


def test_preset_urls_are_unique():
    """Дубль внутри наборов не сломает БД (add_rss_source идемпотентен), но
    завышает счётчик на кнопке и путает."""
    urls = [f.url for f in presets.all_presets()]
    assert len(urls) == len(set(urls))
