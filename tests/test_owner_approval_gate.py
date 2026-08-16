"""Согласование поста владельцем (F72) — сквозной путь.

НАЙДЕНО АУДИТОМ 2026-08-16. Настройка «редактор одобрил → ждём владельца»
была включаема, описана в админке и покрыта тестами на уровне отдельных
функций — но не работала: цепочка была порвана в ДВУХ местах сразу.

1. `mark_approved` (единственное место, где выставляется флаг ожидания) не
   вызывался ниоткуда в боевом коде;
2. немедленная публикация (когда расписание выключено) флаг не проверяла —
   его смотрел только планировщик слотов.

Итог для владельца: он включал согласование, видел его в настройках и
продолжал считать, что редактор без него ничего не опубликует. Публиковалось
всё и сразу.

Тесты ниже идут по ПУТИ, а не по функциям: именно стык был сломан.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from tg_repost import moderation
from tg_repost.db.models import Post, PostKind, PostStatus
from tg_repost.db.session import session_scope
from tg_repost.webui import access
from tg_repost.webui import settings_store


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(Post).delete()

    _wipe()
    yield
    _wipe()
    settings_store.reset_setting("require_owner_approval")
    settings_store.invalidate_settings_cache()


@pytest.fixture
def _approval_required():
    settings_store.save_setting("require_owner_approval", True, "bool")
    settings_store.invalidate_settings_cache()
    yield
    settings_store.reset_setting("require_owner_approval")
    settings_store.invalidate_settings_cache()


def _post() -> int:
    with session_scope() as session:
        row = Post(
            kind=PostKind.SOURCE,
            original_text="текст",
            rewritten_text="текст",
            status=PostStatus.REWRITTEN,
        )
        session.add(row)
        session.flush()
        return row.id


async def test_editor_approval_waits_for_the_owner(_approval_required, monkeypatch):
    """ГЛАВНАЯ ПРОВЕРКА.

    Владелец включил согласование — значит редактор публиковать не может.

    Проверяется, что публикация даже НЕ НАЧАЛАСЬ. Раньше здесь стояло
    «бот ничего не отправил», и тест был беззубым: в тестовой базе нет
    активных целей, поэтому публикация всё равно ничего не слала — гарантию
    давала не калитка, а отсутствие целей. Поймано диверсией: при снятой
    проверке тест продолжал проходить.
    """
    published = AsyncMock()
    monkeypatch.setattr(moderation, "publish_post", published)
    post_id = _post()

    await moderation.approve_post(
        AsyncMock(), post_id, by_username="editor1", by_role=access.ROLE_EDITOR,
    )

    with session_scope() as session:
        row = session.get(Post, post_id)
        assert row.needs_owner_approval is True
    assert published.await_count == 0, "публикация пошла без владельца"


async def test_owner_approval_does_publish(monkeypatch):
    """Проверка самой проверки: без согласования публикация ДОЛЖНА идти.

    Иначе тест выше проходил бы и на коде, который не публикует никогда.
    """
    published = AsyncMock()
    monkeypatch.setattr(moderation, "publish_post", published)
    post_id = _post()

    await moderation.approve_post(
        AsyncMock(), post_id, by_username="owner", by_role=access.ROLE_OWNER,
    )

    assert published.await_count == 1


async def test_owner_approval_publishes_immediately(_approval_required):
    """Владельцу второе подтверждение не нужно — он и есть владелец."""
    post_id = _post()

    await moderation.approve_post(
        AsyncMock(), post_id, by_username="owner", by_role=access.ROLE_OWNER,
    )

    with session_scope() as session:
        assert session.get(Post, post_id).needs_owner_approval is False


async def test_without_the_setting_editor_publishes_as_before():
    """Выключено по умолчанию: навязывать согласование там, где владелец
    работает один, — церемония, которая только замедляет."""
    post_id = _post()

    await moderation.approve_post(
        AsyncMock(), post_id, by_username="editor1", by_role=access.ROLE_EDITOR,
    )

    with session_scope() as session:
        assert session.get(Post, post_id).needs_owner_approval is False


async def test_who_approved_is_recorded(_approval_required):
    """Без имени «ждёт владельца» не объясняет, чьё решение подтверждают."""
    post_id = _post()

    await moderation.approve_post(
        AsyncMock(), post_id, by_username="editor1", by_role=access.ROLE_EDITOR,
    )

    with session_scope() as session:
        assert session.get(Post, post_id).approved_by == "editor1"


async def test_awaiting_post_appears_in_the_calendar(_approval_required):
    from tg_repost import calendar_repo

    post_id = _post()
    await moderation.approve_post(
        AsyncMock(), post_id, by_username="editor1", by_role=access.ROLE_EDITOR,
    )

    awaiting = calendar_repo.posts_awaiting_owner()

    assert [p.post_id for p in awaiting] == [post_id]


async def test_owner_confirmation_releases_the_post(_approval_required):
    from tg_repost import calendar_repo

    post_id = _post()
    await moderation.approve_post(
        AsyncMock(), post_id, by_username="editor1", by_role=access.ROLE_EDITOR,
    )

    assert calendar_repo.approve_by_owner(post_id) is True
    with session_scope() as session:
        assert session.get(Post, post_id).needs_owner_approval is False
