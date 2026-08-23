"""Ключи API и вебхуки (F73) — веб-роуты.

ТОЛЬКО ВЛАДЕЛЕЦ. Ключ — это пропуск в систему для чужой программы, а
вебхук — адрес, по которому наш сервер сам пойдёт стучаться. И то и другое
уровня секретов, а не уровня редактора контента.

КЛЮЧ ПОКАЗЫВАЕТСЯ ОДИН РАЗ И НЕ ХРАНИТСЯ. Поэтому он передаётся на страницу
через флеш-сообщение в сессии, а не через параметр адреса: параметры оседают
в истории браузера, логах прокси и реферерах — то есть ключ утекал бы сам
собой, ровно тем способом, от которого хранение хэша и защищает.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from tg_repost import api_keys_repo as keys
from tg_repost import webhooks_repo as hooks
from tg_repost.webui import audit
from tg_repost.webui.auth import require_login
from tg_repost.webui.templating import build_templates

_templates = build_templates()


def build_integrations_router() -> APIRouter:
    router = APIRouter(dependencies=[Depends(require_login)])

    def _page(request: Request, error: str | None = None, status: int = 200) -> Response:
        # Ключ забирается из сессии и СРАЗУ удаляется: показать его можно
        # только один раз, и перезагрузка страницы не должна показывать
        # снова.
        fresh_key = request.session.pop("fresh_api_key", None)
        return _templates.TemplateResponse(
            request, "integrations.html",
            {
                "keys": keys.list_keys(),
                "webhooks": hooks.list_all(),
                "known_events": hooks.KNOWN_EVENTS,
                "fresh_key": fresh_key,
                "error": error,
            },
            status_code=status,
        )

    @router.get("/integrations", response_class=HTMLResponse)
    async def integrations_page(request: Request) -> Response:
        return _page(request)

    @router.post("/integrations/keys")
    async def create_key(
        request: Request,
        name: str = Form(""),
        scope: str = Form(keys.SCOPE_READ),
        rate_limit: str = Form(str(keys.DEFAULT_RATE_LIMIT)),
    ) -> Response:
        try:
            limit = int(rate_limit or keys.DEFAULT_RATE_LIMIT)
        except ValueError:
            return _page(request, "Ограничение частоты должно быть числом", 400)

        try:
            view, raw = keys.create(name, scope=scope, rate_limit=limit)
        except keys.InvalidKey as exc:
            return _page(request, str(exc), 400)

        request.session["fresh_api_key"] = raw
        audit.record_audit("api_key_create", target=view.name, detail=view.scope)
        return RedirectResponse(url="/integrations", status_code=303)

    @router.post("/integrations/keys/{key_id}/revoke")
    async def revoke_key(key_id: int) -> Response:
        rows = [k for k in keys.list_keys() if k.id == key_id]
        if keys.revoke(key_id) and rows:
            audit.record_audit("api_key_revoke", target=rows[0].name)
        return RedirectResponse(url="/integrations", status_code=303)

    @router.post("/integrations/webhooks")
    async def create_webhook(
        request: Request,
        url: str = Form(""),
        events: list[str] = Form(default=[]),
    ) -> Response:
        try:
            hooks.save(url, events=events)
        except hooks.InvalidWebhook as exc:
            return _page(request, str(exc), 400)

        audit.record_audit("webhook_create", target=url.strip())
        return RedirectResponse(url="/integrations", status_code=303)

    @router.post("/integrations/webhooks/{webhook_id}/toggle")
    async def webhook_toggle(request: Request, webhook_id: int) -> Response:
        """Включить или выключить подписку.

        Нужно прежде всего затем, что подписку выключает САМА СИСТЕМА после
        серии отказов — приёмник полежал, и включить его обратно было нечем.
        """
        del request
        new_state = hooks.toggle_webhook(webhook_id)
        if new_state is not None:
            audit.record_audit(
                "webhook_toggle", target=f"#{webhook_id}",
                detail=f"active={new_state}",
            )
        return RedirectResponse(url="/integrations", status_code=303)

    @router.post("/integrations/webhooks/{webhook_id}/delete")
    async def delete_webhook(webhook_id: int) -> Response:
        view = hooks.get(webhook_id)
        if view is not None and hooks.delete(webhook_id):
            audit.record_audit("webhook_delete", target=view.url)
        return RedirectResponse(url="/integrations", status_code=303)

    return router
