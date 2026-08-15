"""Баги, найденные аудитом 2026-08-16, и их фиксация тестами.

Оба относятся к одному классу: код делал ровно то, что написано, но
побочный путь оставался неучтённым. Такие вещи не ловятся чтением — оба
воспроизведены на живой базе до того, как были исправлены.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tg_repost import ad_requests_repo
from tg_repost.ads import injector
from tg_repost.ads import repo as ads_repo
from tg_repost.db.models import (
    AdBrief,
    AdRequest,
    Post,
    PostKind,
    PostRewriteVariant,
    PostStatus,
    PostTarget,
    TargetGroup,
)
from tg_repost.db.session import session_scope
from tg_repost.telegram.publisher import publish_post

ADVERTISER = "ООО «Ромашка»"
ERID = "2Vfnxabcdef"


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(PostTarget).delete()
            session.query(PostRewriteVariant).delete()
            session.query(Post).delete()
            session.query(AdRequest).delete()
            session.query(AdBrief).delete()
            session.query(TargetGroup).delete()

    _wipe()
    yield
    _wipe()


# --- БАГ 1: бриф отменённой заявки продолжал жить ---


def test_deleting_accepted_request_disables_its_brief():
    """Реклама по отменённой сделке выходила как ни в чём не бывало.

    Инжектор (F21) берёт ЛЮБОЙ активный бриф и про заявки ничего не знает.
    """
    request_id = ad_requests_repo.create(
        chat_id=-100, advertiser="@x", brief_text="Купите ромашки",
        slot_date=date(2026, 9, 1),
    )
    ad_requests_repo.accept(request_id)

    assert ad_requests_repo.delete(request_id) is True

    with session_scope() as session:
        assert injector.select_next_ad_brief(session) is None


def test_brief_is_disabled_not_deleted():
    """Бриф мог уже сработать: на него ссылаются посты и отчётность ОРД."""
    request_id = ad_requests_repo.create(
        chat_id=-100, advertiser="@x", brief_text="Купите ромашки",
        slot_date=date(2026, 9, 1),
    )
    brief_id = ad_requests_repo.accept(request_id)

    ad_requests_repo.delete(request_id)

    brief = ads_repo.get_brief(brief_id)
    assert brief is not None
    assert brief.is_active is False


def test_deleting_new_request_touches_nothing():
    """У непринятой заявки брифа ещё нет — гасить нечего."""
    request_id = ad_requests_repo.create(
        chat_id=-100, advertiser="@x", brief_text="Купите ромашки",
        slot_date=date(2026, 9, 2),
    )

    assert ad_requests_repo.delete(request_id) is True
    assert ads_repo.list_briefs() == []


# --- БАГ 2: метки и пометка ставились только на активный язык ---


def _bot() -> AsyncMock:
    bot = AsyncMock()
    bot.send_message.return_value = SimpleNamespace(message_id=555)
    return bot


def _two_language_targets() -> None:
    with session_scope() as session:
        session.add(TargetGroup(chat_id=-1001, title="ru", is_active=True, language="ru"))
        session.add(TargetGroup(chat_id=-1002, title="en", is_active=True, language="en"))


def _post_with_variants(kind: PostKind, brief_id: int | None = None) -> int:
    with session_scope() as session:
        post = Post(
            kind=kind,
            ad_brief_id=brief_id,
            original_text="исходник",
            rewritten_text="Русский текст, ссылка https://example.com/a",
            status=PostStatus.APPROVED,
            active_rewrite_variant_index=0,
        )
        session.add(post)
        session.flush()
        session.add(PostRewriteVariant(
            post_id=post.id, variant_index=0, language="ru",
            text="Русский текст, ссылка https://example.com/a",
        ))
        session.add(PostRewriteVariant(
            post_id=post.id, variant_index=1, language="en",
            text="English text, link https://example.com/b",
        ))
        return post.id


@pytest.fixture
def _marking_on(monkeypatch):
    from tg_repost import config

    real = config.get_settings()
    monkeypatch.setattr(
        "tg_repost.telegram.publisher.get_settings",
        lambda: SimpleNamespace(**{**real.model_dump(), "ad_marking_enabled": True}),
    )


@pytest.fixture
def _utm_on(monkeypatch):
    from tg_repost import config

    real = config.get_settings()
    monkeypatch.setattr(
        "tg_repost.telegram.publisher.get_settings",
        lambda: SimpleNamespace(**{**real.model_dump(), "utm_enabled": True}),
    )


async def test_ad_label_reaches_every_language(_marking_on):
    """ГЛАВНЫЙ ИЗ ДВУХ БАГОВ.

    В группу с другим языком уходил текст ИЗ ВАРИАНТА, а пометку получал
    только активный текст. То есть при включённой маркировке реклама всё
    равно выходила немаркированной — ровно то, что F62 обязана исключить.
    """
    brief = ads_repo.add_brief("Купите ромашки")
    ads_repo.set_marking(
        brief.id, advertiser_legal_name=ADVERTISER, advertiser_inn=None, erid=ERID,
    )
    _two_language_targets()
    post_id = _post_with_variants(PostKind.AD, brief.id)
    bot = _bot()

    await publish_post(bot, post_id)

    sent = [call.kwargs["text"] for call in bot.send_message.await_args_list]
    assert len(sent) == 2
    assert all(t.startswith("Реклама") for t in sent), sent
    assert all(ERID in t for t in sent), sent


async def test_utm_reaches_every_language(_utm_on):
    """Тот же баг, другая цена: у неактивных языков терялась аналитика."""
    _two_language_targets()
    post_id = _post_with_variants(PostKind.SOURCE)
    bot = _bot()

    await publish_post(bot, post_id)

    sent = [call.kwargs["text"] for call in bot.send_message.await_args_list]
    assert len(sent) == 2
    assert all("utm_source" in t for t in sent), sent


async def test_language_variants_stay_different(_marking_on):
    """Оформление не должно превратить переводы в одинаковый текст."""
    brief = ads_repo.add_brief("Купите ромашки")
    ads_repo.set_marking(
        brief.id, advertiser_legal_name=ADVERTISER, advertiser_inn=None, erid=ERID,
    )
    _two_language_targets()
    post_id = _post_with_variants(PostKind.AD, brief.id)
    bot = _bot()

    await publish_post(bot, post_id)

    sent = [call.kwargs["text"] for call in bot.send_message.await_args_list]
    assert "Русский текст" in " ".join(sent)
    assert "English text" in " ".join(sent)
