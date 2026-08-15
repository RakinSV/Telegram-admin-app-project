"""UTM-метки на исходящих ссылках (F59).

Если канал гонит трафик на сайт, сейчас невозможно понять, какой пост принёс
переходы. Метки это чинят: внешняя аналитика видит источник.

НЕ ДУБЛЬ связки «вариант → просмотры» (F53 и `post_variants`): та про то,
что происходит ВНУТРИ Telegram, эта — про то, что снаружи.

ГЛАВНЫЙ РИСК ЗДЕСЬ — ИСПОРТИТЬ ТЕКСТ ПОСТА. Пост уходит подписчикам один
раз, и битая ссылка в нём — это не «поправим и перевыложим», а потерянные
переходы и вопрос «что у вас с ссылками». Поэтому разбор консервативный:

* трогаются только `http`/`https` — никаких `t.me`-схем и упоминаний;
* **ссылки на Telegram не размечаются вообще**: метки там бессмысленны, а
  инвайт-ссылку с лишним параметром Telegram может и не принять;
* ссылка, где уже есть `utm_source`, остаётся как есть — иначе повторная
  публикация (F55) удвоила бы метки;
* существующие параметры и якорь сохраняются: ссылка с `?ref=abc#section`
  должна остаться рабочей.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Хвостовые знаки препинания в ссылку не входят: «сайт example.com/статья.»
# — точка здесь конец предложения, а не часть адреса.
_URL_RE = re.compile(r"https?://[^\s<>\[\]()«»\"']+")
_TRAILING = ".,;:!?»\"'"

# Домены, которые не размечаем. Метки на них бессмысленны (внешняя аналитика
# их не увидит), а инвайт-ссылку лишний параметр может сломать.
_SKIP_HOSTS = ("t.me", "telegram.me", "telegram.org", "telegra.ph")


def _should_skip(url: str) -> bool:
    host = urlsplit(url).hostname or ""
    host = host.lower()
    return any(host == skip or host.endswith("." + skip) for skip in _SKIP_HOSTS)


def add_utm(url: str, params: dict[str, str]) -> str:
    """Добавить метки к одной ссылке, сохранив всё остальное."""
    if not params or _should_skip(url):
        return url

    parts = urlsplit(url)
    existing = parse_qsl(parts.query, keep_blank_values=True)
    if any(key == "utm_source" for key, _ in existing):
        # Уже размечена — повторная публикация не должна удваивать метки.
        return url

    merged = existing + [(key, value) for key, value in params.items() if value]
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(merged), parts.fragment)
    )


def tag_links(text: str, params: dict[str, str]) -> str:
    """Разметить все внешние ссылки в тексте.

    Текст возвращается как есть, если меток нет или ссылок не нашлось —
    лишняя обработка тут ничего не даёт, а риск сломать разметку есть.
    """
    if not text or not params:
        return text

    def _replace(match: re.Match[str]) -> str:
        url = match.group(0)
        # Знаки препинания, прилипшие к концу, возвращаем в текст: иначе
        # «читайте на example.com/пост.» превратится в ссылку с точкой.
        tail = ""
        while url and url[-1] in _TRAILING:
            tail = url[-1] + tail
            url = url[:-1]
        return add_utm(url, params) + tail

    return _URL_RE.sub(_replace, text)


def build_params(
    *,
    source: str,
    medium: str,
    campaign_template: str,
    post_id: int | None = None,
) -> dict[str, str]:
    """Собрать метки. `{post_id}` в шаблоне кампании подставляется.

    Именно `post_id`, а не дата: в отчёте внешней аналитики он однозначно
    указывает на конкретный пост, тогда как «2026-08-15» смешает все посты
    одного дня.
    """
    campaign = campaign_template
    if "{post_id}" in campaign:
        campaign = campaign.replace("{post_id}", str(post_id) if post_id else "")
    return {
        "utm_source": source.strip(),
        "utm_medium": medium.strip(),
        "utm_campaign": campaign.strip(),
    }
