"""Одна точка сборки шаблонов админки.

ЗАЧЕМ. `base.html` один на всю админку, а `Jinja2Templates` заводился в
КАЖДОМ модуле роутов — одиннадцать окружений, и в каждом свой набор
глобальных значений, собранный копированием. Расхождение уже случилось и
жило незамеченным: `SUPPORTED_LANGS` был зарегистрирован только в `app.py`,
поэтому переключатель языка РУ/EN пропадал на всех страницах из остальных
модулей — то есть почти везде. Страница при этом отдавала 200, и ни один
тест этого не видел.

Здесь окружение собирается один раз и одинаково. Новое глобальное значение
добавляется в одном месте и сразу доступно всем страницам.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates
from jinja2 import pass_context

from tg_repost import languages
from tg_repost.webui import access, flash, i18n, nav

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"


@pass_context
def _can_open(context: dict, href: str) -> bool:
    """Откроется ли этот путь текущей роли — для показа пунктов меню.

    ТОЛЬКО ДЛЯ ВНЕШНЕГО ВИДА. Доступ проверяет middleware; прятать ссылку —
    это не защита, а избавление от пунктов, которые всё равно ответят 403.
    Роль читается из сессии через контекст шаблона, потому что глобальная
    функция Jinja о запросе иначе не знает.
    """
    request = context.get("request")
    if request is None:
        return True
    role = request.session.get("role") if hasattr(request, "session") else None
    if role is None:
        # До входа меню и так не показывается; не гадаем и не скрываем.
        return True
    return access.can(role, access.required_role(href))


def _asset_version() -> str:
    """Версия статики: номер выпуска плюс время правки самих файлов.

    Номера выпуска мало: между выпусками статика правится, а во время работы
    над системой — по нескольку раз в день. Время последней правки файлов
    меняется тогда же, когда меняется содержимое, и не требует помнить о
    ручном увеличении номера.
    """
    from tg_repost import __version__

    newest = 0.0
    for path in _STATIC_DIR.glob("*"):
        if path.is_file():
            newest = max(newest, path.stat().st_mtime)
    return f"{__version__}-{int(newest)}"


def build_templates() -> Jinja2Templates:
    """Шаблоны с полным набором глобальных значений."""
    templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))
    templates.env.globals["t"] = i18n.t
    templates.env.globals["SUPPORTED_LANGS"] = i18n.SUPPORTED_LANGS
    templates.env.globals["current_lang"] = i18n.get_current_lang
    templates.env.globals["humanize_action"] = i18n.humanize_action
    # Название языка по коду — нужно и в галерее вариантов на модерации, и в
    # списке целей: держать перевод кодов в шаблонах значило бы размазать
    # справочник языков по HTML.
    templates.env.globals["language_label"] = languages.label
    templates.env.globals["can_open"] = _can_open
    # Одноразовое сообщение после переадресации — см. `webui/flash.py`.
    templates.env.globals["pop_flash"] = flash.pop_flash
    # Метка версии для ссылок на статику. Браузер держит стиль и скрипты в
    # кэше и после обновления системы может крутить ПРОШЛЫЙ файл: стиль
    # разъезжается, а скрипт холста начинает спорить с новыми данными от
    # сервера. Поймано на живой странице — палитра узлов не открывалась,
    # потому что браузер отдал предыдущую версию скрипта.
    templates.env.globals["asset_version"] = _asset_version()
    # Состав меню — данными, а не разметкой; см. `webui/nav.py`.
    # ФУНКЦИЯ, А НЕ ГОТОВЫЙ КОРТЕЖ: иначе состав меню замораживается в момент
    # сборки шаблонов, и защиту «группа без доступных пунктов не рисует
    # заголовок» нечем проверить — подменить набор групп в тесте было бы
    # невозможно.
    templates.env.globals["NAV"] = lambda: nav.NAV
    return templates
