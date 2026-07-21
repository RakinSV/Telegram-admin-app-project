"""Тесты перехода по ссылке внутри пайплайна рерайта (`rewrite_new_posts`).

Сама функция раньше не была покрыта ничем, хотя это ядро качества рерайта:
если текст статьи по ссылке не доехал до модели, рерайт неизбежно выглядит
как синонимайз короткого тизера — ровно та жалоба, из-за которой правился
выбор ссылки (см. `enrichment/link_content.py::extract_article_urls`).

Сеть не трогается: `fetch_link_content` подменяется, LLM — фейковый клиент.
"""

from __future__ import annotations

import pytest

from tg_repost.config import invalidate_settings_cache
from tg_repost.db.models import AppSetting, Post, PostKind, PostRewriteVariant, PostStatus
from tg_repost.db.session import session_scope
from tg_repost.enrichment.link_content import LinkContent
from tg_repost.rewriter.client import RewriteResult
from tg_repost.scheduler import jobs
from tg_repost.webui import settings_store


@pytest.fixture(autouse=True)
def _clean_posts_and_settings():
    def _wipe() -> None:
        with session_scope() as session:
            session.query(PostRewriteVariant).delete()
            session.query(Post).delete()
            session.query(AppSetting).filter(
                AppSetting.key.in_(("fetch_link_content_enabled", "rewrite_variant_count")),
            ).delete(synchronize_session=False)
        invalidate_settings_cache()

    _wipe()
    yield
    _wipe()


class _FakeRewriter:
    """Запоминает, с каким `link_content` его позвали."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def rewrite(self, post_text, prompt_name="default", link_content=""):
        self.calls.append({"post_text": post_text, "link_content": link_content})
        return RewriteResult(text=f"рерайт[{link_content[:20]}]", prompt_tokens=1, completion_tokens=1)


def _new_post(text: str) -> int:
    with session_scope() as session:
        post = Post(kind=PostKind.SOURCE, original_text=text, status=PostStatus.NEW)
        session.add(post)
        session.flush()
        return post.id


def _fetched(post_id: int) -> Post:
    with session_scope() as session:
        return session.get(Post, post_id)


@pytest.mark.asyncio
async def test_skips_channel_promo_link_and_fetches_the_article(monkeypatch):
    """Промо-ссылка канала первой строкой не должна уводить переход на
    страницу Telegram вместо статьи."""
    settings_store.save_setting("fetch_link_content_enabled", True, "bool")
    asked: list[str] = []

    async def _fake_fetch(url: str):
        asked.append(url)
        return LinkContent(url=url, title="T", text="ПОЛНЫЙ ТЕКСТ СТАТЬИ", image_url=None)

    monkeypatch.setattr(jobs, "fetch_link_content", _fake_fetch)
    rewriter = _FakeRewriter()
    post_id = _new_post("Подпишись https://t.me/ch\n\nНовость: https://example.com/article")

    await jobs.rewrite_new_posts(rewriter, batch=5)

    assert asked == ["https://example.com/article"]
    assert rewriter.calls[0]["link_content"] == "ПОЛНЫЙ ТЕКСТ СТАТЬИ"
    post = _fetched(post_id)
    assert post.status == PostStatus.REWRITTEN
    # Диагностика для модерации: что именно прочитано.
    assert post.link_source_url == "https://example.com/article"
    assert post.link_content_chars == len("ПОЛНЫЙ ТЕКСТ СТАТЬИ")


@pytest.mark.asyncio
async def test_falls_through_to_next_candidate_when_first_link_yields_nothing(monkeypatch):
    """Битая/пустая первая ссылка не должна означать «рерайт без статьи»:
    раньше кандидат был ровно один, второго шанса не было."""
    settings_store.save_setting("fetch_link_content_enabled", True, "bool")
    asked: list[str] = []

    async def _fake_fetch(url: str):
        asked.append(url)
        if "broken" in url:
            return None  # пейвол/таймаут/нет текста
        return LinkContent(url=url, title="T", text="ТЕКСТ ВТОРОЙ ССЫЛКИ", image_url=None)

    monkeypatch.setattr(jobs, "fetch_link_content", _fake_fetch)
    rewriter = _FakeRewriter()
    _new_post("https://broken.example.com/a затем https://good.example.com/b")

    await jobs.rewrite_new_posts(rewriter, batch=5)

    assert asked == ["https://broken.example.com/a", "https://good.example.com/b"]
    assert rewriter.calls[0]["link_content"] == "ТЕКСТ ВТОРОЙ ССЫЛКИ"


@pytest.mark.asyncio
async def test_rewrites_without_article_when_every_candidate_fails(monkeypatch):
    """Недоступность ссылок не должна ронять рерайт — работаем по посту."""
    settings_store.save_setting("fetch_link_content_enabled", True, "bool")

    async def _fake_fetch(url: str):
        return None

    monkeypatch.setattr(jobs, "fetch_link_content", _fake_fetch)
    rewriter = _FakeRewriter()
    post_id = _new_post("Новость: https://example.com/a")

    await jobs.rewrite_new_posts(rewriter, batch=5)

    assert rewriter.calls[0]["link_content"] == ""
    post = _fetched(post_id)
    assert post.status == PostStatus.REWRITTEN
    # 0, а не NULL: «пробовали и не смогли» — это ЗНАНИЕ, его и показываем
    # при модерации. NULL остаётся у постов, рерайченных до появления полей.
    assert post.link_content_chars == 0
    assert post.link_source_url is None


@pytest.mark.asyncio
async def test_no_network_calls_when_link_fetch_disabled(monkeypatch):
    settings_store.save_setting("fetch_link_content_enabled", False, "bool")
    asked: list[str] = []

    async def _fake_fetch(url: str):
        asked.append(url)
        return None

    monkeypatch.setattr(jobs, "fetch_link_content", _fake_fetch)
    rewriter = _FakeRewriter()
    _new_post("Новость: https://example.com/a")

    await jobs.rewrite_new_posts(rewriter, batch=5)

    assert asked == []
    assert rewriter.calls[0]["link_content"] == ""


@pytest.mark.asyncio
async def test_post_without_links_is_rewritten_from_its_own_text(monkeypatch):
    settings_store.save_setting("fetch_link_content_enabled", True, "bool")

    async def _fake_fetch(url: str):
        raise AssertionError("не должно вызываться: в посте нет ссылок")

    monkeypatch.setattr(jobs, "fetch_link_content", _fake_fetch)
    rewriter = _FakeRewriter()
    post_id = _new_post("Просто текст без ссылок")

    await jobs.rewrite_new_posts(rewriter, batch=5)

    assert rewriter.calls[0]["post_text"] == "Просто текст без ссылок"
    assert _fetched(post_id).status == PostStatus.REWRITTEN
