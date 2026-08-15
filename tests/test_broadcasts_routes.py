"""Веб-интерфейс рассылок (F64).

Отправка необратима, поэтому интерфейс двухшаговый, и тесты в основном про
это: предпросмотр ничего не отправляет, подтверждение сверяет числа с теми,
что человек видел, а если состав сегмента изменился между экранами —
владельца возвращают на предпросмотр вместо тихой отправки по другому
списку.
"""

from __future__ import annotations

import pytest

from tests.test_app_routes import _bootstrap, _client, _isolated_env  # noqa: F401
from tg_repost import broadcasts_repo, contacts_repo, segments_repo, subscribers_repo
from tg_repost.db.models import (
    Broadcast,
    BotSubscriber,
    ContactSegment,
    ContactTag,
    QueuedTask,
)
from tg_repost.db.session import session_scope


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(Broadcast).delete()
            session.query(QueuedTask).delete()
            session.query(BotSubscriber).delete()
            session.query(ContactTag).delete()
            session.query(ContactSegment).delete()

    _wipe()
    yield
    _wipe()


def _segment(reachable: int = 1, unreachable: int = 0) -> int:
    user_id = 1
    for _ in range(reachable):
        contacts_repo.add_tag(user_id, "рассылка")
        subscribers_repo.record_contact(user_id)
        user_id += 1
    for _ in range(unreachable):
        contacts_repo.add_tag(user_id, "рассылка")
        user_id += 1
    return segments_repo.save("Тест", {"tag": "рассылка"})


# --- страница ---


def test_page_opens_when_empty():
    client = _client()
    _bootstrap(client)

    assert client.get("/broadcasts").status_code == 200


def test_page_suggests_creating_segment_first():
    client = _client()
    _bootstrap(client)

    response = client.get("/broadcasts")

    assert "/segments" in response.text


# --- шаг 1: предпросмотр ---


def test_preview_shows_both_numbers_and_sends_nothing():
    """ГЛАВНОЕ: предпросмотр НИЧЕГО не отправляет.

    Если бы он создавал рассылку, «посмотреть, кому уйдёт» означало бы
    «отправить» — и первая же проверка обернулась бы разосланными
    сообщениями.
    """
    client = _client()
    _bootstrap(client)
    segment_id = _segment(reachable=1, unreachable=2)

    response = client.post(
        "/broadcasts/preview",
        data={"segment_id": str(segment_id), "text": "Привет!"},
    )

    assert response.status_code == 200
    assert broadcasts_repo.list_recent() == []
    # Обе цифры на экране: 3 в сегменте, 1 получит.
    assert ">3<" in response.text
    assert ">1<" in response.text


def test_preview_explains_why_fewer():
    client = _client()
    _bootstrap(client)
    segment_id = _segment(reachable=1, unreachable=2)

    response = client.post(
        "/broadcasts/preview",
        data={"segment_id": str(segment_id), "text": "Привет!"},
    )

    # Причина названа: люди не запускали бота. Без объяснения цифра
    # выглядит как поломка.
    assert "не запускали бота" in response.text


def test_preview_requires_segment_and_text():
    client = _client()
    _bootstrap(client)
    segment_id = _segment()

    empty_text = client.post(
        "/broadcasts/preview", data={"segment_id": str(segment_id), "text": "  "},
    )

    assert empty_text.status_code == 400
    assert broadcasts_repo.list_recent() == []


def test_preview_warns_when_nobody_is_reachable():
    """Отправлять некому — кнопки отправки быть не должно."""
    client = _client()
    _bootstrap(client)
    segment_id = _segment(reachable=0, unreachable=3)

    response = client.post(
        "/broadcasts/preview",
        data={"segment_id": str(segment_id), "text": "Привет!"},
    )

    assert "Отправлять некому" in response.text
    assert "/broadcasts/send" not in response.text


# --- шаг 2: отправка ---


def test_send_creates_broadcast():
    client = _client()
    _bootstrap(client)
    segment_id = _segment(reachable=2)

    response = client.post(
        "/broadcasts/send",
        data={
            "segment_id": str(segment_id),
            "text": "Привет!",
            "expected_reachable": "2",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    rows = broadcasts_repo.list_recent()
    assert len(rows) == 1
    assert rows[0].reachable_size == 2


def test_send_blocks_when_segment_changed_between_screens():
    """САМАЯ ТОНКАЯ ЗАЩИТА.

    Человек посмотрел предпросмотр на 1 получателя, отвлёкся, а за это время
    сегмент вырос до 3. Молча отправить по новому списку — ровно то, ради
    чего предпросмотр и существует. Возвращаем на него с новыми числами.
    """
    client = _client()
    _bootstrap(client)
    segment_id = _segment(reachable=3)

    response = client.post(
        "/broadcasts/send",
        data={
            "segment_id": str(segment_id),
            "text": "Привет!",
            "expected_reachable": "1",  # столько было на предпросмотре
        },
        follow_redirects=False,
    )

    assert response.status_code == 409
    assert broadcasts_repo.list_recent() == []
    assert "изменился" in response.text


def test_send_ignores_missing_segment():
    client = _client()
    _bootstrap(client)

    response = client.post(
        "/broadcasts/send",
        data={"segment_id": "999999", "text": "Привет!", "expected_reachable": "1"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert broadcasts_repo.list_recent() == []


# --- остановка ---


def test_cancel_stops_broadcast():
    client = _client()
    _bootstrap(client)
    segment_id = _segment(reachable=2)
    broadcast_id = broadcasts_repo.create(segment_id, "Привет!")

    response = client.post(
        f"/broadcasts/{broadcast_id}/cancel", follow_redirects=False,
    )

    assert response.status_code == 303
    row = broadcasts_repo.get(broadcast_id)
    assert row is not None
    assert row.status == broadcasts_repo.STATUS_CANCELED


def test_history_shows_the_gap_between_segment_and_reached():
    client = _client()
    _bootstrap(client)
    segment_id = _segment(reachable=1, unreachable=4)
    broadcasts_repo.create(segment_id, "Привет!")

    response = client.get("/broadcasts")

    assert "в сегменте было 5" in response.text


def test_pages_require_login():
    client = _client()

    assert client.get("/broadcasts", follow_redirects=False).status_code in (302, 303, 307)


# --- полнота переводов ---


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_no_missing_translations(lang):
    import re

    client = _client()
    _bootstrap(client)
    segment_id = _segment(reachable=1, unreachable=1)
    broadcasts_repo.create(segment_id, "Привет!")

    client.get(f"/lang/{lang}?next=/broadcasts", follow_redirects=False)
    listing = client.get("/broadcasts")
    preview = client.post(
        "/broadcasts/preview",
        data={"segment_id": str(segment_id), "text": "Привет!"},
    )

    missing = re.compile(r"\[[a-z_]+\.[a-z_]+\]")
    assert not missing.findall(listing.text), f"список ({lang})"
    assert not missing.findall(preview.text), f"предпросмотр ({lang})"
