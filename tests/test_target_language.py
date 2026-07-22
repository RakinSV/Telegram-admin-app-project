"""Язык публикации выбирается у ЦЕЛЕВОЙ группы и определяет язык рерайта.

Один источник может кормить и русские, и англоязычные каналы, поэтому пост,
уходящий в разноязычные группы, требует по рерайту на каждый язык — одним
текстом их не обслужить. Здесь проверяется вся цепочка: настройка у цели →
инструкция в промпте → отдельный вариант на язык → подбор текста при
публикации в каждую группу.
"""

from __future__ import annotations

import pytest

from tg_repost import languages, targets_repo
from tg_repost.config import invalidate_settings_cache
from tg_repost.db.models import (
    AppSetting,
    Post,
    PostCoverVariant,
    PostKind,
    PostRewriteVariant,
    PostStatus,
    TargetGroup,
)
from tg_repost.db.session import session_scope
from tg_repost.rewriter.client import RewriteResult, build_rewrite_prompt
from tg_repost.scheduler import jobs
from tg_repost.telegram.publisher import resolve_target_languages_for_post
from tg_repost.webui import settings_store


@pytest.fixture(autouse=True)
def _clean():
    def _wipe() -> None:
        with session_scope() as s:
            s.query(PostCoverVariant).delete()
            s.query(PostRewriteVariant).delete()
            s.query(Post).delete()
            s.query(TargetGroup).delete()
            s.query(AppSetting).filter(
                AppSetting.key.in_((
                    "rewrite_variant_count", "fetch_link_content_enabled",
                    "enable_auto_cover", "cover_replace_source_media",
                )),
            ).delete(synchronize_session=False)
        invalidate_settings_cache()

    _wipe()
    settings_store.save_setting("fetch_link_content_enabled", False, "bool")
    settings_store.save_setting("enable_auto_cover", False, "bool")
    settings_store.save_setting("cover_replace_source_media", False, "bool")
    yield
    _wipe()


class _LanguageAwareRewriter:
    """Отвечает так, чтобы по тексту было видно, какой язык запросили."""

    def __init__(self) -> None:
        self.languages_seen: list[str | None] = []

    async def rewrite(self, post_text, prompt_name="default", link_content="", language=None):
        self.languages_seen.append(language)
        return RewriteResult(text=f"текст[{language}]", prompt_tokens=1, completion_tokens=1)


def _target(chat_id: int, language: str) -> int:
    target, _ = targets_repo.add_target(chat_id, f"Группа {chat_id}")
    targets_repo.set_language(target.id, language)
    return target.id


def _new_post() -> int:
    with session_scope() as s:
        post = Post(kind=PostKind.SOURCE, original_text="исходный текст", status=PostStatus.NEW)
        s.add(post)
        s.flush()
        return post.id


def _variants(post_id: int) -> list[tuple[str, str]]:
    with session_scope() as s:
        return [
            (v.language, v.text)
            for v in s.query(PostRewriteVariant)
            .filter(PostRewriteVariant.post_id == post_id)
            .order_by(PostRewriteVariant.variant_index)
            .all()
        ]


# --- справочник и промпт ---


def test_unknown_language_falls_back_to_default():
    """Цель могла быть заведена старой версией или значение поправили руками —
    публикация из-за этого падать не должна."""
    assert languages.normalize("klingon") == languages.DEFAULT_LANGUAGE
    assert languages.normalize(None) == languages.DEFAULT_LANGUAGE
    assert languages.normalize("EN") == "en"


def test_language_instruction_is_the_last_thing_in_the_prompt():
    """Получив материал на одном языке, модель по умолчанию отвечает на нём же:
    требование сменить язык должно быть последним, что она читает."""
    prompt = build_rewrite_prompt("default", "исходник", language="en")
    assert prompt.rstrip().endswith(languages.instruction("en"))
    assert "English" in prompt


def test_no_language_means_no_instruction_at_all():
    """Поведение до появления языка у целей: модель отвечает на языке
    исходника, а не получает лишнее указание."""
    prompt = build_rewrite_prompt("default", "исходник", language=None)
    assert "LANGUAGE:" not in prompt
    assert "ЯЗЫК ОТВЕТА:" not in prompt


# --- резолв языков по целям ---


def test_languages_come_from_the_target_groups():
    _target(-100, "ru")
    _target(-200, "en")
    post_id = _new_post()
    assert sorted(resolve_target_languages_for_post(post_id)) == ["en", "ru"]


def test_same_language_targets_need_only_one_rewrite():
    """Иначе за две русские группы платили бы как за две разные версии."""
    _target(-100, "ru")
    _target(-200, "ru")
    post_id = _new_post()
    assert resolve_target_languages_for_post(post_id) == ["ru"]


def test_no_targets_means_no_language_requirement():
    """Публиковать пока некуда — рерайт всё равно делается, без указания
    языка: цели могут появиться позже, а работа не должна пропадать."""
    assert resolve_target_languages_for_post(_new_post()) == []


# --- пайплайн ---


