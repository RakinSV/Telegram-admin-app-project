"""Атрибуция подписчиков (F41): откуда пришёл участник и остался ли.

Главное, что проверяем: данные, которые Telegram и так присылает в апдейтах
(`invite_link`), реально сохраняются и превращаются в статистику кампании —
пришло / осталось / retention / цена подписчика.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tg_repost import invites_repo, member_origins_repo
from tg_repost.db.models import InviteLink, MemberOrigin
from tg_repost.db.session import session_scope

CHAT = -100777


@pytest.fixture(autouse=True)
def _clean_tables():
    with session_scope() as session:
        session.query(MemberOrigin).delete()
        session.query(InviteLink).delete()
    yield
    with session_scope() as session:
        session.query(MemberOrigin).delete()
        session.query(InviteLink).delete()


def _backdate(user_id: int, days: int, left_after_days: float | None = None) -> None:
    """Сдвинуть вступление в прошлое — иначе retention нечего считать."""
    joined = datetime.now(timezone.utc) - timedelta(days=days)
    with session_scope() as session:
        row = (
            session.query(MemberOrigin)
            .filter(MemberOrigin.chat_id == CHAT, MemberOrigin.user_id == user_id)
            .one()
        )
        row.joined_at = joined
        if left_after_days is not None:
            row.left_at = joined + timedelta(days=left_after_days)


# --- запись вступлений/уходов ---


def test_join_with_link_is_attributed():
    member_origins_repo.record_join(CHAT, 1, invite_link="https://t.me/+abc", invite_name="Реклама A")
    stats = member_origins_repo.origin_stats(CHAT)
    assert len(stats) == 1
    assert stats[0].invite_link == "https://t.me/+abc"
    assert stats[0].invite_name == "Реклама A"
    assert stats[0].joined == 1
    assert stats[0].still_here == 1


def test_join_without_link_is_grouped_separately():
    """Пришёл сам (поиск/добавил админ) — это не кампания, но учитывать надо."""
    member_origins_repo.record_join(CHAT, 1, invite_link=None)
    stats = member_origins_repo.origin_stats(CHAT)
    assert stats[0].invite_link is None
    assert stats[0].joined == 1


def test_leave_moves_member_out_of_still_here():
    member_origins_repo.record_join(CHAT, 1, invite_link="https://t.me/+abc")
    assert member_origins_repo.record_leave(CHAT, 1) is True
    stats = member_origins_repo.origin_stats(CHAT)
    assert stats[0].still_here == 0
    assert stats[0].left == 1


def test_leave_of_unknown_member_is_noop():
    """Про вступивших до F41 мы ничего не знаем — не выдумываем запись задним
    числом, иначе исказим статистику ссылок."""
    assert member_origins_repo.record_leave(CHAT, 999) is False
    assert member_origins_repo.origin_stats(CHAT) == []


def test_rejoin_overwrites_source_and_clears_left():
    member_origins_repo.record_join(CHAT, 1, invite_link="https://t.me/+old", invite_name="Старая")
    member_origins_repo.record_leave(CHAT, 1)
    member_origins_repo.record_join(CHAT, 1, invite_link="https://t.me/+new", invite_name="Новая")

    stats = member_origins_repo.origin_stats(CHAT)
    assert len(stats) == 1  # одна строка на участника, а не история метаний
    assert stats[0].invite_link == "https://t.me/+new"
    assert stats[0].still_here == 1
    assert stats[0].left == 0


def test_stats_are_scoped_per_chat():
    member_origins_repo.record_join(CHAT, 1, invite_link="https://t.me/+abc")
    member_origins_repo.record_join(-100888, 2, invite_link="https://t.me/+abc")
    assert member_origins_repo.origin_stats(CHAT)[0].joined == 1
    assert member_origins_repo.origin_stats()[0].joined == 2  # без фильтра — все чаты


# --- retention ---


def test_retention_ignores_members_too_fresh_to_judge():
    """Вступивший час назад физически не мог «прожить неделю» — учитывать его
    в retention_7d значит занижать её."""
    member_origins_repo.record_join(CHAT, 1, invite_link="https://t.me/+abc")
    assert member_origins_repo.origin_stats(CHAT)[0].retention_7d is None


def test_retention_counts_survivors_among_mature_joins():
    member_origins_repo.record_join(CHAT, 1, invite_link="https://t.me/+abc")
    member_origins_repo.record_join(CHAT, 2, invite_link="https://t.me/+abc")
    member_origins_repo.record_join(CHAT, 3, invite_link="https://t.me/+abc")
    _backdate(1, days=30)                       # жив
    _backdate(2, days=30, left_after_days=20)   # ушёл, но прожил > 7 дней
    _backdate(3, days=30, left_after_days=2)    # ушёл на второй день

    stats = member_origins_repo.origin_stats(CHAT)[0]
    assert stats.retention_7d == pytest.approx(2 / 3, abs=0.01)
    assert stats.retention_30d == pytest.approx(1 / 3, abs=0.01)


# --- цена подписчика ---


def test_cpa_counts_by_remaining_not_by_joined():
    """Платить за того, кто вступил и сразу вышел, смысла нет — CPA считается
    по оставшимся."""
    invites_repo.record_invite_link(CHAT, "https://t.me/+abc", "Реклама A", None, False)
    link = invites_repo.list_invite_links(CHAT)[0]
    invites_repo.set_link_cost(link.id, 1000.0, "RUB")

    for user_id in (1, 2, 3, 4):
        member_origins_repo.record_join(CHAT, user_id, invite_link="https://t.me/+abc")
    member_origins_repo.record_leave(CHAT, 4)

    stats = member_origins_repo.origin_stats(CHAT)[0]
    assert stats.joined == 4
    assert stats.still_here == 3
    assert stats.cpa == pytest.approx(1000 / 3, abs=0.01)


def test_cpa_is_none_without_cost():
    member_origins_repo.record_join(CHAT, 1, invite_link="https://t.me/+abc")
    assert member_origins_repo.origin_stats(CHAT)[0].cpa is None


def test_cpa_is_none_when_everyone_left():
    """Делить на ноль оставшихся нельзя — показываем прочерк, а не ошибку."""
    invites_repo.record_invite_link(CHAT, "https://t.me/+abc", "A", None, False)
    link = invites_repo.list_invite_links(CHAT)[0]
    invites_repo.set_link_cost(link.id, 500.0)
    member_origins_repo.record_join(CHAT, 1, invite_link="https://t.me/+abc")
    member_origins_repo.record_leave(CHAT, 1)
    assert member_origins_repo.origin_stats(CHAT)[0].cpa is None


def test_set_cost_none_clears_it():
    """Размещение по бартеру: цены нет, и CPA=0 было бы враньём."""
    invites_repo.record_invite_link(CHAT, "https://t.me/+abc", None, None, False)
    link = invites_repo.list_invite_links(CHAT)[0]
    invites_repo.set_link_cost(link.id, 700.0)
    invites_repo.set_link_cost(link.id, None)
    member_origins_repo.record_join(CHAT, 1, invite_link="https://t.me/+abc")
    assert member_origins_repo.origin_stats(CHAT)[0].cpa is None


def test_direct_joins_sort_last():
    """«Без ссылки» — не кампания, ей не место в начале отчёта."""
    member_origins_repo.record_join(CHAT, 1, invite_link=None)
    member_origins_repo.record_join(CHAT, 2, invite_link=None)
    member_origins_repo.record_join(CHAT, 3, invite_link="https://t.me/+abc")
    stats = member_origins_repo.origin_stats(CHAT)
    assert stats[0].invite_link == "https://t.me/+abc"
    assert stats[-1].invite_link is None


# --- хендлер chat_member: именно здесь Telegram отдаёт invite_link ---


async def test_chat_member_handler_records_join_with_link():
    from tests.aiogram_fakes import fake_membership
    from tg_repost.telegram.moderation_bot import _on_chat_member

    await _on_chat_member(fake_membership(
        chat_id=CHAT, chat_type="supergroup", user_id=42,
        old_status="left", new_status="member",
        invite_link="https://t.me/+camp",
    ))

    stats = member_origins_repo.origin_stats(CHAT)
    assert stats[0].invite_link == "https://t.me/+camp"
    assert stats[0].invite_name == "кампания"
    assert stats[0].still_here == 1


async def test_chat_member_handler_records_leave():
    from tests.aiogram_fakes import fake_membership
    from tg_repost.telegram.moderation_bot import _on_chat_member

    member_origins_repo.record_join(CHAT, 42, invite_link="https://t.me/+camp")

    await _on_chat_member(fake_membership(
        chat_id=CHAT, chat_type="supergroup", user_id=42,
        old_status="member", new_status="left",
    ))

    assert member_origins_repo.origin_stats(CHAT)[0].still_here == 0


async def test_chat_member_handler_ignores_role_change_inside_chat():
    """Выдали админку участнику — он никуда не приходил и не уходил."""
    from tests.aiogram_fakes import fake_membership
    from tg_repost.telegram.moderation_bot import _on_chat_member

    await _on_chat_member(fake_membership(
        chat_id=CHAT, chat_type="supergroup", user_id=42,
        old_status="member", new_status="administrator",
    ))
    assert member_origins_repo.origin_stats(CHAT) == []


async def test_chat_member_handler_join_without_link():
    from tests.aiogram_fakes import fake_membership
    from tg_repost.telegram.moderation_bot import _on_chat_member

    # Без ссылки: нашёл поиском или добавил админ.
    await _on_chat_member(fake_membership(
        chat_id=CHAT, chat_type="supergroup", user_id=43,
        old_status="left", new_status="member",
    ))
    assert member_origins_repo.origin_stats(CHAT)[0].invite_link is None
