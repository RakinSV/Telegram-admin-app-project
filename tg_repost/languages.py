"""Язык публикации: справочник и инструкция для рерайта.

Язык выбирается У ЦЕЛЕВОЙ ГРУППЫ (`TargetGroup.language`), а не у источника:
один и тот же источник может кормить и русские, и англоязычные группы, и
решение «на каком языке говорить» принадлежит аудитории, а не поводу.

Отсюда следствие для пайплайна: пост, который уходит в группы с РАЗНЫМИ
языками, требует по рерайту на каждый язык — одним текстом их не обслужить
(см. `scheduler/jobs.py::rewrite_new_posts` и
`telegram/publisher.py::publish_post`).

Модуль намеренно без зависимостей от БД и конфига: его импортируют и модели,
и рерайтер, и веб-слой.
"""

from __future__ import annotations

# Код языка → (название в админке, как называть его модели в промпте).
# Коды короткие и стабильные: они лежат в БД у каждой цели и у каждого
# варианта рерайта, менять их потом дороже, чем подписи.
LANGUAGES: dict[str, tuple[str, str]] = {
    "ru": ("Русский", "русском"),
    "en": ("English", "English"),
}

DEFAULT_LANGUAGE = "ru"

LANGUAGE_CODES: tuple[str, ...] = tuple(LANGUAGES)


def normalize(code: str | None) -> str:
    """Привести код языка к известному, иначе — язык по умолчанию.

    Незнакомый код не должен ронять публикацию: цель могла быть заведена
    старой версией или значение поправили руками в БД.
    """
    if code and code.strip().lower() in LANGUAGES:
        return code.strip().lower()
    return DEFAULT_LANGUAGE


def label(code: str | None) -> str:
    """Название языка для интерфейса."""
    return LANGUAGES[normalize(code)][0]


def instruction(code: str | None) -> str:
    """Строка-инструкция для промпта рерайта.

    Ставится последней и сформулирована жёстко: модель, получив материал на
    одном языке, по умолчанию отвечает на нём же, и мягкая просьба
    («желательно по-английски») сплошь и рядом игнорируется.
    """
    normalized = normalize(code)
    if normalized == "ru":
        return (
            "ЯЗЫК ОТВЕТА: пиши на русском языке. Даже если исходный материал "
            "на другом языке — готовый пост должен быть полностью на русском."
        )
    return (
        "LANGUAGE: write the final post entirely in English. The source "
        "material may be in another language — translate and rewrite it, do "
        "not answer in the source language."
    )
