"""Заявки рекламодателей и календарь сетки (F66) — веб-роуты.

Календарь и список показываются НА ОДНОЙ странице намеренно. Решение
«принять или отказать» невозможно принять, не видя, что уже стоит на эту
дату: разнеси их по вкладкам — и владелец начнёт принимать заявки вслепую,
а потом извиняться перед тем, кому место уже обещано.

Конфликт дат показывается ТЕКСТОМ С ИМЕНЕМ конфликтующего рекламодателя, а
не «дата занята»: владельцу решать, кому отказать, и для этого надо видеть,
кто там стоит.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from tg_repost import ad_requests_repo, targets_repo
from tg_repost.webui import audit, i18n
from tg_repost.webui.auth import require_login

_BASE_DIR = Path(__file__).parent
_templates = Jinja2Templates(directory=str(_BASE_DIR / "templates"))
_templates.env.globals["t"] = i18n.t
_templates.env.globals["current_lang"] = i18n.get_current_lang

# Насколько вперёд рисуем сетку. Месяц — горизонт, на который рекламодатели
# реально бронируют; год превратил бы страницу в простыню из пустых дней.
_CALENDAR_DAYS = 30


def build_ad_requests_router() -> APIRouter:
    router = APIRouter(dependencies=[Depends(require_login)])

    @router.get("/ad-requests", response_class=HTMLResponse)
    async def ad_requests_page(
        request: Request, chat_id: str = "", error: str = "",
    ) -> Response:
        return _templates.TemplateResponse(
            request, "ad_requests.html", _context(chat_id, error or None),
        )

    @router.post("/ad-requests")
    async def ad_request_create(
        request: Request,
        chat_id: str = Form(""),
        advertiser: str = Form(""),
        brief_text: str = Form(""),
        slot_date: str = Form(""),
        price: str = Form(""),
        note: str = Form(""),
    ) -> Response:
        if not chat_id.lstrip("-").isdigit():
            return RedirectResponse(url="/ad-requests", status_code=303)

        try:
            day = date.fromisoformat(slot_date)
        except ValueError:
            return _error(request, chat_id, i18n.t("ad_requests.error_bad_date"))

        amount: float | None = None
        if price.strip():
            try:
                amount = float(price.replace(",", "."))
            except ValueError:
                return _error(request, chat_id, i18n.t("ad_requests.error_bad_price"))

        request_id = ad_requests_repo.create(
            chat_id=int(chat_id), advertiser=advertiser, brief_text=brief_text,
            slot_date=day, price=amount, note=note,
        )
        if request_id is None:
            return _error(request, chat_id, i18n.t("ad_requests.error_need_fields"))

        audit.record_audit(
            "ad_request_create", target=advertiser.strip(), detail=str(day),
        )
        return RedirectResponse(url=f"/ad-requests?chat_id={chat_id}", status_code=303)

    @router.post("/ad-requests/{request_id}/accept")
    async def ad_request_accept(request: Request, request_id: int) -> Response:
        view = ad_requests_repo.get(request_id)
        if view is None:
            return RedirectResponse(url="/ad-requests", status_code=303)

        try:
            ad_requests_repo.accept(request_id)
        except ad_requests_repo.SlotTaken as exc:
            # Имя конфликтующего рекламодателя — не украшение сообщения, а
            # то, из чего владелец принимает решение.
            return _error(
                request, str(view.chat_id),
                i18n.t(
                    "ad_requests.error_slot_taken",
                    date=exc.existing.slot_date,
                    who=exc.existing.advertiser,
                ),
                status_code=409,
            )

        audit.record_audit(
            "ad_request_accept", target=view.advertiser, detail=str(view.slot_date),
        )
        return RedirectResponse(
            url=f"/ad-requests?chat_id={view.chat_id}", status_code=303,
        )

    @router.post("/ad-requests/{request_id}/decline")
    async def ad_request_decline(request_id: int, note: str = Form("")) -> Response:
        view = ad_requests_repo.get(request_id)
        if ad_requests_repo.decline(request_id, note) and view is not None:
            audit.record_audit("ad_request_decline", target=view.advertiser)
        chat = view.chat_id if view else ""
        return RedirectResponse(url=f"/ad-requests?chat_id={chat}", status_code=303)

    @router.post("/ad-requests/{request_id}/publish")
    async def ad_request_publish(request_id: int, amount: str = Form("")) -> Response:
        view = ad_requests_repo.get(request_id)
        if view is None:
            return RedirectResponse(url="/ad-requests", status_code=303)

        override: float | None = None
        if amount.strip():
            try:
                override = float(amount.replace(",", "."))
            except ValueError:
                override = None

        ad_requests_repo.mark_published(request_id, amount=override)
        audit.record_audit(
            "ad_request_publish", target=view.advertiser,
            detail=str(override if override is not None else view.price),
        )
        return RedirectResponse(
            url=f"/ad-requests?chat_id={view.chat_id}", status_code=303,
        )

    @router.post("/ad-requests/{request_id}/delete")
    async def ad_request_delete(request_id: int) -> Response:
        view = ad_requests_repo.get(request_id)
        if ad_requests_repo.delete(request_id) and view is not None:
            audit.record_audit("ad_request_delete", target=view.advertiser)
        chat = view.chat_id if view else ""
        return RedirectResponse(url=f"/ad-requests?chat_id={chat}", status_code=303)

    def _error(
        request: Request, chat_id: str, message: str, status_code: int = 400,
    ) -> Response:
        return _templates.TemplateResponse(
            request, "ad_requests.html", _context(chat_id, message),
            status_code=status_code,
        )

    return router


def _context(chat_id: str, error: str | None) -> dict:
    targets = [t for t in targets_repo.list_targets() if t.is_active]
    selected: int | None = None
    if chat_id.lstrip("-").isdigit():
        selected = int(chat_id)
    elif targets:
        selected = targets[0].chat_id

    requests = ad_requests_repo.list_all(selected) if selected is not None else []
    occupied = ad_requests_repo.occupied_dates(selected) if selected is not None else {}

    today = datetime.now(timezone.utc).date()
    calendar = [
        {"day": today + timedelta(days=i), "taken": occupied.get(today + timedelta(days=i))}
        for i in range(_CALENDAR_DAYS)
    ]
    return {
        "targets": targets,
        "selected": selected,
        "requests": requests,
        "calendar": calendar,
        "today": today,
        "error": error,
        "statuses": {
            "new": ad_requests_repo.STATUS_NEW,
            "accepted": ad_requests_repo.STATUS_ACCEPTED,
            "declined": ad_requests_repo.STATUS_DECLINED,
            "published": ad_requests_repo.STATUS_PUBLISHED,
        },
    }
