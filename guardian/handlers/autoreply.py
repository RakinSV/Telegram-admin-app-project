"""Автоответчик по ключевым словам (F45).

Снимает с админа рутину: «как купить», «где правила», «когда стрим» задают
каждый день, и каждый день их приходится отвечать вручную.

Главная опасность такой фичи — превратить бота в назойливого болтуна. Поэтому
три ограничителя:
1. Срабатывание по СЛОВУ целиком, а не по подстроке: правило «стрим» не должно
   стрелять на «экстримальный».
2. Пауза на правило и чат: если десять человек подряд спросят одно и то же,
   бот ответит один раз.
3. Ответ только на сообщения обычных участников — не на свои и не на других
   ботов, иначе два бота устроят бесконечный обмен.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass

from aiogram import Bot, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

from guardian.config import get_guardian_settings
from guardian.logging_conf import get_logger

logger = get_logger(__name__)
router = Router(name="autoreply")

# Когда последний раз отвечали по каждому правилу в каждом чате:
# (chat_id, триггер) → момент времени. В памяти процесса намеренно: пауза
# нужна против серии одинаковых вопросов подряд, а после рестарта ответить
# один лишний раз не страшно — БД ради этого не нужна.
_last_reply: dict[tuple[int, str], float] = {}


@dataclass(frozen=True)
class Rule:
    """Одно правило: список триггеров → ответ."""

    triggers: list[str]
    reply: str


def parse_rules(raw: str) -> list[Rule]:
    """Разобрать правила из настройки (JSON-массив).

    Формат: `[{"triggers": ["правила", "rules"], "reply": "Правила в закрепе"}]`
    Кривой JSON — не повод падать: вернём пусто и напишем в лог, автоответчик
    просто промолчит.
    """
    if not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("Правила автоответчика не разобраны: %s", exc)
        return []
    if not isinstance(data, list):
        return []

    rules: list[Rule] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        raw_triggers = item.get("triggers")
        reply = str(item.get("reply") or "").strip()
        if not isinstance(raw_triggers, list) or not reply:
            continue
        triggers = [str(t).strip().lower() for t in raw_triggers if str(t).strip()]
        if triggers:
            rules.append(Rule(triggers=triggers, reply=reply))
    return rules


def find_match(text: str, rules: list[Rule]) -> Rule | None:
    """Первое правило, чей триггер встречается в тексте ОТДЕЛЬНЫМ словом.

    Подстрока не годится: правило «стрим» стреляло бы на «экстримальный», а
    «бан» — на «банан». `\\b` по краям и есть вся разница между полезным
    автоответчиком и раздражающим.
    """
    lowered = text.lower()
    for rule in rules:
        for trigger in rule.triggers:
            if re.search(rf"\b{re.escape(trigger)}\b", lowered):
                return rule
    return None


def _cooldown_passed(chat_id: int, trigger: str, cooldown_seconds: int) -> bool:
    key = (chat_id, trigger)
    # Отсутствие ключа — это «ещё ни разу не отвечали», и его нельзя
    # подменять нулём: time.monotonic() отсчитывается от старта машины, и
    # сразу после загрузки он сам по себе меньше кулдауна. С нулём по
    # умолчанию `monotonic() - 0 < cooldown` было бы истиной, и бот молчал
    # бы первые cooldown_seconds (по умолчанию 10 минут) после каждого
    # рестарта — по всем правилам сразу.
    last = _last_reply.get(key)
    if last is not None and time.monotonic() - last < cooldown_seconds:
        return False
    _last_reply[key] = time.monotonic()
    return True


@router.message()
async def on_message(message: Message, bot: Bot) -> None:
    """Ответить, если сообщение попало под правило."""
    del bot
    settings = get_guardian_settings()
    if not settings.autoreply_enabled:
        return
    if message.chat.id not in settings.protected_chat_ids:
        return
    # Не отвечаем ботам (включая себя): иначе два бота могут устроить
    # бесконечный обмен репликами.
    if message.from_user is None or message.from_user.is_bot:
        return
    text = message.text or message.caption or ""
    if not text.strip():
        return

    rule = find_match(text, parse_rules(settings.autoreply_rules))
    if rule is None:
        return
    if not _cooldown_passed(
        message.chat.id, rule.triggers[0], settings.autoreply_cooldown_seconds,
    ):
        return

    try:
        await message.reply(rule.reply, disable_notification=True)
    except TelegramBadRequest as exc:
        logger.warning("Автоответ не отправлен в %s: %s", message.chat.id, exc)
