"""Приём криптовалюты: способы и привязка к группам (F70) — веб-роуты.

ТОЛЬКО ВЛАДЕЛЕЦ: здесь лежат ключи от денег.

КЛЮЧ НЕ ПОКАЗЫВАЕТСЯ НИКОГДА, даже владельцу. Его нет в объекте, который
уходит в шаблон, — не замаскирован, а отсутствует. Пустое поле при правке
означает «не меняли»: показать сохранённый ключ нельзя, поэтому трактовать
пустоту как очистку значило бы ломать способ при каждой правке названия.

ПРИВЯЗКА К ГРУППАМ — ОТДЕЛЬНОЙ ТАБЛИЦЕЙ НА ТОЙ ЖЕ СТРАНИЦЕ. Владелец мыслит
так: «в этой группе платим сюда, в той туда»; разносить это по двум экранам
значит заставлять его держать связь в голове.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from tg_repost import crypto_rails_repo as rails
from tg_repost import targets_repo
from tg_repost.crypto_rails import KINDS
from tg_repost.webui import audit
from tg_repost.webui.auth import require_login
from tg_repost.webui.templating import build_templates

_templates = build_templates()


def build_crypto_router() -> APIRouter:
    router = APIRouter(dependencies=[Depends(require_login)])

    def _page(request: Request, error: str | None = None, status: int = 200) -> Response:
        configured = rails.list_all()
        by_id = {r.id: r for r in configured}
        groups = []
        for target in targets_repo.list_targets():
            bound = None
            from tg_repost.db.models import TargetGroup
            from tg_repost.db.session import session_scope

            with session_scope() as session:
                row = (
                    session.query(TargetGroup)
                    .filter(TargetGroup.chat_id == target.chat_id)
                    .first()
                )
                bound = row.crypto_rail_id if row is not None else None
            groups.append({
                "target": target,
                "rail_id": bound,
                "rail": by_id.get(bound) if bound else None,
            })

        return _templates.TemplateResponse(
            request, "crypto.html",
            {
                "rails": configured,
                "kinds": KINDS,
                "groups": groups,
                "error": error,
            },
            status_code=status,
        )

    @router.get("/crypto", response_class=HTMLResponse)
    async def crypto_page(request: Request) -> Response:
        return _page(request)

    @router.post("/crypto")
    async def crypto_save(
        request: Request,
        rail_id: str = Form(""),
        name: str = Form(""),
        kind: str = Form(""),
        credential: str = Form(""),
        is_active: str = Form(""),
        is_default: str = Form(""),
    ) -> Response:
        existing = int(rail_id) if rail_id.isdigit() else None
        try:
            saved = rails.save(
                rail_id=existing,
                name=name,
                kind=kind,
                credential=credential,
                is_active=bool(is_active),
                is_default=bool(is_default),
            )
        except rails.InvalidRail as exc:
            return _page(request, str(exc), 400)

        audit.record_audit(
            "crypto_rail_save", target=name.strip(), detail=kind,
        )
        del saved
        return RedirectResponse(url="/crypto", status_code=303)

    @router.post("/crypto/{rail_id}/delete")
    async def crypto_delete(rail_id: int) -> Response:
        view = rails.get(rail_id)
        if view is not None and rails.delete(rail_id):
            audit.record_audit("crypto_rail_delete", target=view.name)
        return RedirectResponse(url="/crypto", status_code=303)

    @router.post("/crypto/bind")
    async def crypto_bind(chat_id: str = Form(""), rail_id: str = Form("")) -> Response:
        if not chat_id.lstrip("-").isdigit():
            return RedirectResponse(url="/crypto", status_code=303)
        chosen = int(rail_id) if rail_id.isdigit() else None
        if rails.bind_to_group(int(chat_id), chosen):
            audit.record_audit(
                "crypto_rail_bind", target=chat_id,
                detail=str(chosen) if chosen else "по умолчанию",
            )
        return RedirectResponse(url="/crypto", status_code=303)

    return router
