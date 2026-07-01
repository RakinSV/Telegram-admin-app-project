"""Фильтр ссылок (G04) — whitelist доменов, пустой по умолчанию.

Проверяет и видимый URL-текст (`https://...`, `t.me/...`, `www...`), и
скрытые ссылки Telegram (entity `text_link` — текст кнопки/слова не похож
на ссылку, но `entity.url` есть; частый приём спамеров)."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from guardian.db.models import BotConfig

_LINK_RE = re.compile(r"(?:https?://|t\.me/|www\.)\S+", re.IGNORECASE)


def _domain_from_url(url: str) -> str | None:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        netloc = urlparse(url).netloc.lower()
    except ValueError:
        return None
    if netloc.startswith("www."):
        netloc = netloc[len("www.") :]
    return netloc or None


class LinkFilter:
    def __init__(self) -> None:
        self._allowed: set[str] = set()

    def reload(self, session: Session) -> None:
        row = (
            session.query(BotConfig)
            .filter(BotConfig.key == "allowed_domains")
            .one_or_none()
        )
        self._allowed = set(json.loads(row.value)) if row is not None else set()

    def _extract_domains(self, message: Any) -> list[str]:
        domains: list[str] = []
        text = getattr(message, "text", None) or getattr(message, "caption", None) or ""
        for m in _LINK_RE.finditer(text):
            domain = _domain_from_url(m.group(0))
            if domain:
                domains.append(domain)

        entities = list(getattr(message, "entities", None) or []) + list(
            getattr(message, "caption_entities", None) or []
        )
        for entity in entities:
            url = getattr(entity, "url", None)
            if getattr(entity, "type", None) == "text_link" and url:
                domain = _domain_from_url(url)
                if domain:
                    domains.append(domain)
        return domains

    def check(self, message: Any) -> tuple[bool, str | None]:
        """Вернуть (найдена_ли_запрещённая_ссылка, домен)."""
        for domain in self._extract_domains(message):
            if domain not in self._allowed:
                return True, domain
        return False, None
