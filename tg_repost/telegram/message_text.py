"""Полный текст Telegram-сообщения — вместе со скрытыми ссылками.

`message.message` отдаёт ТОЛЬКО видимые символы. Ссылка, оформленная как
гиперссылка на слове (в API — `MessageEntityTextUrl`), в этой строке не
представлена ничем: в тексте остаётся якорь «Github», а сам URL живёт
отдельно, в `message.entities`.

Для нашего пайплайна это значит, что ссылка терялась ещё ДО рерайта: правило
«ссылку на репозиторий сохрани дословно» физически не могло сработать, потому
что модель этой ссылки не видела. Обнаружено по жалобе «ссылки на гитхаб не
сохраняются» — в БД у постов таких ссылок не было вообще ни одной.

Смещения entity Telegram считает в UTF-16 code units (та же мера, что у
лимитов подписи), а не в питоновских символах: один эмодзи в тексте сдвигает
их на две единицы. Поэтому режем по UTF-16, а не по `str`.
"""

from __future__ import annotations

from typing import Any

# Ссылка дописывается сразу после якоря, в скобках: и человеку читаемо, и
# `extract_article_urls`/промпт видят обычный URL в тексте.
_TEMPLATE = "{anchor} ({url})"


def _utf16_slice(units: bytes, start: int, end: int) -> str:
    return units[start * 2 : end * 2].decode("utf-16-le", errors="ignore")


def expand_hidden_links(text: str, entities: list[Any] | None) -> str:
    """Вернуть текст, в котором скрытые ссылки раскрыты в явные URL.

    Пример: якорь «Github» с url `https://github.com/foo/bar` превращается в
    `Github (https://github.com/foo/bar)`.

    Не трогает entity без `url` (жирный шрифт, упоминания, код) и не дублирует
    ссылку, если она и так уже присутствует в тексте видимым URL.
    """
    if not text or not entities:
        return text

    units = text.encode("utf-16-le")
    total_units = len(units) // 2

    # Собираем замены, потом применяем С КОНЦА — иначе первая же вставка
    # сдвинет смещения всех последующих entity.
    replacements: list[tuple[int, int, str]] = []
    for entity in entities:
        url = getattr(entity, "url", None)
        offset = getattr(entity, "offset", None)
        length = getattr(entity, "length", None)
        if not url or offset is None or length is None:
            continue
        end = offset + length
        if offset < 0 or end > total_units or length <= 0:
            continue  # битые смещения — молча пропускаем, текст важнее

        anchor = _utf16_slice(units, offset, end)
        if url in text or url == anchor:
            continue  # ссылка и так видна — второй раз не пишем
        replacements.append((offset, end, _TEMPLATE.format(anchor=anchor, url=url)))

    if not replacements:
        return text

    # Идём С КОНЦА: тогда смещения ещё не обработанных entity (они все левее)
    # остаются валидными, а «хвост» уже включает предыдущие раскрытия.
    result = text
    for offset, end, expanded in sorted(replacements, reverse=True):
        units = result.encode("utf-16-le")
        head = _utf16_slice(units, 0, offset)
        tail = _utf16_slice(units, end, len(units) // 2)
        result = f"{head}{expanded}{tail}"

    return result
