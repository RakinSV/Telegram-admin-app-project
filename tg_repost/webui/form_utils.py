"""Общие хелперы обработки HTML-форм веб-админки — используется и `app.py`
(настройки репост-бота), и `guardian_routes.py` (настройки Guardian).
Вынесено в отдельный модуль, а не оставлено в `app.py`, чтобы избежать
кругового импорта (`guardian_routes.py` регистрируется ИЗ `app.py`, поэтому
не может импортировать что-то обратно из него)."""

from __future__ import annotations


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
        return int(text) if text.strip() else 0
    if value_type == "float":
        return float(text) if text.strip() else 0.0
    if value_type == "csv_list":
        return [s.strip() for s in text.split(",") if s.strip()]
    return text
