"""Из чего состоит узел: поля, которые владелец заполняет в конструкторе (F75).

СХЕМА ЖИВЁТ НА СЕРВЕРЕ, А НЕ В JAVASCRIPT. Движок читает конфигурацию узла по
именам ключей. Нарисуй холст поле «сообщение» там, где движок ждёт «text», — и
узел молча отправит человеку пустую строку. Одно описание питает и форму на
холсте, и проверку перед публикацией.

ОБЯЗАТЕЛЬНОСТЬ ПОЛЯ — ЧАСТЬ СХЕМЫ, А НЕ ПРОВЕРКА В ФОРМЕ. Незаполненный
`file_id` у видео виден только в бою: узел «показать видео» без файла ничего
не покажет, а человек будет ждать. Поэтому список обязательных полей
проверяется при публикации, вместе с графом.
"""

from __future__ import annotations

from dataclasses import dataclass

# Как поле выглядит и как разбирается. Типов ровно столько, сколько нужно
# двенадцати узлам: лишние варианты пришлось бы поддерживать и в холсте.
LINE = "line"        # одна строка
TEXT = "text"        # многострочный текст
NUMBER = "number"
CHOICE = "choice"    # выбор из фиксированного списка
LIST = "list"        # список строк — варианты ответа теста
BUTTONS = "buttons"  # список пар «подпись → значение»
CHAT = "chat"        # идентификатор чата: подсказка со списком известных

# Категории узлов — те же четыре, что у чужих конструкторов, и по той же
# причине: человек ищет узел по тому, ЧТО тот делает с диалогом.
CAT_SHOW = "show"
CAT_ASK = "ask"
CAT_WAIT = "wait"
CAT_DECIDE = "decide"
CAT_DO = "do"
CATEGORIES = (CAT_SHOW, CAT_ASK, CAT_WAIT, CAT_DECIDE, CAT_DO)

# Операторы условия. Список берётся отсюда и холстом, и переводами; сам разбор
# живёт в `flow_engine._evaluate` — там же, где применяется.
OPERATORS = ("eq", "ne", "contains", "gt", "lt", "is_set", "is_empty")


@dataclass(frozen=True)
class Field:
    name: str
    kind: str
    required: bool = False
    choices: tuple[str, ...] = ()
    # Значение по умолчанию для нового узла: срок ответа в сутки лучше, чем
    # пустое поле, которое владелец пропустит, а прохождения зависнут.
    default: object = None


@dataclass(frozen=True)
class NodeKind:
    category: str
    fields: tuple[Field, ...]


_TIMEOUT = Field("timeout_hours", NUMBER, default=24)
_CAPTION = Field("caption", TEXT)


def _media(*, required_file: bool = True) -> tuple[Field, ...]:
    return (Field("file_id", LINE, required=required_file), _CAPTION)


KINDS: dict[str, NodeKind] = {
    "show_text": NodeKind(CAT_SHOW, (Field("text", TEXT, required=True),)),
    "show_photo": NodeKind(CAT_SHOW, _media()),
    "show_video": NodeKind(CAT_SHOW, _media()),
    "show_document": NodeKind(CAT_SHOW, _media()),
    "ask_buttons": NodeKind(CAT_ASK, (
        Field("text", TEXT, required=True),
        Field("buttons", BUTTONS, required=True),
        _TIMEOUT,
    )),
    "ask_quiz": NodeKind(CAT_ASK, (
        Field("question", TEXT, required=True),
        Field("options", LIST, required=True),
        Field("correct_index", NUMBER, required=True, default=0),
        Field("explanation", TEXT),
        # Текст на ошибку отдельный: пояснение к верному ответу («Верно,
        # четыре») человеку, который ошибся, читается как похвала за промах.
        Field("wrong_text", TEXT),
        _TIMEOUT,
    )),
    "ask_text": NodeKind(CAT_ASK, (
        Field("text", TEXT, required=True),
        # Имя переменной: под ним ответ запомнится и по нему потом ветвиться.
        Field("variable", LINE, required=True),
        _TIMEOUT,
    )),
    "wait_timer": NodeKind(CAT_WAIT, (
        Field("hours", NUMBER, required=True, default=24),
    )),
    "decide_condition": NodeKind(CAT_DECIDE, (
        Field("variable", LINE, required=True),
        Field("operator", CHOICE, required=True, choices=OPERATORS, default="eq"),
        Field("value", LINE),
    )),
    "do_tag": NodeKind(CAT_DO, (Field("tag", LINE, required=True),)),
    "do_points": NodeKind(CAT_DO, (
        Field("points", NUMBER, required=True, default=10),
        # Очки геймификации живут ПО ЧАТУ: таблица лидеров у каждой группы
        # своя, и без чата непонятно, в чьём зачёте человек поднялся.
        Field("chat_id", CHAT, required=True),
    )),
    "do_access": NodeKind(CAT_DO, (
        Field("chat_id", CHAT, required=True),
        Field("days", NUMBER, required=True, default=30),
    )),
    "do_webhook": NodeKind(CAT_DO, (Field("payload", TEXT),)),
}

FIELD_NAMES: tuple[str, ...] = tuple(dict.fromkeys(
    field.name for node in KINDS.values() for field in node.fields
))


def problems_in_config(kind: str, config: dict) -> list[str]:
    """Чего не хватает узлу, чтобы он что-то сделал.

    Возвращает ИМЕНА полей, а не готовые фразы: перевод собирается там, где
    известен язык владельца.
    """
    node = KINDS.get(kind)
    if node is None:
        return []
    missing = []
    for field in node.fields:
        if not field.required:
            continue
        value = config.get(field.name)
        if value is None or value == "" or value == [] or value == {}:
            missing.append(field.name)
    return missing


def defaults_for(kind: str) -> dict:
    """Конфигурация нового узла: только осмысленные значения по умолчанию."""
    node = KINDS.get(kind)
    if node is None:
        return {}
    return {
        field.name: field.default
        for field in node.fields
        if field.default is not None
    }
