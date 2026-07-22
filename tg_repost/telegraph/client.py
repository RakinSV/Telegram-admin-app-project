"""Клиент api.telegra.ph — публикация статьи и получение просмотров.

Ключа/регистрации не требуется: `createAccount` выдаёт `access_token` сразу.
Токен нужен, чтобы статью потом можно было ПРАВИТЬ (`editPage`) — без него
страница создаётся, но навсегда становится чужой. Поэтому он сохраняется в
шифрованное хранилище секретов при первом создании.
"""

from __future__ import annotations

import json

import httpx

from tg_repost.config import get_settings, invalidate_settings_cache
from tg_repost.logging_conf import get_logger
from tg_repost.telegraph.nodes import Node

logger = get_logger(__name__)

_API = "https://api.telegra.ph"
# Лимит Telegraph на страницу — 64 КБ. Режем чуть раньше, чтобы служебные
# поля JSON (теги, атрибуты) гарантированно уместились вместе с текстом.
_MAX_CONTENT_BYTES = 60_000


class TelegraphError(RuntimeError):
    """Публикация не удалась. В отличие от обогащения источниками, это НЕ
    «просто без блока»: статьи нет — значит постить в канал нечего, и
    вызывающий код должен решить, откатываться ли на обычный пост."""


async def _call(method: str, payload: dict) -> dict:
    """POST к api.telegra.ph. Бросает TelegraphError на любой неуспех."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(f"{_API}/{method}", json=payload)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:  # noqa: BLE001
        raise TelegraphError(f"{method}: сеть/протокол — {exc}") from exc

    if not data.get("ok"):
        # Ответ 200 с ok=false — штатный способ Telegraph сообщать об ошибке
        # (истёкший токен, слишком большая страница, битый content).
        raise TelegraphError(f"{method}: {data.get('error') or 'неизвестная ошибка'}")
    return data.get("result") or {}


async def create_account(short_name: str, author_name: str) -> str:
    """Завести аккаунт Telegraph, вернуть access_token."""
    result = await _call("createAccount", {
        "short_name": short_name[:32] or "tg_repost",
        "author_name": author_name[:128],
    })
    token = result.get("access_token")
    if not token:
        raise TelegraphError("createAccount не вернул access_token")
    return str(token)


async def get_or_create_token() -> str:
    """Токен из настроек, либо создать аккаунт и сохранить его в секреты.

    Аккаунт заводится ОДИН раз на инсталляцию: потеряв токен, теряешь
    возможность править уже опубликованные статьи (сами страницы остаются
    доступны по своим URL).
    """
    settings = get_settings()
    token = settings.telegraph_access_token.strip()
    if token:
        return token

    author = settings.telegraph_author_name.strip() or "tg_repost"
    token = await create_account(short_name=author, author_name=author)

    # Импорт внутри функции: settings_store тянет за собой веб-слой, а этот
    # модуль зовётся и из пайплайна, где веб не нужен.
    from tg_repost.webui import settings_store

    settings_store.set_secret("telegraph_access_token", token)
    invalidate_settings_cache()
    logger.info("Создан аккаунт Telegraph, токен сохранён в секреты")
    return token


def _encode_content(nodes: list[Node]) -> str:
    """Узлы → JSON-строка для API, с проверкой лимита страницы."""
    content = json.dumps(nodes, ensure_ascii=False)
    size = len(content.encode("utf-8"))
    if size > _MAX_CONTENT_BYTES:
        raise TelegraphError(
            f"статья не помещается в лимит Telegraph: {size} Б при потолке "
            f"{_MAX_CONTENT_BYTES} Б — сократи текст или число картинок",
        )
    return content


async def create_page(title: str, nodes: list[Node]) -> str:
    """Опубликовать статью, вернуть её URL."""
    if not title.strip():
        raise TelegraphError("у статьи нет заголовка")
    if not nodes:
        raise TelegraphError("у статьи пустое содержимое")

    settings = get_settings()
    token = await get_or_create_token()
    result = await _call("createPage", {
        "access_token": token,
        # Telegraph режет заголовок на 256 символов — обрезаем сами, чтобы
        # не получить ошибку вместо страницы.
        "title": title.strip()[:256],
        "author_name": settings.telegraph_author_name.strip()[:128],
        "author_url": settings.telegraph_author_url.strip()[:512],
        "content": _encode_content(nodes),
        "return_content": False,
    })
    url = result.get("url")
    if not url:
        raise TelegraphError("createPage не вернул url")
    logger.info("Статья опубликована на Telegraph: %s", url)
    return str(url)
