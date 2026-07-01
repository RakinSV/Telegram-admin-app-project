"""Генерация капчи при вступлении нового участника (G01).

Три типа, переключаются `CAPTCHA_TYPE`:
- `math`     — «Сколько будет 7 + 4?», 4 кнопки (1 верная + 3 случайных).
- `button`   — одна кнопка «Я не робот» — минимальный порог, блокирует
               простых ботов, не читающих сообщение.
- `question` — тематический вопрос из `bot_config` (ключ `captcha_questions`,
               JSON-список `{"question", "answer", "wrong": [...]}`),
               ротация случайным выбором. Если список не настроен —
               откатываемся на `math` (не ломаем верификацию из-за пустого
               конфига).

`generate_captcha()` возвращает ВСЁ разом (вопрос/ответ/тип/неверные
варианты) одним вызовом — `make_captcha_keyboard()` только рендерит уже
готовый набор, не обращается к БД повторно. Более ранний вариант дважды
запрашивал `question`-конфиг (один раз в generate, второй в make_keyboard)
и мог случайно выбрать ДРУГОЙ вопрос при повторном random.choice —
сознательно исправлено объединением в один шаг.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.orm import Session

from guardian.db.models import BotConfig

_CAPTCHA_PREFIX = "captcha"
BUTTON_VERIFIED_VALUE = "verified"


@dataclass(frozen=True)
class Captcha:
    question: str
    correct_answer: str
    captcha_type: str  # фактически использованный тип (после возможного отката на math)
    wrong_options: tuple[str, ...]


def _math_captcha() -> Captcha:
    a, b = random.randint(1, 9), random.randint(1, 9)
    correct = a + b
    candidates = sorted({correct + d for d in (-3, -2, -1, 1, 2, 3)} - {correct})
    wrong = [str(v) for v in random.sample(candidates, k=3)]
    return Captcha(f"Сколько будет {a} + {b}?", str(correct), "math", tuple(wrong))


def _button_captcha() -> Captcha:
    return Captcha(
        "Нажми кнопку ниже, чтобы подтвердить, что ты не бот:",
        BUTTON_VERIFIED_VALUE,
        "button",
        (),
    )


def _question_captcha(session: Session | None) -> Captcha:
    """Поднимает ValueError, если конфиг `captcha_questions` пуст/невалиден —
    вызывающий код (`generate_captcha`) обязан откатиться на `math`."""
    if session is None:
        raise ValueError("question-капча требует сессию БД")
    row = (
        session.query(BotConfig)
        .filter(BotConfig.key == "captcha_questions")
        .one_or_none()
    )
    if row is None:
        raise ValueError("captcha_questions не настроен")
    try:
        options = json.loads(row.value)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("captcha_questions содержит невалидный JSON") from exc
    if not options:
        raise ValueError("captcha_questions пуст")
    chosen = random.choice(options)
    wrong = tuple(str(w) for w in chosen.get("wrong", []))[:3]
    return Captcha(str(chosen["question"]), str(chosen["answer"]), "question", wrong)


def generate_captcha(captcha_type: str, session: Session | None = None) -> Captcha:
    if captcha_type == "button":
        return _button_captcha()
    if captcha_type == "question":
        try:
            return _question_captcha(session)
        except ValueError:
            pass  # осознанный откат на math — см. docstring модуля
    return _math_captcha()


def make_captcha_keyboard(
    captcha: Captcha, target_user_id: int
) -> tuple[InlineKeyboardMarkup, list[str]]:
    """Вернуть (клавиатура, порядок_вариантов).

    `callback_data` кодирует ЦЕЛЕВОГО пользователя (`target_user_id`, тот, для
    кого сгенерирована капча) и ИНДЕКС варианта в списке, а не сам текст
    ответа — так `callback_data` остаётся коротким независимо от длины
    текста (важно для `question`-типа с произвольными ответами админа, лимит
    Telegram на callback_data — 64 байта) и даёт `join.py` явно и дёшево
    проверить, что кликнувший — это и есть `target_user_id`, до любого
    обращения к состоянию. Порядок вариантов возвращается отдельно, чтобы
    вызывающий код мог сохранить его и позже сопоставить индекс с ответом —
    `Captcha.wrong_options` сам по себе не хранит порядок показа (он
    перемешивается здесь).
    """
    if captcha.captcha_type == "button":
        options = [BUTTON_VERIFIED_VALUE]
        button = InlineKeyboardButton(
            text="✅ Я не робот",
            callback_data=f"{_CAPTCHA_PREFIX}:{target_user_id}:0",
        )
        return InlineKeyboardMarkup(inline_keyboard=[[button]]), options

    options = [captcha.correct_answer, *captcha.wrong_options]
    random.shuffle(options)
    buttons = [
        InlineKeyboardButton(
            text=opt, callback_data=f"{_CAPTCHA_PREFIX}:{target_user_id}:{i}"
        )
        for i, opt in enumerate(options)
    ]
    # По 2 кнопки в ряд — читаемо на мобильном экране Telegram.
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(inline_keyboard=rows), options
