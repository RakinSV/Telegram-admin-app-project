"""Общие хелперы обработки HTML-форм веб-админки — используется и `app.py`
(настройки репост-бота), и `guardian_routes.py` (настройки Guardian).
Вынесено в отдельный модуль, а не оставлено в `app.py`, чтобы избежать
кругового импорта (`guardian_routes.py` регистрируется ИЗ `app.py`, поэтому
не может импортировать что-то обратно из него)."""

from __future__ import annotations

# SQLite хранит целые в 64 битах. Всё, что больше, при записи даёт
# `OverflowError: Python int too large to convert to SQLite INTEGER` — то
# есть пятисотку и стектрейс вместо формы с ошибкой. Найдено перебором ввода
# 2026-08-19: длинное число в поле «chat_id» на /targets и в цене товара.
DB_INT_MIN = -(2 ** 63)
DB_INT_MAX = 2 ** 63 - 1


def fits_in_db(value: int) -> bool:
    """Влезает ли целое в то, что умеет база."""
    return DB_INT_MIN <= value <= DB_INT_MAX


def parse_db_int(raw: str) -> int | None:
    """Целое из формы, пригодное для записи. `None` — не число или не влезает.

    Одно место на все формы: раньше каждая разбирала число сама и про предел
    базы не помнила ни одна.
    """
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return value if fits_in_db(value) else None


def coerce_form_value(value_type: str, raw: object) -> object:
    """Привести значение HTML-формы к типу настройки (чистая функция).

    Чекбоксы (bool) при снятой галке вообще не попадают в form-data — `raw`
    будет None, что корректно означает False.

    Бросает `ValueError` на нечисловой ввод для int/float — раньше это было
    необработанным исключением прямо в роуте (голый 500 вместо чистой формы
    с ошибкой), найдено при security-аудите Фазы 5.
    """
    if value_type == "bool":
        return raw is not None and str(raw).strip().lower() in {"on", "true", "1"}
    text = "" if raw is None else str(raw)
    if value_type == "int":
        if not text.strip():
            return 0
        value = int(text)
        if not fits_in_db(value):
            # Больше, чем умеет база: без этой проверки запись падала
            # OverflowError уже внутри SQLAlchemy — пятисоткой вместо формы.
            raise ValueError(f"число не влезает в базу: {value}")
        return value
    if value_type == "float":
        if not text.strip():
            return 0.0
        value_f = float(text)
        if value_f != value_f or value_f in (float("inf"), float("-inf")):
            # nan/inf проходят через float() молча и ломают всё дальше.
            raise ValueError(f"недопустимое число: {text}")
        return value_f
    if value_type == "csv_list":
        return [s.strip() for s in text.split(",") if s.strip()]
    return text
