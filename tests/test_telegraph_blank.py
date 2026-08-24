"""Затирание статьи Telegraph при удалении поста (по просьбе владельца).

ГЛАВНОЕ, ЧТО НАДО ЗНАТЬ: удалить страницу Telegraph НЕЛЬЗЯ. В его API есть
только `createPage` и `editPage` — метода удаления не существует ни для нас,
ни для владельца вручную. Поэтому «убрать материал» здесь означает заменить
текст заглушкой: адрес останется рабочим, содержимого по нему не будет.

Это НЕОБРАТИМО — прежний текст Telegraph не хранит. Отсюда два решения,
которые и проверяются ниже:

* по умолчанию выключено: удаление поста из канала и судьба статьи — разные
  решения владельца, связывать их молча нельзя;
* затираем, только когда поста не осталось НИ В ОДНОЙ цели: один пост уходит
  в несколько групп, а статья на них одна.
"""

from __future__ import annotations

import pytest

from tg_repost import moderation
from tg_repost.config import invalidate_settings_cache
from tg_repost.db.models import Post, PostKind, PostStatus, PostTarget
from tg_repost.db.session import session_scope
from tg_repost.telegraph.client import page_path

ARTICLE = "https://telegra.ph/Test-Article-08-23"


@pytest.fixture
def post_with_article():
    with session_scope() as session:
        session.query(PostTarget).delete()
        session.query(Post).delete()
        post = Post(kind=PostKind.SOURCE, original_text="текст",
                    status=PostStatus.POSTED, telegraph_url=ARTICLE)
        session.add(post)
        session.flush()
        post_id = post.id
    yield post_id
    with session_scope() as session:
        session.query(PostTarget).delete()
        session.query(Post).delete()


def _add_target(post_id: int, chat_id: int, message_id: int | None) -> int:
    with session_scope() as session:
        target = PostTarget(post_id=post_id, chat_id=chat_id,
                            message_id=message_id, ok=True)
        session.add(target)
        session.flush()
        return target.id


# --- разбор адреса ---


def test_page_path_is_taken_from_the_url():
    """`editPage` работает по пути, а не по полному адресу."""
    assert page_path(ARTICLE) == "Test-Article-08-23"
    assert page_path("https://telegra.ph/Test-08-23/") == "Test-08-23"


def test_broken_url_gives_none_instead_of_guessing():
    assert page_path("") is None
    assert page_path("   ") is None


# --- сама галочка ---


@pytest.mark.asyncio
async def test_article_is_left_alone_by_default(post_with_article, monkeypatch):
    """ПО УМОЛЧАНИЮ НЕ ТРОГАЕМ. Затирание необратимо, а владелец удалял пост,
    а не статью."""
    monkeypatch.delenv("TELEGRAPH_BLANK_ON_DELETE", raising=False)
    invalidate_settings_cache()
    called: list[str] = []
    monkeypatch.setattr("tg_repost.telegraph.client.blank_page",
                        lambda url, note: called.append(url))

    await moderation._blank_telegraph_if_asked(post_with_article)

    assert called == [], "статья затёрта без спроса"
    invalidate_settings_cache()


@pytest.mark.asyncio
async def test_article_is_blanked_when_the_checkbox_is_on(post_with_article,
                                                          monkeypatch):
    monkeypatch.setenv("TELEGRAPH_BLANK_ON_DELETE", "true")
    invalidate_settings_cache()
    called: list[tuple[str, str]] = []

    async def fake_blank(url: str, note: str) -> None:
        called.append((url, note))

    monkeypatch.setattr("tg_repost.telegraph.client.blank_page", fake_blank)

    await moderation._blank_telegraph_if_asked(post_with_article)

    assert len(called) == 1
    assert called[0][0] == ARTICLE
    assert called[0][1], "заглушка без текста — читателю непонятно, что случилось"
    invalidate_settings_cache()


@pytest.mark.asyncio
async def test_article_survives_while_the_post_lives_in_another_group(
    post_with_article, monkeypatch,
):
    """ГЛАВНАЯ ПРОВЕРКА. Пост уходит в несколько групп, а статья одна.

    Убрав пост из одной группы, владелец не собирался ломать ссылку в
    остальных — там пост по-прежнему висит и ведёт на эту статью.
    """
    monkeypatch.setenv("TELEGRAPH_BLANK_ON_DELETE", "true")
    invalidate_settings_cache()
    _add_target(post_with_article, -1001, None)      # отсюда удалили
    _add_target(post_with_article, -1002, 555)       # а здесь пост живой
    called: list[str] = []

    async def fake_blank(url: str, note: str) -> None:
        called.append(url)

    monkeypatch.setattr("tg_repost.telegraph.client.blank_page", fake_blank)

    await moderation._blank_telegraph_if_asked(post_with_article)

    assert called == [], (
        "статья затёрта, хотя пост ещё опубликован в другой группе"
    )
    invalidate_settings_cache()


@pytest.mark.asyncio
async def test_article_is_blanked_after_the_last_group(post_with_article,
                                                       monkeypatch):
    """Обратная проверка: когда нигде не осталось — затираем."""
    monkeypatch.setenv("TELEGRAPH_BLANK_ON_DELETE", "true")
    invalidate_settings_cache()
    _add_target(post_with_article, -1001, None)
    _add_target(post_with_article, -1002, None)
    called: list[str] = []

    async def fake_blank(url: str, note: str) -> None:
        called.append(url)

    monkeypatch.setattr("tg_repost.telegraph.client.blank_page", fake_blank)

    await moderation._blank_telegraph_if_asked(post_with_article)

    assert called == [ARTICLE]
    invalidate_settings_cache()


@pytest.mark.asyncio
async def test_post_without_article_does_nothing(monkeypatch):
    monkeypatch.setenv("TELEGRAPH_BLANK_ON_DELETE", "true")
    invalidate_settings_cache()
    with session_scope() as session:
        session.query(Post).delete()
        post = Post(kind=PostKind.SOURCE, original_text="без статьи",
                    status=PostStatus.POSTED)
        session.add(post)
        session.flush()
        post_id = post.id

    called: list[str] = []

    async def fake_blank(url: str, note: str) -> None:
        called.append(url)

    monkeypatch.setattr("tg_repost.telegraph.client.blank_page", fake_blank)

    await moderation._blank_telegraph_if_asked(post_id)

    assert called == []
    with session_scope() as session:
        session.query(Post).delete()
    invalidate_settings_cache()


@pytest.mark.asyncio
async def test_telegraph_failure_does_not_break_deletion(post_with_article,
                                                         monkeypatch):
    """Сообщение УЖЕ удалено к этому моменту. Уронить удаление из-за того,
    что Telegraph не ответил, значило бы соврать владельцу, что пост на
    месте."""
    monkeypatch.setenv("TELEGRAPH_BLANK_ON_DELETE", "true")
    invalidate_settings_cache()

    async def failing(url: str, note: str) -> None:
        raise RuntimeError("Telegraph недоступен")

    monkeypatch.setattr("tg_repost.telegraph.client.blank_page", failing)

    await moderation._blank_telegraph_if_asked(post_with_article)  # не бросает

    invalidate_settings_cache()


def test_checkbox_is_on_the_settings_page():
    """Настройка, до которой нельзя дойти, не существует для владельца."""
    from tg_repost.webui.settings_store import SETTINGS_GROUPS

    names = {f.name for group in SETTINGS_GROUPS for f in group.fields}
    assert "telegraph_blank_on_delete" in names
