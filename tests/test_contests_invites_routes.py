"""Роуты конкурсов и инвайт-ссылок: отказы и защита от чужих рук.

ПОЧЕМУ ИМЕННО ЭТИ ДВА МОДУЛЯ. Замер покрытия: `contests_routes.py` — 35%,
`invites_routes.py` — 68%. Само по себе это не приговор, но здесь непокрытым
было именно то, ради чего роуты и написаны: проверки ввода. Конкурс с датой в
прошлом разыгрался бы первым же проходом джобы — до того, как хоть кто-то
успел бы участвовать; конкурс с нулём победителей не разыграл бы никого.

ВТОРАЯ ТЕМА — ЗАЩИТА. Оба модуля пишут в базу и дёргают Telegram, и оба
обязаны быть недоступны без входа. Это ровно тот случай, где «и так
понятно» стоит проверить: `require_login` вешается на роутер целиком, и
достаточно одного забытого `dependencies=[...]` в новом роутере, чтобы
страница молча открылась миру.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from tg_repost import contests_repo
from tg_repost.db.models import Contest, InviteLink, TargetGroup
from tg_repost.db.session import session_scope
from tg_repost.webui import setup_token
from tg_repost.webui.app import create_app


def _client() -> TestClient:
    return TestClient(create_app())


def _bootstrap(client: TestClient, password: str = "contest-test-password-1") -> None:
    token = setup_token.get_or_create_setup_token()
    response = client.post(
        f"/setup?token={token}",
        data={"password": password, "password_confirm": password},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text[:300]
    response = client.post("/login", data={"password": password}, follow_redirects=False)
    assert response.status_code == 303, response.text[:300]


@pytest.fixture
def target_chat() -> int:
    """Активная цель: без неё конкурсу некуда идти."""
    with session_scope() as session:
        group = TargetGroup(chat_id=-100777000, title="Тестовая цель", is_active=True)
        session.add(group)
        session.flush()
        return group.chat_id


@pytest.fixture(autouse=True)
def _clean():
    yield
    with session_scope() as session:
        session.query(Contest).delete()
        session.query(InviteLink).delete()
        session.query(TargetGroup).filter(TargetGroup.chat_id == -100777000).delete()


def _form(**overrides) -> dict:
    future = datetime.now(timezone.utc) + timedelta(days=3)
    data = {
        "chat_id": "-100777000",
        "title": "Розыгрыш подписки",
        "prize": "Год доступа",
        "winners_count": "2",
        "ends_at": future.strftime("%Y-%m-%dT%H:%M"),
        "require_min_points": "0",
        "require_min_referrals": "0",
    }
    data.update(overrides)
    return data


# --- защита ---


def test_contests_page_requires_login():
    """Страница конкурсов пишет в базу и говорит с группой — без входа её
    быть не должно."""
    client = _client()

    response = client.get("/contests", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_contest_creation_requires_login():
    """Отдельно от страницы: POST мог остаться открытым при закрытом GET."""
    client = _client()

    response = client.post("/contests", data=_form(), follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    with session_scope() as session:
        assert session.query(Contest).count() == 0, "конкурс создан без входа"


def test_invites_page_requires_login():
    client = _client()

    response = client.get("/invites", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


# --- создание конкурса ---


def test_contest_is_created_from_the_form(target_chat):
    client = _client()
    _bootstrap(client)

    response = client.post("/contests", data=_form(), follow_redirects=False)

    assert response.status_code == 303
    rows = contests_repo.list_contests()
    assert len(rows) == 1
    assert rows[0].title == "Розыгрыш подписки"


@pytest.mark.parametrize("field", ["title", "prize"])
def test_contest_without_title_or_prize_is_refused(field, target_chat):
    """Конкурс без приза — это объявление ни о чём: участник не понимает, за
    что играет, а владелец потом не помнит, что обещал."""
    client = _client()
    _bootstrap(client)

    response = client.post("/contests", data=_form(**{field: "   "}))

    assert response.status_code == 400
    assert contests_repo.list_contests() == []


def test_contest_with_past_deadline_is_refused(target_chat):
    """ГЛАВНАЯ ПРОВЕРКА. Конкурс с датой в прошлом разыгрался бы первым же
    проходом джобы — до того, как хоть кто-нибудь успел бы поучаствовать."""
    past = datetime.now(timezone.utc) - timedelta(days=1)
    client = _client()
    _bootstrap(client)

    response = client.post(
        "/contests", data=_form(ends_at=past.strftime("%Y-%m-%dT%H:%M")),
    )

    assert response.status_code == 400
    assert contests_repo.list_contests() == []


def test_contest_without_winners_is_refused(target_chat):
    """Ноль победителей — розыгрыш, который никого не выберет.

    Проверяется ИМЕННО ТЕКСТ ОТКАЗА, а не только код 400. Первая версия
    сравнивала лишь статус и оказалась беззубой: диверсия сняла проверку в
    роуте, а тест остался зелёным — конкурс всё равно не создавался, потому
    что его отсекал репозиторий, и владелец получал невнятное «конкурс не
    создан — проверьте поля» вместо причины.
    """
    client = _client()
    _bootstrap(client)

    response = client.post("/contests", data=_form(winners_count="0"))

    assert response.status_code == 400
    assert "хотя бы один" in response.text, (
        "владельцу не сказали, ЧТО не так: причина подменилась общей отговоркой"
    )
    assert contests_repo.list_contests() == []


@pytest.mark.parametrize(
    "field,value",
    [("winners_count", "два"), ("require_min_points", "-"),
     ("require_min_referrals", "много"), ("chat_id", "не число")],
)
def test_non_numeric_fields_are_refused(field, value, target_chat):
    """Текст вместо числа не должен ронять страницу пятисоткой: это обычная
    опечатка, а не сбой."""
    client = _client()
    _bootstrap(client)

    response = client.post("/contests", data=_form(**{field: value}))

    assert response.status_code == 400
    assert contests_repo.list_contests() == []


def test_broken_date_is_refused(target_chat):
    client = _client()
    _bootstrap(client)

    response = client.post("/contests", data=_form(ends_at="вчера"))

    assert response.status_code == 400
    assert contests_repo.list_contests() == []


def test_finished_contest_is_shown_as_over(target_chat):
    """Страница обязана отличать идущий конкурс от законченного: иначе
    владелец ждёт розыгрыша, который уже прошёл."""
    client = _client()
    _bootstrap(client)
    contests_repo.create_contest(
        chat_id=target_chat, title="Уже всё", prize="Приз",
        winners_count=1,
        ends_at=datetime.now(timezone.utc) - timedelta(hours=1),
        require_min_points=0, require_min_referrals=0,
    )

    page = client.get("/contests")

    assert page.status_code == 200
    assert "Уже всё" in page.text


# --- инвайт-ссылки ---


def test_invite_creation_without_a_running_bot_says_so(target_chat):
    """Ссылку создаёт Telegram, а не мы. Без живого бота честный отказ лучше
    молчаливой переадресации: иначе владелец ищет ссылку, которой нет."""
    client = _client()
    _bootstrap(client)

    response = client.post(
        "/invites", data={"chat_id": str(target_chat), "name": "Тест"},
    )

    assert response.status_code == 400
    with session_scope() as session:
        assert session.query(InviteLink).count() == 0


def test_invite_member_limit_must_be_a_number(target_chat):
    client = _client()
    _bootstrap(client)

    response = client.post(
        "/invites",
        data={"chat_id": str(target_chat), "name": "Тест", "member_limit": "пять"},
    )

    assert response.status_code == 400


def test_invite_cost_ignores_a_typo_instead_of_zeroing_it():
    """Опечатку в цене нельзя молча превращать в «бесплатно»: CPA посчитается
    по нулю, и решение о закупке будет принято по вранью."""
    with session_scope() as session:
        link = InviteLink(
            chat_id=-100777000, invite_link="https://t.me/+test",
            name="Платное размещение", cost=1000.0, cost_currency="RUB",
        )
        session.add(link)
        session.flush()
        link_id = link.id

    client = _client()
    _bootstrap(client)

    response = client.post(
        f"/invites/{link_id}/cost", data={"cost": "тысяча", "currency": "RUB"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    with session_scope() as session:
        assert session.get(InviteLink, link_id).cost == 1000.0, "цену затёрли опечаткой"


def test_invite_cost_refuses_a_negative_price():
    """Отрицательная цена размещения — это доход, а не расход: CPA стал бы
    отрицательным, и отчёт показал бы, что подписчики приносят деньги сами."""
    with session_scope() as session:
        link = InviteLink(
            chat_id=-100777000, invite_link="https://t.me/+neg", cost=500.0,
            cost_currency="RUB",
        )
        session.add(link)
        session.flush()
        link_id = link.id

    client = _client()
    _bootstrap(client)

    client.post(
        f"/invites/{link_id}/cost", data={"cost": "-100", "currency": "RUB"},
        follow_redirects=False,
    )

    with session_scope() as session:
        assert session.get(InviteLink, link_id).cost == 500.0


def test_invite_cost_can_be_cleared():
    """Пустое значение стирает цену: размещение могло быть по бартеру, и
    показывать CPA от прошлой цифры было бы враньём."""
    with session_scope() as session:
        link = InviteLink(
            chat_id=-100777000, invite_link="https://t.me/+barter", cost=700.0,
            cost_currency="RUB",
        )
        session.add(link)
        session.flush()
        link_id = link.id

    client = _client()
    _bootstrap(client)

    client.post(
        f"/invites/{link_id}/cost", data={"cost": "", "currency": "RUB"},
        follow_redirects=False,
    )

    with session_scope() as session:
        assert session.get(InviteLink, link_id).cost is None


def test_invite_cost_accepts_a_comma_as_decimal_separator():
    """Русская раскладка ставит запятую, и это не ошибка ввода."""
    with session_scope() as session:
        link = InviteLink(
            chat_id=-100777000, invite_link="https://t.me/+comma", cost_currency="RUB",
        )
        session.add(link)
        session.flush()
        link_id = link.id

    client = _client()
    _bootstrap(client)

    client.post(
        f"/invites/{link_id}/cost", data={"cost": "1234,50", "currency": "RUB"},
        follow_redirects=False,
    )

    with session_scope() as session:
        assert session.get(InviteLink, link_id).cost == pytest.approx(1234.50)


def test_join_request_actions_need_a_running_bot():
    """Заявку одобряет Telegram. Без бота роут обязан сказать это вслух, а не
    делать вид, что заявка обработана."""
    client = _client()
    _bootstrap(client)

    for path in ("/invites/join-requests/1/approve", "/invites/join-requests/1/decline"):
        response = client.post(path)
        assert response.status_code == 400, path


# --- инвайты с живым ботом ---
#
# Эти пути и оставались непокрытыми: без бота роут отвечает отказом и до
# Telegram не доходит. Подделываем бота ровно так же, как это делают тесты
# модерации — сеть в тестах не нужна, а проверять удобно по вызовам бота.


def _with_bot(bot):
    """Подставить бота в живые компоненты на время теста."""
    from tg_repost.webui.supervisor import get_components

    components = get_components()
    components.moderation_bot = bot
    return components


def test_invite_link_is_created_through_telegram(target_chat):
    """Ссылку выдаёт Telegram, мы только сохраняем её. Проверяем, что роут
    действительно её запрашивает, а не выдумывает."""
    from unittest.mock import AsyncMock

    from aiogram.types import ChatInviteLink

    from tg_repost.webui.supervisor import get_components

    bot = AsyncMock()
    bot.create_chat_invite_link.return_value = ChatInviteLink(
        invite_link="https://t.me/+created", creator=_bot_user(),
        creates_join_request=False, is_primary=False, is_revoked=False,
        name="Из теста", member_limit=50,
    )
    client = _client()
    _bootstrap(client)
    _with_bot(bot)
    try:
        response = client.post(
            "/invites",
            data={"chat_id": str(target_chat), "name": "Из теста",
                  "member_limit": "50"},
            follow_redirects=False,
        )
    finally:
        get_components().moderation_bot = None

    assert response.status_code == 303
    bot.create_chat_invite_link.assert_awaited_once()
    with session_scope() as session:
        saved = session.query(InviteLink).one()
        assert saved.invite_link == "https://t.me/+created"
        assert saved.member_limit == 50


def test_invite_link_revoke_calls_telegram(target_chat):
    """Отзыв только в базе оставил бы ссылку рабочей: люди продолжали бы
    заходить по ней, а админка показывала бы «отозвана»."""
    from unittest.mock import AsyncMock

    from tg_repost.webui.supervisor import get_components

    with session_scope() as session:
        link = InviteLink(
            chat_id=target_chat, invite_link="https://t.me/+revokeme",
        )
        session.add(link)
        session.flush()
        link_id = link.id

    bot = AsyncMock()
    client = _client()
    _bootstrap(client)
    _with_bot(bot)
    try:
        response = client.post(f"/invites/{link_id}/revoke", follow_redirects=False)
    finally:
        get_components().moderation_bot = None

    assert response.status_code == 303
    bot.revoke_chat_invite_link.assert_awaited_once()
    with session_scope() as session:
        assert session.get(InviteLink, link_id).is_revoked is True


def _bot_user():
    from aiogram.types import User

    return User(id=42, is_bot=True, first_name="Тестовый бот")


@pytest.mark.parametrize(
    "action,method,approved",
    [("approve", "approve_chat_join_request", "approved"),
     ("decline", "decline_chat_join_request", "declined")],
)
def test_join_request_decision_goes_to_telegram(action, method, approved, target_chat):
    """Решение по заявке принимает Telegram. Отметить её решённой только в
    базе — значит показать владельцу, что человек впущен, пока тот стоит за
    дверью."""
    from unittest.mock import AsyncMock

    from tg_repost.db.models import JoinRequestRecord
    from tg_repost.webui.supervisor import get_components

    with session_scope() as session:
        record = JoinRequestRecord(
            chat_id=target_chat, user_id=555001, status="pending",
        )
        session.add(record)
        session.flush()
        request_id = record.id

    bot = AsyncMock()
    client = _client()
    _bootstrap(client)
    _with_bot(bot)
    try:
        response = client.post(
            f"/invites/join-requests/{request_id}/{action}", follow_redirects=False,
        )
    finally:
        get_components().moderation_bot = None

    assert response.status_code == 303
    getattr(bot, method).assert_awaited_once()
    with session_scope() as session:
        assert session.get(JoinRequestRecord, request_id).status == approved
        session.query(JoinRequestRecord).delete()
