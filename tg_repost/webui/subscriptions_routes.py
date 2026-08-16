"""Подписчики платного канала (F49) — веб-роуты.

ВСЯ СТРАНИЦА ТОЛЬКО ДЛЯ ВЛАДЕЛЬЦА. Здесь видны деньги и отсюда деньги
возвращаются; это тот же уровень, что `/secrets` и `/users`, а не уровень
редактора контента.

ВЫРУЧКА СЧИТАЕТСЯ ПО ЖУРНАЛУ, А НЕ ПО ПОДПИСКАМ. Подписка знает текущее
состояние, а деньги — это последовательность фактов: оплата, продление,
возврат. Сложить активные подписки и назвать это выручкой значило бы
потерять и возвраты, и уже закончившиеся оплаты.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from tg_repost import subscriptions_repo as subs
from tg_repost.webui import audit
from tg_repost.webui.auth import require_login
from tg_repost.webui.templating import build_templates

_templates = build_templates()


def build_subscriptions_router() -> APIRouter:
    router = APIRouter(dependencies=[Depends(require_login)])

    @router.get("/subscriptions", response_class=HTMLResponse)
    async def subscriptions_page(
        request: Request, error: str = "", ok: str = "",
    ) -> Response:
        rows = subs.list_all()
        return _templates.TemplateResponse(
            request, "subscriptions.html",
            {
                "rows": rows,
                "revenue": subs.revenue_stars(),
                "active_count": sum(1 for r in rows if r.is_active),
                "error": error or None,
                "ok": ok or None,
            },
        )

    @router.post("/subscriptions/{chat_id}/{user_id}/refund")
    async def subscription_refund(chat_id: int, user_id: int) -> Response:
        done, explanation = await subs.refund(chat_id, user_id)
        audit.record_audit(
            "subscription_refund", target=str(user_id),
            detail=explanation,
        )
        key = "ok" if done else "error"
        return RedirectResponse(
            url=f"/subscriptions?{key}={explanation}", status_code=303,
        )

    return router
