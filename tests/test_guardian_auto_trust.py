"""Тесты автодоверия по таймеру (G12) — `bot.py::_auto_trust_eligible_members`.

Раньше `auto_trust_after_days` существовал только как настройка, но ничто
никогда её не читало — найдено при ретроспективе по бэклогу."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from guardian.bot import _auto_trust_eligible_members
from guardian.config import invalidate_settings_cache
from guardian.db.models import BotConfig, Member, TrustedUser
from guardian.db.session import session_scope
from guardian import settings_store

CHAT_ID = -100123  # GUARDIAN_GROUP_ID из tests/conftest.py


@pytest.fixture(autouse=True)
def _isolated():
    with session_scope() as session:
        session.query(Member).delete()
        session.query(TrustedUser).delete()
        session.query(BotConfig).delete()
    invalidate_settings_cache()
    yield
    with session_scope() as session:
        session.query(Member).delete()
        session.query(TrustedUser).delete()
        session.query(BotConfig).delete()
    invalidate_settings_cache()


def _make_member(user_id: int, days_ago: int, **kwargs) -> None:
    defaults = {
        "user_id": user_id,
        "chat_id": CHAT_ID,
        "join_date": datetime.now(timezone.utc) - timedelta(days=days_ago),
        "is_verified": True,
        "warn_count": 0,
        "is_trusted": False,
        "is_banned": False,
    }
    defaults.update(kwargs)
    with session_scope() as session:
        session.add(Member(**defaults))


def test_eligible_member_becomes_trusted():
    settings_store.save_setting("auto_trust_after_days", 30, "int")
    _make_member(1, days_ago=31)

    _auto_trust_eligible_members()

    with session_scope() as session:
        assert session.query(TrustedUser).filter(TrustedUser.user_id == 1).count() == 1
        member = session.query(Member).filter(Member.user_id == 1).one()
        assert member.is_trusted is True


def test_recent_member_not_yet_eligible():
    settings_store.save_setting("auto_trust_after_days", 30, "int")
    _make_member(1, days_ago=5)

    _auto_trust_eligible_members()

    with session_scope() as session:
        assert session.query(TrustedUser).count() == 0


def test_member_with_warns_not_eligible():
    settings_store.save_setting("auto_trust_after_days", 30, "int")
    _make_member(1, days_ago=31, warn_count=1)

    _auto_trust_eligible_members()

    with session_scope() as session:
        assert session.query(TrustedUser).count() == 0


def test_unverified_member_not_eligible():
    settings_store.save_setting("auto_trust_after_days", 30, "int")
    _make_member(1, days_ago=31, is_verified=False)

    _auto_trust_eligible_members()

    with session_scope() as session:
        assert session.query(TrustedUser).count() == 0


def test_banned_member_not_eligible():
    settings_store.save_setting("auto_trust_after_days", 30, "int")
    _make_member(1, days_ago=31, is_banned=True)

    _auto_trust_eligible_members()

    with session_scope() as session:
        assert session.query(TrustedUser).count() == 0


def test_already_trusted_member_skipped_gracefully():
    settings_store.save_setting("auto_trust_after_days", 30, "int")
    _make_member(1, days_ago=31, is_trusted=True)
    with session_scope() as session:
        session.add(TrustedUser(user_id=1, chat_id=CHAT_ID, added_by="test"))

    _auto_trust_eligible_members()  # не должно упасть/задублировать

    with session_scope() as session:
        assert session.query(TrustedUser).filter(TrustedUser.user_id == 1).count() == 1


def test_disabled_when_threshold_zero():
    settings_store.save_setting("auto_trust_after_days", 0, "int")
    _make_member(1, days_ago=365)

    _auto_trust_eligible_members()

    with session_scope() as session:
        assert session.query(TrustedUser).count() == 0
