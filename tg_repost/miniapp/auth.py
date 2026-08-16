"""Проверка подписи `initData` от Telegram (F74).

ЕДИНСТВЕННАЯ ЗАЩИТА ВСЕГО МИНИ-АППА. Telegram передаёт данные о пользователе
строкой запроса, и без проверки подписи любой может подставить туда чужой
`user.id` обычным curl. Тогда «мой реферальный кабинет» показывал бы чужой,
а «моя подписка» — чужую. Здесь нет ничего второстепенного.

КАК ЭТО УСТРОЕНО У TELEGRAM:

1. из всех пар `ключ=значение`, КРОМЕ `hash`, собирается строка: пары
   сортируются по ключу и склеиваются через `\\n`;
2. секрет считается как `HMAC_SHA256(токен_бота, "WebAppData")` — обратите
   внимание на порядок: ключом выступает СТРОКА "WebAppData", а сообщением
   токен, а не наоборот. Перепутать местами — типовая ошибка, и подпись
   тогда не сойдётся ни разу;
3. подпись — `HMAC_SHA256(строка_из_шага_1, секрет)`, сравнивается с `hash`.

СРАВНЕНИЕ ТОЛЬКО `hmac.compare_digest`. Обычное `==` выходит из цикла на
первом несовпавшем байте, и по времени ответа подпись подбирается побайтно.

СРОК ГОДНОСТИ ОБЯЗАТЕЛЕН. Подпись не протухает сама: перехваченная строка
осталась бы пропуском навсегда. `auth_date` старше суток не принимается.

ТОКЕН — ОТ БОТА ENGAGE. Мини-апп открывается из него, им же подписаны
данные; проверка токеном бота модерации не сойдётся никогда.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl

from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)

# Сутки. Мини-апп открывают и оставляют висеть во вкладке, поэтому час был
# бы слишком строг; неделя — уже подарок тому, кто перехватил строку.
MAX_AGE_SECONDS = 24 * 60 * 60


class InvalidInitData(ValueError):
    """Данные не прошли проверку. Причина НЕ раскрывается наружу.

    Подробность вида «подпись верна, но истёк срок» помогает подбирать; в
    лог она идёт, в ответ пользователю — нет.
    """


@dataclass(frozen=True)
class WebAppUser:
    id: int
    username: str | None
    first_name: str | None
    language_code: str | None


def _secret_key(bot_token: str) -> bytes:
    # Ключ — строка "WebAppData", сообщение — токен. Именно в таком порядке.
    return hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()


def check_signature(init_data: str, bot_token: str) -> bool:
    """Сходится ли подпись. Без проверки срока — только криптография."""
    if not init_data or not bot_token:
        return False

    pairs = parse_qsl(init_data, keep_blank_values=True)
    received = dict(pairs).get("hash", "")
    if not received:
        return False

    check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(pairs) if key != "hash"
    )
    expected = hmac.new(
        _secret_key(bot_token), check_string.encode(), hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, received)


def parse_init_data(
    init_data: str, bot_token: str, *, max_age: int = MAX_AGE_SECONDS,
) -> WebAppUser:
    """Проверить подпись и срок, вернуть пользователя.

    Бросает `InvalidInitData` на любой проблеме — вызывающий не должен
    решать, какая из них «не страшная».
    """
    if not check_signature(init_data, bot_token):
        raise InvalidInitData("подпись не сходится")

    values = dict(parse_qsl(init_data, keep_blank_values=True))

    raw_date = values.get("auth_date", "")
    if not raw_date.isdigit():
        raise InvalidInitData("нет auth_date")
    age = time.time() - int(raw_date)
    if age > max_age:
        raise InvalidInitData(f"данные старше {max_age} с")
    if age < -60:
        # Дата из будущего означает подкрученные часы на клиенте или
        # попытку продлить срок; минута запаса покрывает расхождение часов.
        raise InvalidInitData("auth_date из будущего")

    try:
        user = json.loads(values.get("user", "{}"))
    except json.JSONDecodeError as exc:
        raise InvalidInitData("user не разбирается") from exc
    if not isinstance(user, dict) or not isinstance(user.get("id"), int):
        raise InvalidInitData("в данных нет пользователя")

    return WebAppUser(
        id=user["id"],
        username=user.get("username"),
        first_name=user.get("first_name"),
        language_code=user.get("language_code"),
    )


def engage_bot_token() -> str:
    """Токен, которым Telegram подписал данные мини-аппа."""
    from engage.config import get_engage_settings

    return get_engage_settings().engage_bot_token
