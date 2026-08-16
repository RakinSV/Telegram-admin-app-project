"""Конкурсы и розыгрыши (F44) — веб-роуты.

НАЙДЕНО АУДИТОМ 2026-08-16: движок конкурсов был написан целиком — участие,
проверка условий, честный розыгрыш с протоколом, — и числился реализованным,
но завести конкурс владельцу было НЕЧЕМ. Ни страницы, ни команды, ни CLI.
Фича, до которой нельзя дойти, не реализована, как бы хорошо она ни была
покрыта тестами.

РОЗЫГРЫШ ОТСЮДА НЕ ЗАПУСКАЕТСЯ. Победителей тянет Engage, когда конкурс
дозрел (`due_contests`), и делает это по зерну, записанному при создании, —
так протокол воспроизводим и проверяем любым участником. Кнопка «разыграть
сейчас» в админке означала бы, что владелец может тянуть до срока и
перетягивать, а конкурс, который можно перетянуть, — это не конкурс.

ДАТА ОКОНЧАНИЯ ВВОДИТСЯ В UTC. Не потому, что так удобно, а потому что
иначе пришлось бы угадывать часовой пояс владельца и тихо ошибаться на
несколько часов ровно в тот момент, когда конкурс должен завершиться.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from tg_repost import contests_repo, targets_repo
from tg_repost.webui import audit, i18n
from tg_repost.webui.auth import require_login
from tg_repost.webui.templating import build_templates

_templates = build_templates()


def build_contests_router() -> APIRouter:
    router = APIRouter(dependencies=[Depends(require_login)])

    def _page(request: Request, error: str | None = None, status: int = 200) -> Response:
        rows = contests_repo.list_contests()
        contests = []
        for row in rows:
            view = contests_repo.get_contest(row.id)
            if view is None:
                continue
            entries = contests_repo.list_entries(view.id)
            contests.append({
                "view": view,
                "entries": len(entries),
                "winners": [e for e in entries if e.is_winner],
                "is_over": view.ends_at.replace(tzinfo=timezone.utc)
                <= datetime.now(timezone.utc)
                if view.ends_at.tzinfo is None else view.ends_at <= datetime.now(timezone.utc),
            })
        return _templates.TemplateResponse(
            request, "contests.html",
            {
                "contests": contests,
                "targets": [t for t in targets_repo.list_targets() if t.is_active],
                "error": error,
            },
            status_code=status,
        )

    @router.get("/contests", response_class=HTMLResponse)
    async def contests_page(request: Request) -> Response:
        return _page(request)

    @router.post("/contests")
    async def contest_create(
        request: Request,
        chat_id: str = Form(""),
        title: str = Form(""),
        prize: str = Form(""),
        winners_count: str = Form("1"),
        ends_at: str = Form(""),
        require_min_points: str = Form("0"),
        require_min_referrals: str = Form("0"),
    ) -> Response:
        if not title.strip() or not prize.strip():
            return _page(request, i18n.t("contests.error_need_title_and_prize"), 400)
        try:
            target_chat = int(chat_id)
            winners = int(winners_count or 1)
            min_points = int(require_min_points or 0)
            min_referrals = int(require_min_referrals or 0)
        except ValueError:
            return _page(request, i18n.t("contests.error_numbers"), 400)
        if winners < 1:
            return _page(request, i18n.t("contests.error_winners"), 400)

        try:
            # `datetime-local` приходит без зоны — трактуем как UTC явно,
            # см. docstring модуля.
            deadline = datetime.fromisoformat(ends_at).replace(tzinfo=timezone.utc)
        except ValueError:
            return _page(request, i18n.t("contests.error_date"), 400)
        if deadline <= datetime.now(timezone.utc):
            # Конкурс, который уже закончился, разыгрался бы первым же
            # проходом джобы — до того, как кто-либо успел бы участвовать.
            return _page(request, i18n.t("contests.error_past_date"), 400)

        contest_id = contests_repo.create_contest(
            chat_id=target_chat,
            title=title.strip(),
            prize=prize.strip(),
            winners_count=winners,
            ends_at=deadline,
            require_min_points=min_points,
            require_min_referrals=min_referrals,
        )
        if contest_id is None:
            return _page(request, i18n.t("contests.error_not_created"), 400)

        audit.record_audit(
            "contest_create", target=title.strip(),
            detail=f"победителей {winners}, до {deadline:%d.%m.%Y %H:%M} UTC",
        )
        return RedirectResponse(url="/contests", status_code=303)

    return router
