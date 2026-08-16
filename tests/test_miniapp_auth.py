"""Проверка подписи initData (F74).

Единственная защита всего мини-аппа: без неё любой подставит чужой user.id
обычным curl и увидит чужой кабинет. Поэтому тесты здесь не про «функция
возвращает объект», а про каждый способ обойти проверку.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest

from tg_repost.miniapp import auth

TOKEN = "123456:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
OTHER_TOKEN = "999999:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
ALICE = 7654321


def _sign(values: dict, token: str = TOKEN) -> str:
    """Собрать init_data так, как это делает Telegram."""
    pairs = sorted((k, str(v)) for k, v in values.items())
    check_string = "\n".join(f"{k}={v}" for k, v in pairs)
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    signature = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode([*pairs, ("hash", signature)])


def _init_data(**over) -> str:
    values = {
        "auth_date": int(time.time()),
        "query_id": "AAH1",
        "user": json.dumps(
            {"id": ALICE, "username": "alice", "first_name": "Алиса",
             "language_code": "ru"},
            separators=(",", ":"),
        ),
    }
    values.update(over)
    return _sign(values)


# --- честный путь ---


def test_valid_init_data_gives_the_user():
    user = auth.parse_init_data(_init_data(), TOKEN)

    assert user.id == ALICE
    assert user.username == "alice"
    assert user.language_code == "ru"


def test_cyrillic_name_survives_signing():
    """Кириллица в имени проходит через urlencode — подпись не должна
    ломаться на кодировке."""
    assert auth.parse_init_data(_init_data(), TOKEN).first_name == "Алиса"


# --- подделка ---


def test_tampered_user_id_is_rejected():
    """ГЛАВНАЯ АТАКА.

    Подменить `user.id` в строке — самый очевидный способ открыть чужой
    кабинет. Подпись перестаёт сходиться.
    """
    good = _init_data()
    bad = good.replace(str(ALICE), "111")

    assert auth.check_signature(bad, TOKEN) is False
    with pytest.raises(auth.InvalidInitData):
        auth.parse_init_data(bad, TOKEN)


def test_signature_from_another_bot_is_rejected():
    """Данные, подписанные другим ботом, — это чужая система."""
    data = _init_data()

    assert auth.check_signature(data, OTHER_TOKEN) is False


def test_missing_hash_is_rejected():
    values = {"auth_date": int(time.time()), "user": json.dumps({"id": ALICE})}

    assert auth.check_signature(urlencode(values), TOKEN) is False


def test_empty_input_is_rejected():
    assert auth.check_signature("", TOKEN) is False
    assert auth.check_signature(_init_data(), "") is False


def test_extra_field_breaks_the_signature():
    """Дописать поле к подписанной строке нельзя — оно входит в подпись."""
    data = _init_data() + "&is_admin=1"

    assert auth.check_signature(data, TOKEN) is False


# --- срок годности ---


def test_stale_data_is_rejected():
    """Подпись не протухает сама: перехваченная строка иначе осталась бы
    пропуском навсегда."""
    old = _init_data(auth_date=int(time.time()) - auth.MAX_AGE_SECONDS - 10)

    assert auth.check_signature(old, TOKEN) is True, "подпись верна"
    with pytest.raises(auth.InvalidInitData):
        auth.parse_init_data(old, TOKEN)


def test_fresh_data_within_the_window_passes():
    recent = _init_data(auth_date=int(time.time()) - 60)

    assert auth.parse_init_data(recent, TOKEN).id == ALICE


def test_future_auth_date_is_rejected():
    """Дата из будущего — подкрученные часы или попытка продлить срок."""
    future = _init_data(auth_date=int(time.time()) + 3600)

    with pytest.raises(auth.InvalidInitData):
        auth.parse_init_data(future, TOKEN)


def test_small_clock_skew_is_tolerated():
    """Минута запаса: часы клиента и сервера расходятся всегда."""
    skewed = _init_data(auth_date=int(time.time()) + 20)

    assert auth.parse_init_data(skewed, TOKEN).id == ALICE


def test_missing_auth_date_is_rejected():
    values = {
        "query_id": "AAH1",
        "user": json.dumps({"id": ALICE}, separators=(",", ":")),
    }

    with pytest.raises(auth.InvalidInitData):
        auth.parse_init_data(_sign(values), TOKEN)


# --- испорченное содержимое ---


def test_broken_user_json_is_rejected():
    with pytest.raises(auth.InvalidInitData):
        auth.parse_init_data(_init_data(user="{не json"), TOKEN)


def test_user_without_id_is_rejected():
    with pytest.raises(auth.InvalidInitData):
        auth.parse_init_data(_init_data(user=json.dumps({"username": "x"})), TOKEN)


def test_string_id_is_rejected():
    """`"id": "123"` вместо числа — попытка проскочить проверку типом."""
    with pytest.raises(auth.InvalidInitData):
        auth.parse_init_data(_init_data(user=json.dumps({"id": "123"})), TOKEN)


# --- сама криптография ---


def test_secret_key_order_matches_telegram():
    """Ключ — строка «WebAppData», сообщение — токен, а не наоборот.

    Перепутать местами — типовая ошибка, и подпись тогда не сходится
    никогда; тест ловит её прямо на формуле.
    """
    expected = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()

    assert auth._secret_key(TOKEN) == expected


def test_comparison_is_constant_time():
    """Обычное `==` выходит на первом несовпавшем байте, и подпись
    подбирается побайтно по времени ответа."""
    import inspect

    source = inspect.getsource(auth.check_signature)

    assert "compare_digest" in source
