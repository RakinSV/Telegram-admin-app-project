"""Партнёры и их баланс (F67) — веб-роуты.

ТОЛЬКО ВЛАДЕЛЕЦ: страница про раздачу доли выручки, это уровень денег.

ВЫПЛАТА ЗДЕСЬ — ЗАПИСЬ ФАКТА, А НЕ ПЕРЕВОД. Telegram не даёт боту
переслать звёзды человеку: вывод идёт через Fragment на кошелёк владельца, а
дальше он платит партнёру как договорились. Кнопка, которая делает вид, что
переводит деньги, была бы обманом, поэтому она называется «записать
выплату» и ровно это и делает.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from tg_repost import affiliate_repo
from tg_repost.webui import audit, i18n
from tg_repost.webui.auth import require_login
from tg_repost.webui.templating import build_templates

_templates = build_templates()


def build_affiliate_router() -> APIRouter:
    router = APIRouter(dependencies=[Depends(require_login)])

    @router.get("/affiliate", response_class=HTMLResponse)
    async def affiliate_page(request: Request, error: str = "") -> Response:
        from tg_repost.config import get_settings

        partners = affiliate_repo.partners()
        return _templates.TemplateResponse(
            request, "affiliate.html",
            {
                "partners": partners,
                "percent": get_settings().affiliate_percent,
                "total_owed": affiliate_repo.total_owed(),
                "error": error or None,
            },
        )

    @router.get("/affiliate/{partner_user_id}", response_class=HTMLResponse)
    async def affiliate_detail(request: Request, partner_user_id: int) -> Response:
        return _templates.TemplateResponse(
            request, "affiliate_detail.html",
            {
                "balance": affiliate_repo.balance_of(partner_user_id),
                "rows": affiliate_repo.history(partner_user_id),
            },
        )

    @router.post("/affiliate/{partner_user_id}/payout")
    async def affiliate_payout(
        partner_user_id: int, amount: str = Form(""), note: str = Form(""),
    ) -> Response:
        if not amount.strip().isdigit():
            return RedirectResponse(
                url=f"/affiliate?error={i18n.t('affiliate.error_amount')}",
                status_code=303,
            )
        done = affiliate_repo.record_payout(
            partner_user_id, int(amount), note.strip() or None,
        )
        if not done:
            return RedirectResponse(
                url=f"/affiliate?error={i18n.t('affiliate.error_too_much')}",
                status_code=303,
            )
        audit.record_audit(
            "affiliate_payout", target=str(partner_user_id), detail=f"{amount} ⭐",
        )
        return RedirectResponse(url=f"/affiliate/{partner_user_id}", status_code=303)

    return router
