"""Нелепый ввод в формах админки (перебор 2026-08-19).

Это не про «взлом». Владелец вводит данные руками, и ломают систему самые
обычные случаи: очистил поле, промахнулся по клавише, вставил номер из
буфера. Перебор десяти таких значений по восьми формам дал ШЕСТЬ пятисоток —
то есть стектрейс на экране вместо формы с понятной ошибкой.

Что нашлось:

* «9» сорок раз в поле chat_id и в цене товара — `OverflowError: Python int
  too large to convert to SQLite INTEGER`. База хранит целые в 64 битах, а
  проверял это ноль мест;
* пустое, пробельное и отрицательное значение в настройках рерайта — они
  МОЛЧА СОХРАНЯЛИСЬ. Пустое поле превращается в 0, а
  `IntervalTrigger(seconds=0)` APScheduler подменяет на ОДНУ СЕКУНДУ: такт
  пайплайна вместо тридцати секунд начинает идти каждую секунду, вместе со
  всеми запросами к платному провайдеру. Отрицательное значение ставит время
  следующего запуска в прошлое — джоба крутится без остановки.
"""

from __future__ import annotations

import pytest

from tests.test_app_routes import _bootstrap, _client
from tg_repost.webui.form_utils import DB_INT_MAX, coerce_form_value, parse_db_int


# --- разбор чисел ---


def test_number_too_big_for_database_is_refused():
    """Предел базы, а не «здравого смысла»: за ним запись падает
    OverflowError уже внутри SQLAlchemy, где обработать её некому."""
    assert parse_db_int(str(DB_INT_MAX)) == DB_INT_MAX
    assert parse_db_int(str(DB_INT_MAX + 1)) is None
    assert parse_db_int("9" * 40) is None
    assert parse_db_int("-" + "9" * 40) is None


def test_ordinary_chat_id_still_parses():
    """Обратная проверка: защита не должна отвергать обычные значения.
    У Telegram id супергрупп выглядят как -1001234567890."""
    assert parse_db_int("-1001234567890") == -1001234567890
    assert parse_db_int("  42  ") == 42
    assert parse_db_int("не число") is None


def test_coercion_refuses_unstorable_int():
    with pytest.raises(ValueError):
        coerce_form_value("int", "9" * 40)


@pytest.mark.parametrize("raw", ["nan", "inf", "-inf"])
def test_coercion_refuses_nan_and_infinity(raw):
    """`float("nan")` проходит молча и портит всё дальше по цепочке: любое
    сравнение с ним ложно, а в базу оно уходит как есть."""
    with pytest.raises(ValueError):
        coerce_form_value("float", raw)


# --- пределы настроек ---


def test_interval_of_zero_is_refused():
    """ГЛАВНЫЙ СЛУЧАЙ: очищенное поле интервала.

    Ноль не «выключает» джобу — APScheduler подменяет его на одну секунду.
    """
    client = _client()
    _bootstrap(client)

    response = client.post("/settings/pipeline",
                           data={"pipeline_interval_seconds": ""},
                           follow_redirects=False)

    assert response.status_code == 400, (
        "пустой интервал снова сохраняется — такт станет раз в секунду"
    )


def test_negative_interval_is_refused():
    client = _client()
    _bootstrap(client)

    response = client.post("/settings/pipeline",
                           data={"pipeline_interval_seconds": "-5"},
                           follow_redirects=False)

    assert response.status_code == 400


def test_hour_outside_the_day_is_refused():
    """Час 99 роняет CronTrigger прямо при сохранении — пятисоткой."""
    client = _client()
    _bootstrap(client)

    response = client.post("/settings/backup",
                           data={"backup_enabled": "on", "backup_hour": "99",
                                 "backup_keep": "14"},
                           follow_redirects=False)

    assert response.status_code == 400


def test_valid_settings_are_still_accepted():
    """Обратная проверка: пределы не должны мешать обычной работе."""
    client = _client()
    _bootstrap(client)

    response = client.post("/settings/pipeline",
                           data={"pipeline_interval_seconds": "30"},
                           follow_redirects=False)

    assert response.status_code in (200, 303), (
        f"нормальное значение отвергнуто: {response.status_code}"
    )


# --- формы CRUD ---


def test_huge_chat_id_gives_a_form_error_not_a_crash():
    client = _client()
    _bootstrap(client)

    response = client.post("/targets", data={"chat_id": "9" * 40, "title": "Цель"},
                           follow_redirects=False)

    assert response.status_code == 400, (
        f"длинное число снова роняет сохранение цели: {response.status_code}"
    )


def test_huge_price_gives_a_form_error_not_a_crash():
    client = _client()
    _bootstrap(client)

    response = client.post(
        "/shop/products",
        data={"name": "Товар", "price": "9" * 40, "currency": "RUB"},
        follow_redirects=False,
    )

    assert response.status_code == 400, (
        f"длинная цена снова роняет сохранение товара: {response.status_code}"
    )
