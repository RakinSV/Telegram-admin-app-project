"""Детектор накрутки на странице роста (F60, подключён аудитом 2026-08-16).

Сам детектор был написан и покрыт тестами, но `analyze()` не вызывался
НИОТКУДА: ни роут, ни джоба, ни шаблон. Фича числилась реализованной, а
владелец не имел способа увидеть её вывод. Тесты ниже держат именно связь
детектора со страницей — логика самих сигналов проверяется отдельно, в
`test_fraud_detector.py`.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pytest

from tests.test_app_routes import _bootstrap, _client, _isolated_env  # noqa: F401
from tg_repost.db.models import ChannelGrowthSnapshot, TargetGroup
from tg_repost.db.session import session_scope

CHAT_ID = -100777


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(ChannelGrowthSnapshot).delete()
            session.query(TargetGroup).delete()

    _wipe()
    yield
    _wipe()


def _target() -> None:
    with session_scope() as session:
        session.add(TargetGroup(chat_id=CHAT_ID, title="Тестовый канал", is_active=True))


def _snapshots(counts: list[int]) -> None:
    base = datetime.now(timezone.utc) - timedelta(days=len(counts))
    with session_scope() as session:
        for index, count in enumerate(counts):
            session.add(ChannelGrowthSnapshot(
                chat_id=CHAT_ID,
                subscriber_count=count,
                captured_at=base + timedelta(days=index),
            ))


def test_growth_page_shows_the_detector():
    client = _client()
    _bootstrap(client)
    _target()

    response = client.get("/stats/growth")

    assert response.status_code == 200
    assert "Признаки накрутки" in response.text


def test_channel_without_history_says_so_instead_of_staying_silent():
    """«Мало данных» — это ответ. Пустое место читается как «всё чисто»."""
    client = _client()
    _bootstrap(client)
    _target()

    response = client.get("/stats/growth")

    assert "мало данных" in response.text


def test_sawtooth_is_surfaced_on_the_page():
    """Резкий приход и такой же уход — первый из двух сигналов."""
    client = _client()
    _bootstrap(client)
    _target()
    # Ровный фон, затем всплеск на треть и возврат почти к исходному.
    _snapshots([1000, 1010, 1020, 1400, 1410, 1180, 1170, 1160])

    response = client.get("/stats/growth")

    assert "есть признаки" in response.text
    assert "пила" in response.text


def test_clean_channel_is_said_to_be_clean():
    client = _client()
    _bootstrap(client)
    _target()
    _snapshots([1000, 1010, 1021, 1033, 1044, 1056, 1067, 1079])

    response = client.get("/stats/growth")

    assert "ничего подозрительного" in response.text


def test_inactive_target_is_not_analyzed():
    client = _client()
    _bootstrap(client)
    with session_scope() as session:
        session.add(TargetGroup(chat_id=CHAT_ID, title="Выключен", is_active=False))

    assert "Выключен" not in client.get("/stats/growth").text


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_no_missing_translations(lang):
    client = _client()
    _bootstrap(client)
    _target()
    _snapshots([1000, 1010, 1020, 1400, 1410, 1180, 1170, 1160])

    client.get(f"/lang/{lang}?next=/stats/growth", follow_redirects=False)
    response = client.get("/stats/growth")

    assert not re.compile(r"\[[a-z_]+\.[a-z_]+\]").findall(response.text)
