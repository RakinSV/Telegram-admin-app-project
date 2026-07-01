"""Тесты генерации капчи Guardian (G01) — math/button/question + клавиатура."""

import json
import re

from guardian.db.models import BotConfig
from guardian.db.session import session_scope
from guardian.services.captcha import (
    BUTTON_VERIFIED_VALUE,
    generate_captcha,
    make_captcha_keyboard,
)


def _clear_config() -> None:
    with session_scope() as session:
        session.query(BotConfig).delete()


def test_math_captcha_answer_is_correct_sum():
    captcha = generate_captcha("math")
    assert captcha.captcha_type == "math"
    # "Сколько будет {a} + {b}?" — вытаскиваем числа из вопроса.
    numbers = re.findall(r"\d+", captcha.question)
    assert len(numbers) == 2
    assert str(int(numbers[0]) + int(numbers[1])) == captcha.correct_answer


def test_math_captcha_has_three_distinct_wrong_options():
    captcha = generate_captcha("math")
    assert len(captcha.wrong_options) == 3
    assert len(set(captcha.wrong_options)) == 3
    assert captcha.correct_answer not in captcha.wrong_options


def test_button_captcha():
    captcha = generate_captcha("button")
    assert captcha.captcha_type == "button"
    assert captcha.correct_answer == BUTTON_VERIFIED_VALUE
    assert captcha.wrong_options == ()


def test_question_captcha_falls_back_to_math_when_unconfigured():
    _clear_config()
    captcha = generate_captcha("question")
    assert captcha.captcha_type == "math"


def test_question_captcha_uses_configured_pool():
    _clear_config()
    pool = [
        {
            "question": "Столица Франции?",
            "answer": "Париж",
            "wrong": ["Лондон", "Берлин", "Мадрид"],
        }
    ]
    with session_scope() as session:
        session.add(
            BotConfig(
                key="captcha_questions", value=json.dumps(pool), updated_by="test"
            )
        )
    with session_scope() as session:
        captcha = generate_captcha("question", session=session)
    assert captcha.captcha_type == "question"
    assert captcha.question == "Столица Франции?"
    assert captcha.correct_answer == "Париж"
    assert set(captcha.wrong_options) == {"Лондон", "Берлин", "Мадрид"}


def test_make_captcha_keyboard_button_type_has_one_button():
    captcha = generate_captcha("button")
    kb, options = make_captcha_keyboard(captcha, target_user_id=42)
    all_buttons = [b for row in kb.inline_keyboard for b in row]
    assert len(all_buttons) == 1
    assert options == [BUTTON_VERIFIED_VALUE]
    assert all_buttons[0].callback_data == "captcha:42:0"


def test_make_captcha_keyboard_math_type_has_four_buttons_including_correct():
    captcha = generate_captcha("math")
    kb, options = make_captcha_keyboard(captcha, target_user_id=42)
    all_buttons = [b for row in kb.inline_keyboard for b in row]
    assert len(all_buttons) == 4
    assert set(options) == {captcha.correct_answer, *captcha.wrong_options}
    texts = {b.text for b in all_buttons}
    assert captcha.correct_answer in texts
    assert texts == {captcha.correct_answer, *captcha.wrong_options}


def test_make_captcha_keyboard_callback_data_encodes_target_user_and_index():
    captcha = generate_captcha("math")
    kb, options = make_captcha_keyboard(captcha, target_user_id=999)
    all_buttons = [b for row in kb.inline_keyboard for b in row]
    for button in all_buttons:
        prefix, user_id_str, index_str = button.callback_data.split(":", 2)
        assert prefix == "captcha"
        assert user_id_str == "999"
        assert options[int(index_str)] == button.text
