"""Mini App: витрина внутри Telegram (F74) — роуты.

⚠️ ЭТО ЕДИНСТВЕННАЯ ПУБЛИЧНО ДОСТУПНАЯ ЧАСТЬ СИСТЕМЫ. Вся остальная админка
за логином, и открытие `/app` наружу не должно было приоткрыть ничего
другого. Поэтому здесь проверяется не только «страница работает», но и то,
что освобождение `/app` от ролей не распространилось на соседей.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest

from tests.test_app_routes import _bootstrap, _client, _isolated_env  # noqa: F401
from tg_repost import subscriptions_repo as subs
from tg_repost.db.models import ChannelSubscription, PaymentEvent, Product
from tg_repost.db.session import session_scope

TOKEN = "123456:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
ALICE = 7654321
BOB = 7654322


def _sign(values: dict, token: str = TOKEN) -> str:
    pairs = sorted((k, str(v)) for k, v in values.items())
    check_string = "\n".join(f"{k}={v}" for k, v in pairs)
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    signature = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode([*pairs, ("hash", signature)])


def _init_data(user_id: int = ALICE, **over) -> str:
    values = {
        "auth_date": int(time.time()),
        "user": json.dumps(
            {"id": user_id, "username": "alice", "first_name": "Алиса"},
            separators=(",", ":"),
        ),
    }
    values.update(over)
    return _sign(values)


@pytest.fixture(autouse=True)
def _token(monkeypatch):
    monkeypatch.setattr(
        "tg_repost.miniapp.auth.engage_bot_token", lambda: TOKEN,
    )


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(PaymentEvent).delete()
            session.query(ChannelSubscription).delete()
            session.query(Product).delete()

    _wipe()
    yield
    _wipe()


# --- оболочка ---


def test_shell_opens_without_login():
    """Мини-апп открывает Telegram, а не залогиненный админ."""
    client = _client()

    response = client.get("/app")

    assert response.status_code == 200
    assert "telegram-web-app.js" in response.text


def test_shell_carries_no_data():
    """`initData` доступна только JS внутри Telegram — в первом GET её нет,
    и наполнить страницу сервер физически не может."""
    client = _client()

    body = client.get("/app").text

    assert str(ALICE) not in body


# --- данные ---


def test_valid_init_data_returns_the_dashboard():
    client = _client()

    response = client.post("/app/data", data={"init_data": _init_data()})

    assert response.status_code == 200
    assert "Алиса" in response.text


def test_tampered_init_data_is_refused():
    """ГЛАВНАЯ АТАКА: подменить user.id и открыть чужой кабинет."""
    client = _client()
    bad = _init_data().replace(str(ALICE), str(BOB))

    response = client.post("/app/data", data={"init_data": bad})

    assert response.status_code == 403


def test_empty_init_data_is_refused():
    client = _client()

    assert client.post("/app/data", data={"init_data": ""}).status_code == 403


def test_stale_init_data_is_refused():
    client = _client()
    old = _init_data(auth_date=int(time.time()) - 60 * 60 * 48)

    assert client.post("/app/data", data={"init_data": old}).status_code == 403


def test_refusal_does_not_explain_the_reason(monkeypatch):
    """Подробность вида «подпись верна, но истекла» помогает подбирать."""
    client = _client()
    old = _init_data(auth_date=int(time.time()) - 60 * 60 * 48)

    body = client.post("/app/data", data={"init_data": old}).text

    for leak in ("подпись", "auth_date", "старше", "hash"):
        assert leak not in body.lower()


def test_without_bot_token_nothing_is_served(monkeypatch):
    """Без токена подпись проверить нечем — значит верить нельзя никому."""
    monkeypatch.setattr("tg_repost.miniapp.auth.engage_bot_token", lambda: "")
    client = _client()

    assert client.post("/app/data", data={"init_data": _init_data()}).status_code == 403


# --- видно только своё ---


CHAT = -1009900


@pytest.fixture
def _paid_channel():
    """Включить платный канал на время теста.

    Не `pytest.skip`, если он не настроен: пропущенный тест ничего не
    охраняет, а охраняет он здесь главное обещание мини-аппа — «видно
    только своё».
    """
    from tg_repost.webui import settings_store

    settings_store.save_setting("paid_access_chat_id", CHAT, "int")
    settings_store.invalidate_settings_cache()
    yield CHAT
    settings_store.reset_setting("paid_access_chat_id")
    settings_store.invalidate_settings_cache()


def test_dashboard_shows_own_subscription(_paid_channel):
    from datetime import datetime, timedelta, timezone

    client = _client()
    subs.grant(
        chat_id=_paid_channel, user_id=ALICE,
        paid_until=datetime.now(timezone.utc) + timedelta(days=30),
    )

    body = client.post("/app/data", data={"init_data": _init_data(ALICE)}).text

    assert "Активна до" in body


def test_inviter_leaderboard_counts_confirmed_only():
    """Лидерборд пригласивших считает ЗАСЧИТАННЫЕ приглашения.

    Считай он переходы — первое место занял бы тот, кто нагнал
    мультиаккаунтов, и таблица стала бы рекламой накрутки.
    """
    from datetime import datetime, timedelta, timezone

    from tg_repost import targets_repo
    from tg_repost.db.models import Referral, TargetGroup

    with session_scope() as session:
        session.query(TargetGroup).delete()
        session.query(Referral).delete()
        session.add(TargetGroup(chat_id=-100777, title="Канал", is_active=True))
        # Честный: приглашение засчитано. Накрутчик: три перехода без
        # подтверждения.
        session.add(Referral(
            inviter_user_id=ALICE, invited_user_id=5001, chat_id=-100777,
            joined_at=datetime.now(timezone.utc) - timedelta(days=10),
            first_message_at=datetime.now(timezone.utc) - timedelta(days=9),
            confirmed_at=datetime.now(timezone.utc),
        ))
        for invited in (5002, 5003, 5004):
            session.add(Referral(
                inviter_user_id=BOB, invited_user_id=invited, chat_id=-100777,
            ))
    del targets_repo

    client = _client()
    body = client.post("/app/data", data={"init_data": _init_data(ALICE)}).text

    with session_scope() as session:
        session.query(Referral).delete()
        session.query(TargetGroup).delete()

    assert "Кто привёл больше всех" in body
    assert str(BOB) not in body, "накрутчик попал в таблицу"


def test_dashboard_never_shows_someone_elses_subscription(_paid_channel):
    """ГЛАВНОЕ ОБЕЩАНИЕ МИНИ-АППА.

    У Боба подписка есть, у Алисы нет. Алиса не должна увидеть ни его
    подписку, ни намёка на неё.
    """
    from datetime import datetime, timedelta, timezone

    client = _client()
    subs.grant(
        chat_id=_paid_channel, user_id=BOB,
        paid_until=datetime.now(timezone.utc) + timedelta(days=30),
    )

    body = client.post("/app/data", data={"init_data": _init_data(ALICE)}).text

    assert "Активна до" not in body
    assert str(BOB) not in body


# --- освобождение /app не открыло соседей ---


@pytest.mark.parametrize(
    "path", ["/", "/settings", "/users", "/subscriptions", "/moderation", "/shop"],
)
def test_admin_pages_still_require_login(path):
    """РЕГРЕССИЯ НА ГЛАВНЫЙ РИСК ФИЧИ.

    `/app` внесён в список освобождённых от проверки ролей. Ошибка в
    префиксе — и вместе с ним открылась бы вся админка.
    """
    client = _client()

    assert client.get(path, follow_redirects=False).status_code in (302, 303, 307, 403)


def test_app_prefix_does_not_match_other_paths():
    """`/app` не должен совпадать с `/approvals`, `/apps` и подобным."""
    from tg_repost.webui import access

    assert access.is_exempt("/app") is True
    assert access.is_exempt("/app/data") is True
    assert access.is_exempt("/approve") is False
    assert access.is_exempt("/apps") is False
