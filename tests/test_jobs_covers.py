"""Обложки в пайплайне: своя картинка поста больше не отменяет генерацию.

Жалоба: «картинки оригинальные в модерацию прилетают, а не то что мы ставили
генерировать». Причина была в `rewrite_new_posts`: при непустом `media_path`
генерация не запускалась вообще, и на модерацию уходила чужая картинка —
как правило с текстом и watermark'ами, то есть ровно то, чего мы в обложках
избегаем.

Ни сети, ни генератора: `generate_cover` подменяется, LLM — фейковый.
"""

from __future__ import annotations

import pytest

from tg_repost.config import invalidate_settings_cache
from tg_repost.db.models import (
    AppSetting,
    Post,
    PostCoverVariant,
    PostKind,
    PostRewriteVariant,
    PostStatus,
)
from tg_repost.db.session import session_scope
from tg_repost.rewriter.client import RewriteResult
from tg_repost.scheduler import jobs
from tg_repost.webui import settings_store

_SETTING_KEYS = (
    "cover_replace_source_media", "cover_variant_count",
    "rewrite_variant_count", "fetch_link_content_enabled",
)


@pytest.fixture(autouse=True)
def _clean():
    def _wipe() -> None:
        with session_scope() as session:
            session.query(PostCoverVariant).delete()
            session.query(PostRewriteVariant).delete()
            session.query(Post).delete()
            session.query(AppSetting).filter(
                AppSetting.key.in_(_SETTING_KEYS),
            ).delete(synchronize_session=False)
        invalidate_settings_cache()

    _wipe()
    settings_store.save_setting("fetch_link_content_enabled", False, "bool")
    yield
    _wipe()


class _FakeRewriter:
    async def rewrite(self, post_text, prompt_name="default", link_content=""):
        return RewriteResult(text="рерайт", prompt_tokens=1, completion_tokens=1)


def _post_with_media(media_path: str | None) -> int:
    with session_scope() as session:
        post = Post(
            kind=PostKind.SOURCE, original_text="исходный текст",
            status=PostStatus.NEW, media_path=media_path,
        )
        session.add(post)
        session.flush()
        return post.id


def _covers(post_id: int) -> list[str]:
    with session_scope() as session:
        return [
            v.media_path
            for v in session.query(PostCoverVariant)
            .filter(PostCoverVariant.post_id == post_id)
            .order_by(PostCoverVariant.variant_index)
            .all()
        ]


def _media_path(post_id: int) -> str | None:
    with session_scope() as session:
        return session.get(Post, post_id).media_path


def _fake_generator(monkeypatch):
    calls = {"n": 0}

    async def _generate(rewriter, text):
        calls["n"] += 1
        return f"/media/сгенерировано-{calls['n']}.png"

    monkeypatch.setattr(jobs, "generate_cover", _generate)
    return calls


@pytest.mark.asyncio
async def test_cover_is_generated_even_when_post_has_its_own_image(monkeypatch):
    settings_store.save_setting("cover_replace_source_media", True, "bool")
    settings_store.save_setting("cover_variant_count", 1, "int")
    calls = _fake_generator(monkeypatch)
    post_id = _post_with_media("/media/оригинал.jpg")

    await jobs.rewrite_new_posts(_FakeRewriter(), batch=5)

    assert calls["n"] == 1, "при своей картинке генерация обязана запускаться"
    assert _media_path(post_id) == "/media/сгенерировано-1.png"


@pytest.mark.asyncio
async def test_original_image_survives_as_the_last_variant(monkeypatch):
    """Замена не значит потерю: к оригиналу можно вернуться кнопками ◀▶."""
    settings_store.save_setting("cover_replace_source_media", True, "bool")
    settings_store.save_setting("cover_variant_count", 2, "int")
    _fake_generator(monkeypatch)
    post_id = _post_with_media("/media/оригинал.jpg")

    await jobs.rewrite_new_posts(_FakeRewriter(), batch=5)

    covers = _covers(post_id)
    assert covers[-1] == "/media/оригинал.jpg"
    assert len(covers) == 3  # две сгенерированных + оригинал


@pytest.mark.asyncio
async def test_disabled_setting_keeps_the_old_behaviour(monkeypatch):
    """Выключено — прежнее поведение: своя картинка отменяет генерацию."""
    settings_store.save_setting("cover_replace_source_media", False, "bool")
    calls = _fake_generator(monkeypatch)
    post_id = _post_with_media("/media/оригинал.jpg")

    await jobs.rewrite_new_posts(_FakeRewriter(), batch=5)

    assert calls["n"] == 0
    assert _media_path(post_id) == "/media/оригинал.jpg"


@pytest.mark.asyncio
async def test_post_without_media_is_unaffected(monkeypatch):
    """Пост без картинки и раньше получал обложку — регрессию не вносим."""
    settings_store.save_setting("cover_replace_source_media", True, "bool")
    settings_store.save_setting("cover_variant_count", 1, "int")
    _fake_generator(monkeypatch)
    post_id = _post_with_media(None)

    await jobs.rewrite_new_posts(_FakeRewriter(), batch=5)

    assert _covers(post_id) == ["/media/сгенерировано-1.png"]


# --- пустой ответ модели ---


class _EmptyRewriter:
    """Модель, вернувшая пустоту: отказ или сбой на стороне провайдера."""

    def __init__(self, text: str = "   ") -> None:
        self.text = text
        self.calls = 0

    async def rewrite(self, post_text, prompt_name="default", link_content=""):
        self.calls += 1
        return RewriteResult(text=self.text, prompt_tokens=1, completion_tokens=0)


@pytest.mark.asyncio
async def test_empty_model_answer_is_not_accepted_as_a_rewrite(monkeypatch):
    """Найдено на аудите: пустой ответ проходил как валидный вариант — пост
    получал статус rewritten с текстом из пробелов, на модерации показывался
    оригинал (фолбэк в превью), и владелец одобрял пустоту."""
    settings_store.save_setting("cover_replace_source_media", False, "bool")
    _fake_generator(monkeypatch)
    post_id = _post_with_media(None)

    await jobs.rewrite_new_posts(_EmptyRewriter(), batch=5)

    with session_scope() as session:
        post = session.get(Post, post_id)
        assert post.status == PostStatus.FAILED
        assert not (post.rewritten_text or "").strip()
        assert "пуст" in (post.status_reason or "").lower()


@pytest.mark.asyncio
async def test_one_empty_variant_does_not_sink_the_whole_post(monkeypatch):
    """Пустой вариант отбрасывается, но если хоть один непустой есть — пост
    едет дальше (то же правило, что и для упавших вариантов)."""
    settings_store.save_setting("cover_replace_source_media", False, "bool")
    settings_store.save_setting("rewrite_variant_count", 2, "int")
    _fake_generator(monkeypatch)
    post_id = _post_with_media(None)

    class _Flaky:
        def __init__(self) -> None:
            self.n = 0

        async def rewrite(self, post_text, prompt_name="default", link_content=""):
            self.n += 1
            text = "" if self.n == 1 else "нормальный рерайт"
            return RewriteResult(text=text, prompt_tokens=1, completion_tokens=1)

    await jobs.rewrite_new_posts(_Flaky(), batch=5)

    with session_scope() as session:
        post = session.get(Post, post_id)
        assert post.status == PostStatus.REWRITTEN
        assert post.rewritten_text == "нормальный рерайт"
