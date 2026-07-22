"""Загрузка и разбор RSS/Atom-ленты.

`feedparser` берёт на себя разницу между RSS 0.9x/1.0/2.0 и Atom, включая
разнобой в датах и полях — писать это руками на `xml.etree` означало бы
чинить по одному формату за раз.

Сеть отделена от разбора: `parse_feed()` — чистая функция над байтами, её
можно тестировать без запросов наружу.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

import feedparser  # type: ignore[import-untyped]  # библиотека без аннотаций
import httpx

from tg_repost.enrichment.link_content import safe_get_stream
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)

# Тот же UA, что в enrichment/link_content.py: часть сайтов отдаёт 403 на
# «неживые» клиенты, и ленты здесь не исключение.
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_ACCEPT = "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"
_MAX_FEED_BYTES = 5_000_000
# Описание записи режем: в ленту иногда кладут статью целиком, а нам нужен
# только повод — полный текст всё равно добирается переходом по ссылке
# (см. enrichment/link_content.py).
_MAX_SUMMARY_CHARS = 2000

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t]+")


@dataclass(frozen=True)
class FeedItem:
    """Одна запись ленты, уже приведённая к тексту."""

    guid: str          # уникальный ключ записи (id/guid, иначе ссылка)
    title: str
    summary: str
    link: str

    def as_post_text(self) -> str:
        """Текст будущего поста: заголовок, краткое описание и ссылка.

        Ссылка кладётся в текст намеренно: дальше её подхватит
        `extract_article_urls()` и рерайт пойдёт по ПОЛНОЙ статье, а не по
        куцему описанию из ленты. То есть RSS попадает в тот же сценарий
        «настоящего рерайта», что и Telegram-пост со ссылкой.
        """
        parts = [self.title.strip()]
        if self.summary.strip():
            parts.append(self.summary.strip())
        if self.link.strip():
            parts.append(self.link.strip())
        return "\n\n".join(p for p in parts if p)


def strip_html(raw: str) -> str:
    """HTML описания → плоский текст."""
    if not raw:
        return ""
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    text = re.sub(r"(?i)<br\s*/?>|</p>", "\n", text)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = _WS_RE.sub(" ", text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip()).strip()


def parse_feed(raw: bytes) -> list[FeedItem]:
    """Байты ленты → список записей (чистая функция, без сети).

    Записи без ссылки и без заголовка пропускаются: постить нечего, а
    дедуплицировать не по чему.
    """
    parsed = feedparser.parse(raw)
    items: list[FeedItem] = []
    for entry in parsed.entries:
        link = (entry.get("link") or "").strip()
        title = strip_html(entry.get("title") or "").strip()
        if not link and not title:
            continue

        # Описание бывает в summary, а бывает в content[0].value (Atom).
        summary_raw = entry.get("summary") or ""
        content = entry.get("content") or []
        if content and getattr(content[0], "get", None):
            summary_raw = content[0].get("value") or summary_raw
        summary = strip_html(summary_raw)[:_MAX_SUMMARY_CHARS]

        # guid: id → link → title. Он и есть ключ дедупликации, поэтому
        # пустым остаться не должен.
        guid = (entry.get("id") or link or title).strip()
        items.append(FeedItem(guid=guid, title=title, summary=summary, link=link))
    return items


async def fetch_feed(url: str) -> list[FeedItem]:
    """Скачать и разобрать ленту. Пустой список при любой проблеме —
    недоступная лента не должна ронять опрос остальных."""
    headers = {"User-Agent": _USER_AGENT, "Accept": _ACCEPT}
    try:
        # Через `safe_get_stream`, а не голым `client.get(follow_redirects=True)`:
        # адрес ленты задаёт владелец, но КУДА она редиректит — уже нет, а
        # ответ по редиректу попадает в очередь модерации как текст поста.
        # Тот же гард, что у перехода по ссылкам из постов, — не хотим
        # держать в проекте единственный HTTP-клиент без проверки адреса.
        async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
            response = await safe_get_stream(client, url)
            if response is None:
                return []
            try:
                response.raise_for_status()
                raw = (await response.aread())[:_MAX_FEED_BYTES]
            finally:
                await response.aclose()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Лента недоступна (%s): %s", url, exc)
        return []

    try:
        items = parse_feed(raw)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Лента не разобрана (%s): %s", url, exc)
        return []

    if not items:
        logger.warning("Лента пуста или не распознана как RSS/Atom: %s", url)
    return items
