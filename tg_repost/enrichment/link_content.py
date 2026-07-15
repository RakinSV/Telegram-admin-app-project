"""Переход по ссылке из поста для «настоящего» рерайта (F16-доп.).

Telegram-пост часто содержит только короткий тизер и ссылку на полную
статью — рерайт по одному тизеру неизбежно выглядит как синонимайз одного
абзаца, а не пересказ по существу. Если в оригинале есть ссылка, переходим
по ней и вытаскиваем основной текст статьи и её обложку, чтобы LLM
переписывал по ПОЛНОМУ материалу (см. `rewriter/client.py::rewrite`).

SSRF-защита: пост — недоверенный внешний ввод, ссылка в нём может указывать
куда угодно, включая внутреннюю сеть/localhost. Резолвим хост ДО запроса и
отклоняем приватные/loopback/link-local/резервные адреса. Не полная защита
от DNS rebinding (httpx резолвит заново в момент реального соединения), но
соразмерно модели угроз проекта (один админ, сам сервис живёт за
localhost/VPN — см. план Фазы 5) без отдельного pinned-транспорта.

Любая ошибка/пустой результат → None — обогащение никогда не должно ломать
основной рерайт поста.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from tg_repost.config import get_settings
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)

_URL_RE = re.compile(r"https?://[^\s<>\"']+")
# Хвостовые символы, которые обычно не часть URL, а пунктуация вокруг ссылки
# в тексте поста ("... смотри тут: https://example.com/x." — точка не часть пути).
_URL_TRAILING_PUNCT = ").,!?;:»\""

_MAX_DOWNLOAD_BYTES = 3_000_000
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_STRIP_TAGS = ("script", "style", "nav", "footer", "header", "aside", "form", "noscript")
# Абзацы короче этого — обычно меню/подписи/навигация, не тело статьи.
_MIN_PARAGRAPH_LEN = 40

_IMAGE_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


@dataclass(frozen=True)
class LinkContent:
    """Разобранное содержимое страницы по ссылке из поста."""

    url: str
    title: str
    text: str
    image_url: str | None


def extract_first_url(text: str) -> str | None:
    """Первая http(s)-ссылка в тексте поста, либо None."""
    match = _URL_RE.search(text or "")
    if not match:
        return None
    return match.group(0).rstrip(_URL_TRAILING_PUNCT)


def _is_public_host(host: str) -> bool:
    """Хост резолвится ТОЛЬКО в публичные адреса (защита от SSRF)."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    if not infos:
        return False
    for info in infos:
        raw_ip = info[4][0]
        try:
            ip = ipaddress.ip_address(raw_ip)
        except ValueError:
            return False
        if (
            not ip.is_global
            or ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
        ):
            return False
    return True


def _is_safe_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    return _is_public_host(parsed.hostname)


async def _is_safe_url_async(url: str) -> bool:
    """Обёртка `_is_safe_url()` для вызова из async-кода.

    `socket.getaddrinfo()` внутри — БЛОКИРУЮЩИЙ синхронный вызов. Весь
    процесс (Telethon-listener, бот модерации, APScheduler) работает на
    ОДНОМ общем event loop — прямой вызов застопорил бы вообще всё, пока
    идёт DNS-резолв, а не только текущий рерайт (найдено на реальном
    деплое: после включения перехода по ссылкам пайплайн полностью замолкал
    без единой ошибки в логах — event loop был заблокирован синхронным
    резолвом хоста из ссылки в посте). `asyncio.to_thread` уносит это в
    отдельный поток, не трогая event loop."""
    return await asyncio.to_thread(_is_safe_url, url)


def _extract_main_text(soup: BeautifulSoup, max_chars: int) -> str:
    """Грубая эвристика извлечения тела статьи: <article>/<main>, иначе
    весь <body> с вырезанными служебными тегами; абзацы <p> длиннее шума."""
    for tag in soup.find_all(_STRIP_TAGS):
        tag.decompose()
    container = soup.find("article") or soup.find("main") or soup.body or soup

    paragraphs = [p.get_text(" ", strip=True) for p in container.find_all("p")]
    text = "\n".join(p for p in paragraphs if len(p) >= _MIN_PARAGRAPH_LEN)
    if not text:
        text = container.get_text(" ", strip=True)
    return text[:max_chars]


def _extract_image(soup: BeautifulSoup, base_url: str) -> str | None:
    og = soup.find("meta", attrs={"property": "og:image"})
    og_content = og.get("content") if og else None
    if og_content:
        return urljoin(base_url, str(og_content))
    img = soup.find("img", src=True)
    if img:
        return urljoin(base_url, str(img["src"]))
    return None


async def fetch_link_content(url: str) -> LinkContent | None:
    """Скачать и разобрать HTML-страницу по ссылке. None при любой проблеме."""
    if not await _is_safe_url_async(url):
        logger.debug("Ссылка отклонена (не http(s) либо непубличный хост): %s", url)
        return None

    settings = get_settings()
    headers = {"User-Agent": _USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
    try:
        async with httpx.AsyncClient(
            timeout=settings.link_fetch_timeout_seconds,
            follow_redirects=True,
            max_redirects=3,
            headers=headers,
        ) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                if "html" not in response.headers.get("content-type", ""):
                    return None
                html_bytes = await _read_capped(response)
                final_url = str(response.url)
                encoding = response.encoding or "utf-8"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Не удалось получить содержимое ссылки %s: %s", url, exc)
        return None

    try:
        html = html_bytes.decode(encoding, errors="ignore")
        soup = BeautifulSoup(html, "html.parser")
        title = soup.title.get_text(strip=True) if soup.title else ""
        text = _extract_main_text(soup, settings.link_content_max_chars)
        image_url = _extract_image(soup, final_url)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Не удалось разобрать содержимое ссылки %s: %s", url, exc)
        return None

    if not text:
        return None
    logger.info(
        "Ссылка в посте разобрана: %s (%d симв. текста, картинка=%s)",
        url, len(text), bool(image_url),
    )
    return LinkContent(url=final_url, title=title, text=text, image_url=image_url)


async def download_link_image(image_url: str) -> tuple[bytes, str] | None:
    """Скачать картинку статьи в память. Возвращает (байты, расширение) или
    None — при ошибке, недопустимом типе содержимого или превышении лимита
    размера. Расширение всегда из белого списка content-type (никогда из
    URL/имени файла, которое полностью контролируется автором исходной
    страницы — та же логика, что в `telegram/listener.py::_safe_media_extension`)."""
    if not await _is_safe_url_async(image_url):
        return None
    try:
        async with httpx.AsyncClient(
            timeout=10.0, follow_redirects=True, max_redirects=3,
            headers={"User-Agent": _USER_AGENT},
        ) as client:
            async with client.stream("GET", image_url) as response:
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").split(";")[0].strip()
                ext = _IMAGE_CONTENT_TYPES.get(content_type)
                if ext is None:
                    return None
                data = await _read_capped(response)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Не удалось скачать картинку статьи %s: %s", image_url, exc)
        return None
    if not data:
        return None
    return data, ext


async def _read_capped(response: httpx.Response) -> bytes:
    """Читать тело ответа потоково, обрывая на `_MAX_DOWNLOAD_BYTES` — защита
    от неограниченной/потоковой отдачи (умышленной или нет) на стороне
    недоверенного внешнего сервера."""
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        chunks.append(chunk)
        total += len(chunk)
        if total >= _MAX_DOWNLOAD_BYTES:
            break
    return b"".join(chunks)