@pytest.mark.asyncio
async def test_rewrite_is_generated_once_per_target_language():
    _target(-100, "ru")
    _target(-200, "en")
    post_id = _new_post()
    rewriter = _LanguageAwareRewriter()

    await jobs.rewrite_new_posts(rewriter, batch=5)

    assert sorted(rewriter.languages_seen) == ["en", "ru"]
    assert sorted(_variants(post_id)) == [("en", "текст[en]"), ("ru", "текст[ru]")]


@pytest.mark.asyncio
async def test_variant_count_multiplies_by_language():
    """Два языка × два варианта = четыре текста, и каждый помечен своим языком."""
    settings_store.save_setting("rewrite_variant_count", 2, "int")
    _target(-100, "ru")
    _target(-200, "en")
    post_id = _new_post()

    await jobs.rewrite_new_posts(_LanguageAwareRewriter(), batch=5)

    variants = _variants(post_id)
    assert len(variants) == 4
    assert [lang for lang, _ in variants].count("ru") == 2
    assert [lang for lang, _ in variants].count("en") == 2


@pytest.mark.asyncio
async def test_single_language_setup_costs_the_same_as_before():
    """Регрессия по деньгам: у кого все группы на одном языке, число вызовов
    модели не должно вырасти от появления этой фичи."""
    _target(-100, "ru")
    _target(-200, "ru")
    post_id = _new_post()
    rewriter = _LanguageAwareRewriter()

    await jobs.rewrite_new_posts(rewriter, batch=5)

    assert len(rewriter.languages_seen) == 1
    assert len(_variants(post_id)) == 1


@pytest.mark.asyncio
async def test_primary_language_lands_in_the_post_text():
    """`Post.rewritten_text` — то, что видно на модерации первым; это должен
    быть текст первой по порядку целевой группы."""
    _target(-100, "en")
    _target(-200, "ru")
    post_id = _new_post()

    await jobs.rewrite_new_posts(_LanguageAwareRewriter(), batch=5)

    with session_scope() as s:
        assert s.get(Post, post_id).rewritten_text == "текст[en]"


# --- публикация ---


async def _publish_and_collect(post_id: int) -> dict[int, str]:
    """Опубликовать пост фейковым ботом и вернуть {chat_id: отправленный текст}."""
    from unittest.mock import AsyncMock

    from tg_repost.telegram.publisher import publish_post

    sent: dict[int, str] = {}

    async def _send_message(chat_id, text, **kwargs):
        sent[chat_id] = text
        return type("Msg", (), {"message_id": 1})()

    bot = AsyncMock()
    bot.send_message.side_effect = _send_message
    await publish_post(bot, post_id)
    return sent


@pytest.mark.asyncio
async def test_each_group_receives_the_text_in_its_own_language():
    """Главная проверка фичи: русская группа получает русский текст, а
    англоязычная — английский, из одного и того же поста."""
    _target(-100, "ru")
    _target(-200, "en")
    post_id = _new_post()
    await jobs.rewrite_new_posts(_LanguageAwareRewriter(), batch=5)

    with session_scope() as s:
        post = s.get(Post, post_id)
        post.set_status(PostStatus.PENDING_APPROVAL)
        post.set_status(PostStatus.APPROVED)

    sent = await _publish_and_collect(post_id)
    assert sent[-100] == "текст[ru]"
    assert sent[-200] == "текст[en]"


@pytest.mark.asyncio
async def test_owner_edit_wins_for_the_active_language():
    """Правка через ✏️ пишется в `Post.rewritten_text`, а не в строку варианта.
    Читать вариант значило бы опубликовать доправленную версию."""
    _target(-100, "ru")
    _target(-200, "en")
    post_id = _new_post()
    await jobs.rewrite_new_posts(_LanguageAwareRewriter(), batch=5)

    with session_scope() as s:
        post = s.get(Post, post_id)
        post.rewritten_text = "поправлено руками"
        post.set_status(PostStatus.PENDING_APPROVAL)
        post.set_status(PostStatus.APPROVED)

    sent = await _publish_and_collect(post_id)
    assert sent[-100] == "поправлено руками", "активный язык берёт правку владельца"
    assert sent[-200] == "текст[en]", "остальные языки — из своих вариантов"


@pytest.mark.asyncio
async def test_group_added_after_the_rewrite_still_gets_published():
    """Цель добавили уже после рерайта — варианта на её язык нет. Публикуем
    активным текстом: язык поправим ретраем, а молчание канала — нет."""
    _target(-100, "ru")
    post_id = _new_post()
    await jobs.rewrite_new_posts(_LanguageAwareRewriter(), batch=5)

    _target(-200, "en")  # появилась ПОСЛЕ рерайта
    with session_scope() as s:
        post = s.get(Post, post_id)
        post.set_status(PostStatus.PENDING_APPROVAL)
        post.set_status(PostStatus.APPROVED)

    sent = await _publish_and_collect(post_id)
    assert sent[-200] == "текст[ru]", "лучше опубликовать не на том языке, чем промолчать"
