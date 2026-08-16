"""Рассылки по сегменту (F64) — веб-роуты.

ОТПРАВКА ДВУХШАГОВАЯ, И ЭТО НЕ ПРО УДОБСТВО. Разосланные сообщения нельзя
отозвать: ошибка в выборе сегмента видна только по реакции живых людей.
Поэтому между «написал текст» и «ушло» стоит экран, где показано, скольким
именно уйдёт и почему остальным — нет.

Подтверждение несёт СНИМОК чисел, показанных на предпросмотре. Если между
экранами сегмент изменился (кто-то получил тег, кто-то ушёл), владелец
увидит предупреждение вместо тихой отправки по другому списку.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from tg_repost import broadcasts_repo, segments_repo
from tg_repost.webui import audit, flash, i18n
from tg_repost.webui.templating import build_templates
from tg_repost.webui.auth import require_login

_BASE_DIR = Path(__file__).parent
_templates = build_templates()


def build_broadcasts_router() -> APIRouter:
    router = APIRouter(dependencies=[Depends(require_login)])

    @router.get("/broadcasts", response_class=HTMLResponse)
    async def broadcasts_page(request: Request, error: str = "") -> Response:
        return _templates.TemplateResponse(
            request, "broadcasts.html",
            {
                "broadcasts": broadcasts_repo.list_recent(),
                "segments": segments_repo.list_all(),
                "error": error or None,
            },
        )

    @router.post("/broadcasts/preview", response_class=HTMLResponse)
    async def broadcast_preview(
        request: Request, segment_id: str = Form(""), text: str = Form(""),
    ) -> Response:
        """Шаг 1: показать, кому уйдёт. Ничего не отправляет."""
        if not segment_id.isdigit() or not text.strip():
            return _templates.TemplateResponse(
                request, "broadcasts.html",
                {
                    "broadcasts": broadcasts_repo.list_recent(),
                    "segments": segments_repo.list_all(),
                    "error": i18n.t("broadcasts.error_need_segment_and_text"),
                },
                status_code=400,
            )

        plan = broadcasts_repo.plan(int(segment_id))
        if plan is None:
            return RedirectResponse(url="/broadcasts", status_code=303)

        return _templates.TemplateResponse(
            request, "broadcast_preview.html",
            {
                "segment_id": int(segment_id),
                "text": text.strip(),
                "plan": plan,
                # Снимок для сверки на шаге 2 — см. docstring модуля.
                "expected_reachable": plan.stats.reachable,
            },
        )

    @router.post("/broadcasts/send")
    async def broadcast_send(
        request: Request,
        segment_id: str = Form(""),
        text: str = Form(""),
        expected_reachable: str = Form(""),
    ) -> Response:
        """Шаг 2: отправить. Сверяет числа с показанными на предпросмотре."""
        if not segment_id.isdigit() or not text.strip():
            flash.set_flash(request, i18n.t("broadcasts.error_need_segment_and_text"))
            return RedirectResponse(url="/broadcasts", status_code=303)

        plan = broadcasts_repo.plan(int(segment_id))
        if plan is None:
            # Сегмент удалили, пока человек смотрел предпросмотр. Отправлять
            # некуда, и молчать об этом нельзя: иначе он уверен, что рассылка
            # ушла, и узнает обратное только по отсутствию ответов.
            flash.set_flash(request, i18n.t("broadcasts.error_segment_gone"))
            return RedirectResponse(url="/broadcasts", status_code=303)

        if expected_reachable.isdigit() and int(expected_reachable) != plan.stats.reachable:
            # Между экранами состав сегмента изменился. Молча отправить по
            # другому списку — ровно тот случай, ради которого предпросмотр и
            # существует, поэтому возвращаем человека на него с новыми числами.
            return _templates.TemplateResponse(
                request, "broadcast_preview.html",
                {
                    "segment_id": int(segment_id),
                    "text": text.strip(),
                    "plan": plan,
                    "expected_reachable": plan.stats.reachable,
                    "changed_from": int(expected_reachable),
                },
                status_code=409,
            )

        broadcast_id = broadcasts_repo.create(int(segment_id), text)
        if broadcast_id is None:
            return RedirectResponse(url="/broadcasts", status_code=303)

        audit.record_audit(
            "broadcast_send", target=plan.segment_name,
            detail=f"получателей {plan.stats.reachable} из {plan.stats.total}",
        )
        return RedirectResponse(url="/broadcasts", status_code=303)

    @router.post("/broadcasts/{broadcast_id}/cancel")
    async def broadcast_cancel(broadcast_id: int) -> Response:
        row = broadcasts_repo.get(broadcast_id)
        if broadcasts_repo.cancel(broadcast_id) and row is not None:
            audit.record_audit(
                "broadcast_cancel", target=row.segment_name,
                detail=f"успело уйти {row.sent_count}",
            )
        return RedirectResponse(url="/broadcasts", status_code=303)

    return router
