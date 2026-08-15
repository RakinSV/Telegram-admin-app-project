"""Медиакит канала (F65) — веб-роут.

ПУБЛИЧНОЙ ССЫЛКИ НЕТ НАМЕРЕННО. Отдавать медиакит по токену без входа было
бы удобнее, но это добавило бы в систему публичный маршрут, а вся её защита
построена на обратном: в `webui/auth.py` прямо записано, что CSRF-токенов
нет, потому что «нет сторонних origin», и доступ ограничен localhost/VPN.
Один публичный роут эту предпосылку ломает, и пересматривать модель угроз
ради удобства выгрузки — плохой размен.

Поэтому страница живёт под тем же логином, а рекламодателю уходит PDF:
браузер печатает её сам, разметка под печать готова (см. `@media print`).
Если публичная ссылка когда-нибудь понадобится, её место — в F73, где модель
угроз пересматривается целиком и осознанно.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import HTMLResponse

from tg_repost import mediakit_repo, targets_repo
from tg_repost.webui.templating import build_templates
from tg_repost.webui.auth import require_login

_BASE_DIR = Path(__file__).parent
_templates = build_templates()

_WINDOW_CHOICES = (7, 30, 90)


def build_mediakit_router() -> APIRouter:
    router = APIRouter(dependencies=[Depends(require_login)])

    @router.get("/mediakit", response_class=HTMLResponse)
    async def mediakit_page(
        request: Request, chat_id: str = "", days: int = 30,
    ) -> Response:
        targets = [t for t in targets_repo.list_targets() if t.is_active]
        window = days if days in _WINDOW_CHOICES else 30

        selected: int | None = None
        if chat_id.lstrip("-").isdigit():
            selected = int(chat_id)
        elif targets:
            selected = targets[0].chat_id

        kit = mediakit_repo.build(selected, window) if selected is not None else None
        return _templates.TemplateResponse(
            request, "mediakit.html",
            {
                "targets": targets,
                "selected": selected,
                "window": window,
                "windows": _WINDOW_CHOICES,
                "kit": kit,
            },
        )

    return router
