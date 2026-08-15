"""Контент-календарь (F72) — веб-роуты.

РАЗНЫЕ ПРАВА НА ОДНОЙ СТРАНИЦЕ. Календарь открыт редактору — планировать
контент это его работа. А подтверждение поста, ожидающего владельца, живёт
по адресу `/calendar/approve/...`, который политика доступа относит к
владельцу. Работает это за счёт правила «побеждает самый длинный префикс»
(см. `access.py`): без него редактор подтверждал бы собственные посты, и
согласование превратилось бы в декорацию.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from tg_repost import calendar_repo, targets_repo
from tg_repost.config import get_settings
from tg_repost.webui import audit
from tg_repost.webui.templating import build_templates
from tg_repost.webui.auth import require_login

_BASE_DIR = Path(__file__).parent
_templates = build_templates()


def build_calendar_router() -> APIRouter:
    router = APIRouter(dependencies=[Depends(require_login)])

    @router.get("/calendar", response_class=HTMLResponse)
    async def calendar_page(request: Request, chat_id: str = "") -> Response:
        targets = [t for t in targets_repo.list_targets() if t.is_active]
        selected: int | None = None
        if chat_id.lstrip("-").isdigit():
            selected = int(chat_id)
        elif targets:
            selected = targets[0].chat_id

        view = calendar_repo.build(selected)
        return _templates.TemplateResponse(
            request, "calendar.html",
            {
                "targets": targets,
                "selected": selected,
                "view": view,
                "awaiting": calendar_repo.posts_awaiting_owner(),
                "approval_required": get_settings().require_owner_approval,
                "is_owner": request.session.get("role") == "owner",
            },
        )

    @router.post("/calendar/{post_id}/schedule")
    async def schedule(post_id: int, day: str = Form("")) -> Response:
        target: date | None = None
        if day.strip():
            try:
                target = date.fromisoformat(day)
            except ValueError:
                return RedirectResponse(url="/calendar", status_code=303)

        if calendar_repo.schedule_post(post_id, target):
            audit.record_audit(
                "post_schedule", target=f"#{post_id}",
                detail=str(target) if target else "снято",
            )
        return RedirectResponse(url="/calendar", status_code=303)

    # Путь начинается с `/calendar/approve` намеренно: политика доступа
    # относит именно этот префикс к владельцу, и редактор сюда не пройдёт.
    @router.post("/calendar/approve/{post_id}")
    async def approve(post_id: int) -> Response:
        if calendar_repo.approve_by_owner(post_id):
            audit.record_audit("post_owner_approve", target=f"#{post_id}")
        return RedirectResponse(url="/calendar", status_code=303)

    return router
