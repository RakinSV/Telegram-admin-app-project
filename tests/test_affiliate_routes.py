"""Страница партнёров (F67).

Здесь раздаётся доля выручки, поэтому проверяются права и то, что запись
выплаты не позволяет внести в историю неправду.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest

from tests.test_app_routes import _bootstrap, _client, _isolated_env  # noqa: F401
from tg_repost import affiliate_repo
from tg_repost.db.models import AdminUser, AffiliateReward, PaymentEvent, Referral
from tg_repost.db.session import session_scope
from tg_repost.webui import access
from tg_repost.webui.auth import hash_password

PARTNER = 9501


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(AffiliateReward).delete()
            session.query(PaymentEvent).delete()
            session.query(Referral).delete()

    _wipe()
    yield
    _wipe()


def _earned(amount: int = 100) -> None:
    with session_scope() as session:
        session.add(AffiliateReward(
            kind=affiliate_repo.KIND_ACCRUAL,
            partner_user_id=PARTNER,
            payer_user_id=777,
            payment_event_id=1,
            amount=amount,
            percent=30,
            created_at=datetime.now(timezone.utc),
        ))


def test_page_opens_when_empty():
    client = _client()
    _bootstrap(client)

    assert client.get("/affiliate").status_code == 200


def test_page_warns_when_programme_is_off():
    """Пустая страница без объяснения читается как «партнёров нет»."""
    client = _client()
    _bootstrap(client)

    assert "выключена" in client.get("/affiliate").text


def test_partner_and_debt_are_shown():
    client = _client()
    _bootstrap(client)
    _earned(100)

    body = client.get("/affiliate").text

    assert str(PARTNER) in body
    assert "100" in body


def test_detail_shows_history():
    client = _client()
    _bootstrap(client)
    _earned(100)

    body = client.get(f"/affiliate/{PARTNER}").text

    assert "начислено" in body


def test_payout_is_recorded():
    client = _client()
    _bootstrap(client)
    _earned(100)

    response = client.post(
        f"/affiliate/{PARTNER}/payout", data={"amount": "100", "note": "TON"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert affiliate_repo.balance_of(PARTNER).owed == 0


def test_payout_larger_than_debt_is_refused():
    client = _client()
    _bootstrap(client)
    _earned(100)

    client.post(
        f"/affiliate/{PARTNER}/payout", data={"amount": "500"},
        follow_redirects=False,
    )

    assert affiliate_repo.balance_of(PARTNER).owed == 100


def test_non_numeric_payout_is_refused():
    client = _client()
    _bootstrap(client)
    _earned(100)

    client.post(
        f"/affiliate/{PARTNER}/payout", data={"amount": "сто"},
        follow_redirects=False,
    )

    assert affiliate_repo.balance_of(PARTNER).owed == 100


def test_page_is_owner_only():
    client = _client()
    _bootstrap(client)
    with session_scope() as session:
        session.add(AdminUser(
            username="editor_aff", role=access.ROLE_EDITOR,
            password_hash=hash_password("another-strong-pass"),
        ))
    client.post(
        "/login", data={"username": "editor_aff", "password": "another-strong-pass"},
        follow_redirects=False,
    )

    assert client.get("/affiliate").status_code == 403


def test_payout_button_says_it_only_records():
    """Кнопка, делающая вид, что переводит деньги, была бы обманом."""
    client = _client()
    _bootstrap(client)
    _earned()

    assert "ЗАПИСЬ ФАКТА" in client.get("/affiliate").text


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_no_missing_translations(lang):
    client = _client()
    _bootstrap(client)
    _earned()

    client.get(f"/lang/{lang}?next=/affiliate", follow_redirects=False)
    listing = client.get("/affiliate")
    detail = client.get(f"/affiliate/{PARTNER}")

    missing = re.compile(r"\[[a-z_]+\.[a-z_]+\]")
    assert not missing.findall(listing.text), f"список ({lang})"
    assert not missing.findall(detail.text), f"карточка ({lang})"
