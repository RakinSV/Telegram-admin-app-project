"""Маркировка рекламы: пометка, erid и отчёт (F62).

Единственное место бэклога, где цена ошибки — штраф. Поэтому тесты не про
«строка собирается», а про два свойства, которые нельзя нарушить: пост без
erid НЕ УХОДИТ при включённой маркировке, и размещения без erid ВИДНЫ в
отчёте, а не спрятаны.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tg_repost import ad_marking
from tg_repost.ads import repo as ads_repo
from tg_repost.db.models import AdBrief, Post, PostKind, PostStatus, PostTarget, TargetGroup
from tg_repost.db.session import session_scope
from tg_repost.telegram.publisher import publish_post

ADVERTISER = "ООО «Ромашка»"
INN = "7701234567"
ERID = "2Vfnxabcdef"
TARGET_CHAT = -1009900


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(PostTarget).delete()
            session.query(Post).delete()
            session.query(AdBrief).delete()
            session.query(TargetGroup).delete()

    _wipe()
    # ЖИВАЯ ЦЕЛЬ ОБЯЗАТЕЛЬНА, иначе тесты этого файла беззубы: без активной
    # группы пост не публикуется вообще, и «не отправлено» оказывается
    # правдой при любом коде — в том числе при снятой защите. Поймано
    # диверсией: сломанная проверка erid не уронила ни одного теста.
    with session_scope() as session:
        session.add(TargetGroup(chat_id=TARGET_CHAT, title="Тест", is_active=True))
    yield
    _wipe()


@pytest.fixture
def _marking_on(monkeypatch):
    from tg_repost import config

    real = config.get_settings()

    def _fake():
        return SimpleNamespace(
            **{**real.model_dump(), "ad_marking_enabled": True},
        )

    for module in ("tg_repost.telegram.publisher", "tg_repost.webui.crud_routes"):
        monkeypatch.setattr(f"{module}.get_settings", _fake)
    return _fake


def _bot() -> AsyncMock:
    """Бот, чей `send_message` возвращает настоящий message_id.

    Голый AsyncMock отдаёт мок и там, и его пытаются записать в
    `post_targets.message_id` — падает уже SQLite, до всякой проверки.
    """
    bot = AsyncMock()
    bot.send_message.return_value = SimpleNamespace(message_id=555)
    return bot


def _brief(*, erid: str | None = ERID, name: str | None = ADVERTISER) -> int:
    brief = ads_repo.add_brief("Купите ромашки")
    ads_repo.set_marking(
        brief.id, advertiser_legal_name=name, advertiser_inn=INN, erid=erid,
    )
    return brief.id


def _ad_post(brief_id: int | None, *, status=PostStatus.APPROVED) -> int:
    with session_scope() as session:
        post = Post(
            kind=PostKind.AD,
            ad_brief_id=brief_id,
            original_text="Купите ромашки",
            rewritten_text="Ромашки хороши весной.",
            status=status,
        )
        session.add(post)
        session.flush()
        return post.id


# --- сама пометка ---


def test_label_contains_word_advertiser_and_erid():
    label = ad_marking.build_label(
        ad_marking.Marking(ADVERTISER, INN, ERID),
    )

    assert label.startswith("Реклама")
    assert ADVERTISER in label
    assert INN in label
    assert ERID in label


def test_label_without_inn_is_still_valid():
    """Рекламодателем бывает физлицо — ИНН в пометке не всегда есть."""
    marking = ad_marking.Marking(ADVERTISER, None, ERID)

    assert marking.is_complete is True
    assert "ИНН" not in ad_marking.build_label(marking)


def test_label_goes_to_the_beginning():
    """ГЛАВНОЕ РЕШЕНИЕ ФИЧИ.

    Telegram сворачивает длинный текст под «показать полностью». Пометка в
    конце формально есть, а фактически не видна — то есть не выполняет
    единственное, ради чего существует.
    """
    result = ad_marking.apply_label("Текст поста", ad_marking.Marking(ADVERTISER, INN, ERID))

    assert result.startswith("Реклама")
    assert result.endswith("Текст поста")


def test_label_is_not_duplicated_on_second_apply():
    marking = ad_marking.Marking(ADVERTISER, INN, ERID)
    once = ad_marking.apply_label("Текст поста", marking)

    twice = ad_marking.apply_label(once, marking)

    assert twice == once
    assert twice.count("Реклама") == 1


def test_marking_without_erid_is_incomplete():
    assert ad_marking.Marking(ADVERTISER, INN, None).is_complete is False
    assert ad_marking.Marking(ADVERTISER, INN, "   ").is_complete is False


def test_marking_without_advertiser_is_incomplete():
    assert ad_marking.Marking(None, INN, ERID).is_complete is False


def test_blank_fields_are_stored_as_none():
    """«Не заполнено» и «заполнено пустотой» должны выглядеть одинаково."""
    brief = ads_repo.add_brief("Текст")

    ads_repo.set_marking(brief.id, advertiser_legal_name="  ", advertiser_inn="", erid=" ")

    marking = ad_marking.marking_of(brief.id)
    assert marking is not None
    assert marking.erid is None
    assert marking.is_complete is False


# --- публикация ---


async def test_marked_ad_is_published_with_the_label(_marking_on):
    """Опорный тест: с полной маркировкой пост УХОДИТ, и пометка в нём есть.

    Без него «не отправлено» в соседних тестах ничего не доказывает.
    """
    post_id = _ad_post(_brief())
    bot = _bot()

    await publish_post(bot, post_id)

    assert bot.send_message.await_count == 1
    sent = bot.send_message.await_args.kwargs["text"]
    assert sent.startswith("Реклама")
    assert ERID in sent


async def test_ad_without_erid_is_not_published(_marking_on):
    """САМАЯ ВАЖНАЯ ЗАЩИТА ФИЧИ.

    Опубликовать с половиной маркировки хуже, чем не опубликовать: ушедший
    пост не отозвать, а штраф выписывают за факт размещения.
    """
    post_id = _ad_post(_brief(erid=None))
    bot = _bot()

    await publish_post(bot, post_id)

    assert bot.send_message.await_count == 0
    with session_scope() as session:
        post = session.get(Post, post_id)
        assert post.status == PostStatus.FAILED
        assert "erid" in (post.status_reason or "")


async def test_ad_without_brief_at_all_is_not_published(_marking_on):
    post_id = _ad_post(None)
    bot = _bot()

    await publish_post(bot, post_id)

    assert bot.send_message.await_count == 0


async def test_normal_post_is_not_marked(_marking_on):
    """Пометка только на рекламе. Обычный пост с ней стал бы ложью."""
    with session_scope() as session:
        post = Post(
            kind=PostKind.SOURCE, original_text="новость",
            rewritten_text="Обычная новость.", status=PostStatus.APPROVED,
        )
        session.add(post)
        session.flush()
        post_id = post.id
    bot = _bot()

    await publish_post(bot, post_id)

    assert "Реклама" not in bot.send_message.await_args.kwargs["text"]


async def test_failure_reason_names_the_problem():
    """«Не опубликовано» без причины владелец примет за сбой системы."""
    with session_scope() as session:
        post = Post(kind=PostKind.AD, original_text="x", status=PostStatus.APPROVED)
        session.add(post)
        session.flush()
        post.set_status(PostStatus.FAILED, reason="маркировка включена, но нет erid")
        assert "erid" in (post.status_reason or "")


async def test_marking_off_does_not_block_on_erid():
    """Выключатель обязан возвращать прежнее поведение полностью.

    Проверяем ПРИЧИНУ, а не статус: в тестовой базе нет целевых групп, и
    пост всё равно не публикуется — но по совсем другому поводу. Сравнение
    статусов тут дало бы тест, который проходит при любом коде.
    """
    post_id = _ad_post(_brief(erid=None))
    bot = _bot()

    await publish_post(bot, post_id)

    with session_scope() as session:
        assert "erid" not in (session.get(Post, post_id).status_reason or "")


# --- отчёт ---


def _posted_ad(brief_id: int | None) -> int:
    post_id = _ad_post(brief_id, status=PostStatus.APPROVED)
    with session_scope() as session:
        post = session.get(Post, post_id)
        post.set_status(PostStatus.POSTED)
        post.posted_at = datetime.now(timezone.utc)
    return post_id


def test_report_lists_published_ads():
    _posted_ad(_brief())

    rows = ad_marking.report()

    assert len(rows) == 1
    assert rows[0].erid == ERID
    assert rows[0].advertiser_legal_name == ADVERTISER


def test_report_keeps_unmarked_placements_visible():
    """ВТОРАЯ ВАЖНАЯ ЗАЩИТА.

    Отфильтровать размещения без erid значило бы показать красивый отчёт и
    спрятать ровно то, из-за чего приходят штрафы.
    """
    _posted_ad(_brief(erid=None))

    rows = ad_marking.report()

    assert len(rows) == 1
    assert rows[0].erid is None
    assert ad_marking.unmarked_count() == 1


def test_report_ignores_unpublished_and_non_ad_posts():
    _ad_post(_brief())  # рекламный, но ещё не опубликован
    with session_scope() as session:
        post = Post(kind=PostKind.SOURCE, original_text="обычный", status=PostStatus.POSTED)
        post.posted_at = datetime.now(timezone.utc)
        session.add(post)

    assert ad_marking.report() == []


def test_marking_is_copied_to_brief_on_accept():
    """Реквизиты копируются, а не читаются по ссылке.

    Заявку могут поправить позже, а в отчёт должно уйти то, что стояло в
    самом опубликованном посте.
    """
    from datetime import date

    from tg_repost import ad_requests_repo
    from tg_repost.db.models import AdRequest

    with session_scope() as session:
        session.query(AdRequest).delete()

    request_id = ad_requests_repo.create(
        chat_id=-100, advertiser="@romashka", brief_text="Купите ромашки",
        slot_date=date(2026, 9, 1),
    )
    with session_scope() as session:
        row = session.get(AdRequest, request_id)
        row.advertiser_legal_name = ADVERTISER
        row.advertiser_inn = INN

    brief_id = ad_requests_repo.accept(request_id)

    marking = ad_marking.marking_of(brief_id)
    assert marking is not None
    assert marking.advertiser_legal_name == ADVERTISER
    assert marking.advertiser_inn == INN
    with session_scope() as session:
        session.query(AdRequest).delete()
