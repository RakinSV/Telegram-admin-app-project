"""Инвайт-ссылки целевых групп + заявки на вступление (F32) — веб-роуты.

Bot API вызовы идут через `bot` из супервизора (тот же паттерн,
что у `/moderation` — см. `crud_routes.py`), бизнес-логика в
`telegram/invites.py`/`invites_repo.py`."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from tg_repost import invites_repo, member_origins_repo, targets_repo
from tg_repost.telegram.invites import (
    approve_join_request,
    create_invite_link,
    decline_join_request,
    revoke_invite_link,
)
from tg_repost.webui import audit, i18n
from tg_repost.webui.templating import build_templates
from tg_repost.webui.auth import require_login
from tg_repost.webui.supervisor import get_components

_BASE_DIR = Path(__file__).parent
_templates = build_templates()


def _context(error: str | None = None) -> dict:
    targets = [t for t in targets_repo.list_targets() if t.is_active]
    links = invites_repo.list_invite_links()
    links_by_chat: dict[int, list] = {}
    for link in links:
        links_by_chat.setdefault(link.chat_id, []).append(link)
    return {
        "targets": targets,
        "links_by_chat": links_by_chat,
        "pending_requests": invites_repo.list_pending_join_requests(),
        # F41: откуда пришли подписчики — сколько привела каждая ссылка,
        # сколько из них осталось и во что обошёлся один оставшийся (CPA).
        "origin_stats": member_origins_repo.origin_stats(),
        "error": error,
    }


def build_invites_router() -> APIRouter:
    router = APIRouter(prefix="/invites", dependencies=[Depends(require_login)])

    @router.get("", response_class=HTMLResponse)
    async def invites_page(request: Request) -> Response:
        return _templates.TemplateResponse(request, "invites.html", _context())

    @router.post("")
    async def invites_create(
        request: Request,
        chat_id: int = Form(...),
        name: str = Form(""),
        member_limit: str = Form(""),
        creates_join_request: str = Form(""),
    ) -> Response:
        bot = get_components().moderation_bot
        if bot is None:
            return _templates.TemplateResponse(
                request, "invites.html",
                _context(i18n.t("moderation_detail.error_bot_not_running")),
                status_code=400,
            )
        member_limit_int: int | None = None
        if member_limit.strip():
            if not member_limit.strip().isdigit():
                return _templates.TemplateResponse(
                    request, "invites.html",
                    _context(i18n.t("invites.error_invalid_member_limit")),
                    status_code=400,
                )
            member_limit_int = int(member_limit.strip())
        link = await create_invite_link(
            bot, chat_id, name.strip() or None, member_limit_int,
            creates_join_request=bool(creates_join_request),
        )
        audit.record_audit("invite_link_create", target=f"chat {chat_id}", detail=link.invite_link)
        return RedirectResponse(url="/invites", status_code=303)

    @router.post("/{link_id}/cost")
    async def invites_set_cost(
        request: Request, link_id: int,
        cost: str = Form(""), currency: str = Form("RUB"),
    ) -> Response:
        """F41: стоимость размещения → цена привлечённого подписчика (CPA).

        Пустое значение стирает цену: размещение могло быть по бартеру, и
        показывать CPA=0 было бы враньём.
        """
        del request
        raw = cost.strip().replace(",", ".")
        parsed: float | None = None
        if raw:
            try:
                parsed = float(raw)
            except ValueError:
                # Опечатку молча превращать в «бесплатно» нельзя — просто не
                # трогаем сохранённое и возвращаем страницу как есть.
                return RedirectResponse(url="/invites", status_code=303)
            if parsed < 0:
                return RedirectResponse(url="/invites", status_code=303)
        if invites_repo.set_link_cost(link_id, parsed, currency):
            audit.record_audit("invite_link_cost", target=f"#{link_id}", detail=raw or "(стёрта)")
        return RedirectResponse(url="/invites", status_code=303)

    @router.post("/{link_id}/revoke")
    async def invites_revoke(request: Request, link_id: int) -> Response:
        bot = get_components().moderation_bot
        if bot is None:
            return _templates.TemplateResponse(
                request, "invites.html",
                _context(i18n.t("moderation_detail.error_bot_not_running")),
                status_code=400,
            )
        if await revoke_invite_link(bot, link_id):
            audit.record_audit("invite_link_revoke", target=f"#{link_id}")
        return RedirectResponse(url="/invites", status_code=303)

    @router.post("/join-requests/{request_id}/approve")
    async def invites_join_approve(request: Request, request_id: int) -> Response:
        bot = get_components().moderation_bot
        if bot is None:
            return _templates.TemplateResponse(
                request, "invites.html",
                _context(i18n.t("moderation_detail.error_bot_not_running")),
                status_code=400,
            )
        if await approve_join_request(bot, request_id):
            audit.record_audit("join_request_approve", target=f"#{request_id}")
        return RedirectResponse(url="/invites", status_code=303)

    @router.post("/join-requests/{request_id}/decline")
    async def invites_join_decline(request: Request, request_id: int) -> Response:
        bot = get_components().moderation_bot
        if bot is None:
            return _templates.TemplateResponse(
                request, "invites.html",
                _context(i18n.t("moderation_detail.error_bot_not_running")),
                status_code=400,
            )
        if await decline_join_request(bot, request_id):
            audit.record_audit("join_request_decline", target=f"#{request_id}")
        return RedirectResponse(url="/invites", status_code=303)

    return router
