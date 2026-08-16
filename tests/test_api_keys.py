"""Ключи внешнего доступа (F73).

Ключ — это пропуск в систему для чужой программы, поэтому тесты не про
«строка создалась», а про то, что ключ нельзя ни подсмотреть, ни подобрать,
ни использовать после отзыва, ни превратить в отказ обслуживания.
"""

from __future__ import annotations

import pytest

from tg_repost import api_keys_repo as keys
from tg_repost.db.models import ApiKey
from tg_repost.db.session import session_scope


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        with session_scope() as session:
            session.query(ApiKey).delete()
        keys.reset_rate_limits()

    _wipe()
    yield
    _wipe()


# --- создание ---


def test_created_key_authenticates():
    view, raw = keys.create("Дашборд")

    found = keys.authenticate(raw)

    assert found is not None
    assert found.id == view.id


def test_raw_key_is_never_stored():
    """ГЛАВНОЕ СВОЙСТВО.

    Утечка базы не должна давать доступ к системе. В строке лежит хэш, и
    самого ключа в ней нет ни целиком, ни куском.
    """
    _, raw = keys.create("Дашборд")
    secret = raw.split(".", 1)[1]

    with session_scope() as session:
        row = session.query(ApiKey).one()

        assert raw not in row.key_hash
        assert secret not in row.key_hash
        assert secret not in (row.prefix or "")


def test_key_cannot_be_recovered_from_the_listing():
    """Показать ключ повторно невозможно — в описании только префикс."""
    _, raw = keys.create("Дашборд")

    view = keys.list_keys()[0]

    assert raw.split(".", 1)[1] not in repr(view)


def test_two_keys_differ():
    _, first = keys.create("Первый")
    _, second = keys.create("Второй")

    assert first != second


def test_empty_name_is_refused():
    with pytest.raises(keys.InvalidKey):
        keys.create("   ")


def test_unknown_scope_is_refused():
    with pytest.raises(keys.InvalidKey):
        keys.create("Ключ", scope="admin")


@pytest.mark.parametrize("limit", [0, -1, keys.MAX_RATE_LIMIT + 1])
def test_impossible_rate_limit_is_refused(limit):
    """Ключ без предела превращает цикл без паузы в чужом скрипте в отказ
    обслуживания для всей системы."""
    with pytest.raises(keys.InvalidKey):
        keys.create("Ключ", rate_limit=limit)


def test_default_scope_is_read_only():
    """Умолчание не должно раздавать право писать."""
    view, _ = keys.create("Ключ")

    assert view.scope == keys.SCOPE_READ


# --- проверка ключа ---


@pytest.mark.parametrize("raw", [None, "", "мусор", "короткий.секрет", "."])
def test_broken_key_is_refused(raw):
    keys.create("Ключ")

    assert keys.authenticate(raw) is None


def test_wrong_secret_with_right_prefix_is_refused():
    """Префикс открыт и подсматривается в журнале — сам по себе он не пускает."""
    view, _ = keys.create("Ключ")

    assert keys.authenticate(f"{view.prefix}.подобранный") is None


def test_revoked_key_stops_working():
    view, raw = keys.create("Ключ")
    keys.revoke(view.id)

    assert keys.authenticate(raw) is None


def test_revoked_key_row_survives():
    """Удалить строку значило бы стереть след использования вместе с ключом —
    ровно тогда, когда он понадобился для разбора."""
    view, _ = keys.create("Ключ")
    keys.revoke(view.id)

    assert len(keys.list_keys()) == 1


def test_revoking_twice_reports_nothing_to_do():
    view, _ = keys.create("Ключ")

    assert keys.revoke(view.id) is True
    assert keys.revoke(view.id) is False


def test_use_is_recorded():
    """Владелец должен видеть, живой ключ или забытый."""
    _, raw = keys.create("Ключ")

    keys.authenticate(raw)

    assert keys.list_keys()[0].last_used_at is not None


def test_comparison_is_constant_time():
    """Обычное `==` выходит на первом несовпавшем символе и позволяет
    подбирать хэш побайтно по времени ответа."""
    import inspect

    assert "compare_digest" in inspect.getsource(keys.authenticate)


# --- ограничение частоты ---


def test_requests_within_the_limit_pass():
    view, _ = keys.create("Ключ", rate_limit=3)

    assert all(keys.check_rate_limit(view, now=100.0)[0] for _ in range(3))


def test_request_over_the_limit_is_refused():
    view, _ = keys.create("Ключ", rate_limit=2)
    for _ in range(2):
        keys.check_rate_limit(view, now=100.0)

    allowed, retry_after = keys.check_rate_limit(view, now=100.0)

    assert allowed is False
    assert retry_after > 0


def test_limit_frees_up_as_the_window_slides():
    view, _ = keys.create("Ключ", rate_limit=2)
    keys.check_rate_limit(view, now=100.0)
    keys.check_rate_limit(view, now=100.0)

    assert keys.check_rate_limit(view, now=161.0)[0] is True


def test_sliding_window_blocks_the_double_burst():
    """ГРАНИЦА, КОТОРУЮ ЛОМАЕТ СБРОС ПО ЧАСАМ.

    При сбросе «раз в минуту» можно отправить двойной предел на стыке: пол-
    предела в конце одной минуты и столько же в начале следующей. Скользящее
    окно этого не даёт.
    """
    view, _ = keys.create("Ключ", rate_limit=2)
    keys.check_rate_limit(view, now=159.0)
    keys.check_rate_limit(view, now=159.5)

    assert keys.check_rate_limit(view, now=160.5)[0] is False


def test_keys_have_independent_limits():
    """Чужой скрипт, упёршийся в предел, не должен мешать соседнему ключу."""
    first, _ = keys.create("Первый", rate_limit=1)
    second, _ = keys.create("Второй", rate_limit=1)
    keys.check_rate_limit(first, now=100.0)

    assert keys.check_rate_limit(second, now=100.0)[0] is True
