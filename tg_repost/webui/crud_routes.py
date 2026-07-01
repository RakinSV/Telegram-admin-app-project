"""CRUD-роуты веб-админки (F23, Фаза 5.3): источники, цели, модерация,
реклама, статистика/расписание/рост.

Зеркалит существующую функциональность `cli.py` и `telegram/moderation_bot.py`
через общие repo-модули (`sources_repo.py`, `targets_repo.py`, `ads/repo.py`,
`moderation.py`) — никакой бизнес-логики здесь нет, только HTTP-обвязка
(см. план Фазы 5, раздел 5.3).

Отдельный модуль от `app.py` (auth/setup/settings/secrets/components) —
держит размер каждого файла разумным.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from tg_repost import sources_repo, targets_repo
from tg_repost import moderation as moderation_repo
from tg_repost.ads import repo as ads_repo
from tg_repost.config import get_settings
from tg_repost.db.models import InvalidStatusTransition
from tg_repost.logging_conf import get_logger
from tg_repost.rewriter.client import KNOWN_STYLES, prompt_exists
from tg_repost.scheduler.growth import build_growth_report
from tg_repost.scheduler.smart_schedule import compute_recommended_slots
from tg_repost.scheduler.stats import compute_stats_summary
from tg_repost.webui import audit, log_broadcast
from tg_repost.webui.auth import require_login
from tg_repost.webui.supervisor import get_components

_SSE_HEARTBEAT_SECONDS = 15.0

logger = get_logger(__name__)

_BASE_DIR = Path(__file__).parent
_templates = Jinja2Templates(directory=str(_BASE_DIR / "templates"))


def build_crud_router() -> APIRouter:
    """CRUD-роуты — все требуют авторизации (см. `auth.require_login`)."""
    router = APIRouter(dependencies=[Depends(require_login)])

    # --- Источники (F01, F12, F15, F16) ---

    @router.get("/sources", response_class=HTMLResponse)
    async def sources_list(request: Request) -> Response:
        return _templates.TemplateResponse(
            request, "sources.html", {"sources": sources_repo.list_sources()},
        )

    @router.post("/sources")
    async def sources_create(request: Request, channel: str = Form(...)) -> Response:
        del request
        source, created = sources_repo.add_source(channel)
        audit.record_audit(
            "source_add" if created else "source_reactivate", target=f"@{source.channel_username}",
        )
        return RedirectResponse(url="/sources", status_code=303)

    @router.get("/sources/{source_id}", response_class=HTMLResponse)
    async def source_detail(request: Request, source_id: int) -> Response:
        source = sources_repo.get_source(source_id)
        if source is None:
            return RedirectResponse(url="/sources", status_code=303)
        return _templates.TemplateResponse(request, "source_detail.html", {
            "source": source, "known_styles": KNOWN_STYLES, "error": None,
        })

    @router.post("/sources/{source_id}")
    async def source_update(
        request: Request,
        source_id: int,
        style_profile: str = Form(""),
        enrich_mode: str = Form("default"),
        target_chat_ids: str = Form(""),
    ) -> Response:
        source = sources_repo.get_source(source_id)
        if source is None:
            return RedirectResponse(url="/sources", status_code=303)

        style = style_profile.strip().lower()
        if style and prompt_exists(style):
            sources_repo.set_source_style(source_id, style)
        if enrich_mode not in ("on", "off", "default"):
            return _templates.TemplateResponse(request, "source_detail.html", {
                "source": source, "known_styles": KNOWN_STYLES,
                "error": "Недопустимый режим добора источников.",
            }, status_code=400)
        sources_repo.set_source_enrich(source_id, enrich_mode)
        try:
            sources_repo.set_source_targets(source_id, target_chat_ids.strip() or None)
        except ValueError:
            return _templates.TemplateResponse(request, "source_detail.html", {
                "source": sources_repo.get_source(source_id),
                "known_styles": KNOWN_STYLES,
                "error": "Цели должны быть числами (chat_id) через запятую.",
            }, status_code=400)
        audit.record_audit(
            "source_update", target=f"#{source_id}",
            detail=f"style={style or 'default'}, enrich={enrich_mode}, "
                   f"targets={target_chat_ids.strip() or 'все'}",
        )
        return RedirectResponse(url=f"/sources/{source_id}", status_code=303)

    @router.post("/sources/{source_id}/delete")
    async def source_delete(request: Request, source_id: int) -> Response:
        del request
        if sources_repo.deactivate_source(source_id):
            audit.record_audit("source_deactivate", target=f"#{source_id}")
        return RedirectResponse(url="/sources", status_code=303)

    # --- Целевые группы (F08, F12) ---

    @router.get("/targets", response_class=HTMLResponse)
    async def targets_list(request: Request) -> Response:
        return _templates.TemplateResponse(
            request, "targets.html", {"targets": targets_repo.list_targets()},
        )

    @router.post("/targets")
    async def targets_create(
        request: Request, chat_id: str = Form(...), title: str = Form("")
    ) -> Response:
        try:
            chat_id_int = int(chat_id.strip())
        except ValueError:
            return _templates.TemplateResponse(request, "targets.html", {
                "targets": targets_repo.list_targets(),
                "error": "chat_id должен быть целым числом.",
            }, status_code=400)
        targets_repo.add_target(chat_id_int, title.strip() or None)
        audit.record_audit("target_add", target=str(chat_id_int))
        return RedirectResponse(url="/targets", status_code=303)

    @router.post("/targets/{target_id}/toggle")
    async def targets_toggle(request: Request, target_id: int) -> Response:
        del request
        new_state = targets_repo.toggle_target(target_id)
        if new_state is not None:
            audit.record_audit("target_toggle", target=f"#{target_id}", detail=f"active={new_state}")
        return RedirectResponse(url="/targets", status_code=303)

    # --- Модерация (F07) ---

    @router.get("/moderation", response_class=HTMLResponse)
    async def moderation_queue(request: Request) -> Response:
        return _templates.TemplateResponse(
            request, "moderation.html", {"posts": moderation_repo.list_pending_posts()},
        )

    @router.get("/moderation/{post_id}", response_class=HTMLResponse)
    async def moderation_detail(request: Request, post_id: int) -> Response:
        post = moderation_repo.get_post(post_id)
        if post is None:
            return RedirectResponse(url="/moderation", status_code=303)
        return _templates.TemplateResponse(
            request, "moderation_detail.html", {"post": post, "error": None},
        )

    @router.post("/moderation/{post_id}/approve")
    async def moderation_approve(request: Request, post_id: int) -> Response:
        application = get_components().application
        if application is None:
            return _templates.TemplateResponse(
                request, "moderation_detail.html",
                {"post": moderation_repo.get_post(post_id),
                 "error": "Бот модерации не запущен — публикация невозможна. "
                          "Запусти компоненты на странице «Компоненты»."},
                status_code=400,
            )
        try:
            outcome = await moderation_repo.approve_post(application.bot, post_id)
        except InvalidStatusTransition as exc:
            return _templates.TemplateResponse(
                request, "moderation_detail.html",
                {"post": moderation_repo.get_post(post_id), "error": str(exc)},
                status_code=400,
            )
        audit.record_audit("post_approve", target=f"#{post_id}", detail=outcome)
        return RedirectResponse(url="/moderation", status_code=303)

    @router.post("/moderation/{post_id}/reject")
    async def moderation_reject(request: Request, post_id: int) -> Response:
        try:
            found = moderation_repo.reject_post(post_id)
        except InvalidStatusTransition as exc:
            return _templates.TemplateResponse(
                request, "moderation_detail.html",
                {"post": moderation_repo.get_post(post_id), "error": str(exc)},
                status_code=400,
            )
        if found:
            audit.record_audit("post_reject", target=f"#{post_id}")
        return RedirectResponse(url="/moderation", status_code=303)

    @router.post("/moderation/{post_id}/edit")
    async def moderation_edit(
        request: Request, post_id: int, rewritten_text: str = Form(...)
    ) -> Response:
        del request
        if moderation_repo.edit_post_text(post_id, rewritten_text):
            audit.record_audit("post_edit", target=f"#{post_id}")
        return RedirectResponse(url=f"/moderation/{post_id}", status_code=303)

    # --- Реклама (F21) ---

    @router.get("/ads", response_class=HTMLResponse)
    async def ads_list(request: Request) -> Response:
        return _templates.TemplateResponse(
            request, "ads.html", {"briefs": ads_repo.list_briefs()},
        )

    @router.post("/ads")
    async def ads_create(
        request: Request, brief_text: str = Form(...), max_uses: str = Form("")
    ) -> Response:
        max_uses = max_uses.strip()
        if not max_uses:
            max_uses_int = None
        elif max_uses.isdigit():
            max_uses_int = int(max_uses)
        else:
            return _templates.TemplateResponse(request, "ads.html", {
                "briefs": ads_repo.list_briefs(),
                "error": "Лимит показов должен быть целым неотрицательным числом или пустым.",
            }, status_code=400)
        brief = ads_repo.add_brief(brief_text.strip(), max_uses_int)
        audit.record_audit("ad_brief_add", target=f"#{brief.id}", detail=brief.brief_text[:80])
        return RedirectResponse(url="/ads", status_code=303)

    @router.post("/ads/{brief_id}/disable")
    async def ads_disable(request: Request, brief_id: int) -> Response:
        del request
        if ads_repo.disable_brief(brief_id):
            audit.record_audit("ad_brief_disable", target=f"#{brief_id}")
        return RedirectResponse(url="/ads", status_code=303)

    # --- Статистика / расписание / рост (F14, F19, F22) ---

    @router.get("/stats", response_class=HTMLResponse)
    async def stats_page(request: Request) -> Response:
        settings = get_settings()
        summary = compute_stats_summary(settings.stats_window_days)
        return _templates.TemplateResponse(request, "stats.html", {"summary": summary})

    @router.get("/stats/best-times", response_class=HTMLResponse)
    async def stats_best_times(request: Request) -> Response:
        settings = get_settings()
        rec = compute_recommended_slots(
            settings.smart_schedule_window_days,
            settings.smart_schedule_top_n,
            settings.smart_schedule_min_posts,
        )
        return _templates.TemplateResponse(request, "best_times.html", {"rec": rec})

    @router.get("/stats/growth", response_class=HTMLResponse)
    async def stats_growth(request: Request) -> Response:
        settings = get_settings()
        report = build_growth_report(
            settings.growth_report_window_days, settings.growth_min_snapshots
        )
        return _templates.TemplateResponse(
            request, "growth.html",
            {"report": report, "window_days": settings.growth_report_window_days},
        )

    # --- Журнал изменений + живые логи (F23, Фаза 5.4) ---

    @router.get("/audit", response_class=HTMLResponse)
    async def audit_page(request: Request) -> Response:
        return _templates.TemplateResponse(
            request, "audit.html", {"entries": audit.list_audit_log()},
        )

    @router.get("/logs", response_class=HTMLResponse)
    async def logs_page(request: Request) -> Response:
        return _templates.TemplateResponse(
            request, "logs.html", {"recent": log_broadcast.recent_logs()},
        )

    @router.get("/logs/stream")
    async def logs_stream(request: Request) -> StreamingResponse:
        async def event_source():
            async with log_broadcast.subscription() as queue:
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        line = await asyncio.wait_for(
                            queue.get(), timeout=_SSE_HEARTBEAT_SECONDS
                        )
                    except TimeoutError:
                        yield ": keep-alive\n\n"
                        continue
                    yield _sse_event(line)

        return StreamingResponse(event_source(), media_type="text/event-stream")

    return router


def _sse_event(text: str) -> str:
    """Отформатировать многострочный текст (напр. traceback) как одно
    SSE-сообщение — каждая физическая строка со своим префиксом `data:`,
    как того требует спецификация SSE для восстановления переводов строк."""
    return "".join(f"data: {line}\n" for line in text.splitlines() or [""]) + "\n"
