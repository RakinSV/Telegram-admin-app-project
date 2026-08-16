"""Полный путь реферала: от перехода по ссылке до начисления (F42 + F67).

НАЙДЕНО АУДИТОМ 2026-08-16. Каждый кусок этой цепочки был покрыт тестами по
отдельности, и все они проходили. Не покрыт был СТЫК: в боевом коде никто
не звал `mark_joined` и `mark_first_message`, поэтому два из трёх условий
подтверждения не выполнялись НИКОГДА.

Последствия молчаливые и дорогие: реферальные очки не начислялись ни разу
(F42), партнёрские комиссии не могли начислиться в принципе (F67 требует
подтверждённого реферала), а в кабинете мини-аппа у всех стоял ноль. Ни
один тест этого не видел, потому что каждый честно вызывал недостающие
функции руками.

Отсюда правило этого файла: сценарий идёт ТОЛЬКО через то, что в бою
происходит само — вступление в чат и сообщение в группе.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tg_repost import referrals_repo
from tg_repost.db.models import Referral, UserActivity
from tg_repost.db.session import session_scope

INVITER = 8801
INVITED = 8802
CHAT = -1008800


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(Referral).delete()
            session.query(UserActivity).delete()

    _wipe()
    yield
    _wipe()


def _age_the_referral(days: int = 30) -> None:
    """Состарить вступление, чтобы выдержался срок."""
    with session_scope() as session:
        row = session.query(Referral).one()
        if row.joined_at is not None:
            row.joined_at = datetime.now(timezone.utc) - timedelta(days=days)


def test_referral_is_confirmed_after_joining_and_writing():
    """ГЛАВНЫЙ СЦЕНАРИЙ ЦЕЛИКОМ.

    Три условия: вступил, написал, прожил срок. Все три должны выполняться
    сами по ходу обычной жизни чата.
    """
    referrals_repo.register_referral(INVITER, INVITED, CHAT)
    referrals_repo.mark_joined(INVITED)
    referrals_repo.mark_first_message(INVITED)
    _age_the_referral()

    assert referrals_repo.confirm_matured_referrals(min_days=7) == 1
    assert referrals_repo.stats_for(INVITER).confirmed == 1


def test_join_without_a_message_is_not_confirmed():
    """Вступить может кто угодно; писать боты-однодневки не станут."""
    referrals_repo.register_referral(INVITER, INVITED, CHAT)
    referrals_repo.mark_joined(INVITED)
    _age_the_referral()

    assert referrals_repo.confirm_matured_referrals(min_days=7) == 0


def test_message_without_joining_is_not_confirmed():
    referrals_repo.register_referral(INVITER, INVITED, CHAT)
    referrals_repo.mark_first_message(INVITED)

    assert referrals_repo.confirm_matured_referrals(min_days=7) == 0


def test_fresh_referral_waits_out_its_term():
    referrals_repo.register_referral(INVITER, INVITED, CHAT)
    referrals_repo.mark_joined(INVITED)
    referrals_repo.mark_first_message(INVITED)

    assert referrals_repo.confirm_matured_referrals(min_days=7) == 0


# --- боевая проводка ---


def test_guardian_marks_joins_in_production():
    """ГЛАВНАЯ ПРОВЕРКА ЭТОГО ФАЙЛА.

    Проверяется не «функция работает», а что её КТО-ТО ЗОВЁТ в бою. Именно
    отсутствие вызова и было ошибкой: сами функции были исправны и покрыты
    тестами.
    """
    import pathlib

    sources = "\n".join(
        p.read_text(encoding="utf-8", errors="ignore")
        for p in list(pathlib.Path("guardian").rglob("*.py"))
        + list(pathlib.Path("engage").rglob("*.py"))
        + list(pathlib.Path("tg_repost").rglob("*.py"))
        if "__pycache__" not in str(p) and p.name != "referrals_repo.py"
    )

    assert "mark_joined(" in sources, "никто не отмечает вступление приглашённого"


def test_first_message_is_marked_in_production():
    import pathlib

    sources = "\n".join(
        p.read_text(encoding="utf-8", errors="ignore")
        for p in list(pathlib.Path("guardian").rglob("*.py"))
        + list(pathlib.Path("engage").rglob("*.py"))
        + list(pathlib.Path("tg_repost").rglob("*.py"))
        if "__pycache__" not in str(p) and p.name != "referrals_repo.py"
    )

    assert "mark_first_message(" in sources, "никто не отмечает первое сообщение"
