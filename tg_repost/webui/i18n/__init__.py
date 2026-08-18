"""Двуязычный (RU/EN) слой текста веб-админки.

Один источник истины для ВСЕХ строк UI — и статичного текста шаблонов
(`{{ t('nav.dashboard') }}`), и динамического текста, собираемого в Python
(заголовки/описания групп настроек, лейблы секретов и т.п. — резолвятся
через `t()` в `webui/app.py`/`webui/crud_routes.py`/`webui/guardian_routes.py`
ДО передачи в шаблон, а не в самом шаблоне, т.к. эти строки приходят как уже
собранный контекст, а не как статичная разметка).

Текущий язык — per-request: middleware в `app.py` читает
`request.session["lang"]` (по умолчанию `"ru"`) и на время обработки запроса
выставляет `ContextVar` — асинхронно-безопасно (каждый HTTP-запрос Starlette
обрабатывает в своей asyncio Task, `ContextVar` копируется per-task, гонки
между параллельными запросами разных админов исключены).
"""

from __future__ import annotations

from contextvars import ContextVar

SUPPORTED_LANGS: tuple[str, ...] = ("ru", "en")
DEFAULT_LANG = "ru"

_current_lang: ContextVar[str] = ContextVar("current_lang", default=DEFAULT_LANG)


def set_current_lang(lang: str) -> None:
    """Выставить текущий язык для этого request/task (вызывается middleware)."""
    _current_lang.set(lang if lang in SUPPORTED_LANGS else DEFAULT_LANG)


def get_current_lang() -> str:
    return _current_lang.get()


def normalize_lang(lang: str | None) -> str:
    """Привести произвольную строку к поддерживаемому коду языка —
    используется и middleware (значение из сессии), и роутом `/lang/{code}`
    (значение из URL, ещё не провалидированное)."""
    return lang if lang in SUPPORTED_LANGS else DEFAULT_LANG


def humanize_action(action: str, namespace: str = "audit.action") -> str:
    """Человекочитаемый лейбл для сырого ключа действия из `audit_log`/
    `guardian.ModerationLog` (например `source_add` → «Добавлен источник»).
    Такие ключи — внутренние snake_case-идентификаторы, читаемые
    разработчику, но не конечному пользователю (найдено при аудите UI).
    В отличие от `t()`, при отсутствии перевода возвращает САМ `action`
    (не `[key]`-заглушку) — это runtime-значение из БД, а не забытый ключ
    каталога, ломать вид таблицы плейсхолдером не нужно.

    `namespace` переключает каталог между `audit.action.*` (tg_repost
    audit_log) и `guardian_dashboard.action.*` (Guardian ModerationLog) —
    разные наборы событий, разные префиксы ключей."""
    entry = STRINGS.get(f"{namespace}.{action}")
    if entry is None:
        return action
    return entry.get(get_current_lang(), entry.get(DEFAULT_LANG, action))


def t(key: str, **kwargs: object) -> str:
    """Перевести строку по ключу на текущий язык (см. `get_current_lang()`).

    Отсутствующий ключ — не 500-я и не пустая строка (это ломало бы UI молча
    и было бы незаметно при рерайте копирайтинга), а сам ключ в квадратных
    скобках — сразу видно на странице/в тесте, что перевод забыли добавить.
    `**kwargs` — простая `.format()`-подстановка для строк со счётчиками
    (например `t("audit.footer", total=42, page=1, pages=3)`).
    """
    entry = STRINGS.get(key)
    if entry is None:
        return f"[{key}]"
    text = entry.get(get_current_lang(), entry.get(DEFAULT_LANG, f"[{key}]"))
    return text.format(**kwargs) if kwargs else text


def opt(key: str, **kwargs: object) -> str:
    """Как `t()`, но для НЕОБЯЗАТЕЛЬНЫХ строк: отсутствующий ключ даёт пустую
    строку, а не `[ключ]`.

    Нужно для подсказок к полям настроек: их около сотни, подсказка осмысленна
    далеко не у каждого поля (у `stats_window_days` название говорит само за
    себя), а `t()` вывалил бы в интерфейс `[settings.field.x.hint]` для всех
    полей без подсказки. Шаблон рендерит блок подсказки только при непустом
    результате.

    Для ОБЯЗАТЕЛЬНЫХ строк по-прежнему `t()` — там молчаливое исчезновение
    текста как раз то, чего мы избегаем.
    """
    entry = STRINGS.get(key)
    if entry is None:
        return ""
    text = entry.get(get_current_lang(), entry.get(DEFAULT_LANG, ""))
    return text.format(**kwargs) if (text and kwargs) else text


# ---------------------------------------------------------------------------
# Каталог строк. Организован по разделам приложения, не по языку — так легко
# видеть RU/EN пару рядом и не разойтись в смысле при правке одного языка.
# ---------------------------------------------------------------------------

# --- Каталог строк ---
#
# РАЗБИТ НА ЧАСТИ ПО ТЕМАМ. Одним файлом он вырос до 4239 строк и правился
# почти в каждой фиче — там же случались и самые обидные ошибки: дубль ключа
# `flows.published` перекрыл заголовок столбца, и заметить это можно было
# только глазами на странице. Части собираются здесь, а проверка на повтор
# ключа между ними стоит в тестах.

from tg_repost.webui.i18n import audience as _audience  # noqa: E402
from tg_repost.webui.i18n import common as _common  # noqa: E402
from tg_repost.webui.i18n import content as _content  # noqa: E402
from tg_repost.webui.i18n import flows as _flows  # noqa: E402
from tg_repost.webui.i18n import guardian as _guardian  # noqa: E402
from tg_repost.webui.i18n import money as _money  # noqa: E402
from tg_repost.webui.i18n import settings as _settings  # noqa: E402
from tg_repost.webui.i18n import system as _system  # noqa: E402

_PARTS = (
    _common, _content, _audience, _money, _flows, _guardian, _settings, _system,
)

STRINGS: dict[str, dict[str, str]] = {}
for _part in _PARTS:
    STRINGS.update(_part.STRINGS)
