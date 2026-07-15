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

from tg_repost import sources_repo, targets_repo, telethon_sessions_repo
from tg_repost import moderation as moderation_repo
from tg_repost.ads import repo as ads_repo
from tg_repost.config import get_settings
from tg_repost.db.models import InvalidStatusTransition, parse_chat_ids_csv
from tg_repost.logging_conf import get_logger
from tg_repost.rewriter.client import KNOWN_STYLES, prompt_exists
from tg_repost.scheduler.growth import build_growth_report
from tg_repost.scheduler.smart_schedule import apply_recommended_slots, compute_recommended_slots
from tg_repost.scheduler.stats import compute_stats_summary
from tg_repost.webui import audit, i18n, log_broadcast
from tg_repost.webui.auth import require_login
from tg_repost.webui.supervisor import get_components, resync_scheduler_jobs

_SSE_HEARTBEAT_SECONDS = 15.0
# Совпадает с дефолтным `limit` в sources_repo.list_sources/targets_repo.
# list_targets/ads.repo.list_briefs — используется только для индикации
# «список мог быть обрезан» в шаблонах (аудит Фазы 5), сам лимит задаётся
# в repo-функциях.
_LIST_LIMIT = 500

logger = get_logger(__name__)

_BASE_DIR = Path(__file__).parent
_templates = Jinja2Templates(directory=str(_BASE_DIR / "templates"))
# Отдельный экземпляр Jinja2Templates/Environment от `app.py` (тот же каталог
# шаблонов на диске, но другой объект в памяти) — глобалы `t`/`current_lang`
# нужно регистрировать в КАЖДОМ, иначе `{{ t(...) }}` в шаблонах, отданных
# через ЭТОТ роутер, упадёт с UndefinedError.
_templates.env.globals["t"] = i18n.t
_templates.env.globals["current_lang"] = i18n.get_current_lang
_templates.env.globals["humanize_action"] = i18n.humanize_action


def build_crud_router() -> APIRouter:
    """CRUD-роуты — все требуют авторизации (см. `auth.require_login`)."""
    router = APIRouter(dependencies=[Depends(require_login)])

    # --- Источники (F01, F12, F15, F16) ---

    @router.get("/sources", response_class=HTMLResponse)
    async def sources_list(request: Request) -> Response:
        sources = sources_repo.list_sources()
        return _templates.TemplateResponse(request, "sources.html", {
            "sources": sources, "truncated": len(sources) >= _LIST_LIMIT,
        })

    @router.post("/sources")
    async def sources_create(request: Request, channel: str = Form(...)) -> Response:
        del request
        source, created = sources_repo.add_source(channel)
        audit.record_audit(
            "source_add" if created else "source_reactivate", target=f"@{source.channel_username}",
        )
        return RedirectResponse(url="/sources", status_code=303)

    def _source_detail_context(source, error: str | None = None) -> dict:
        """Контекст source_detail: источник + список целей с отметкой, куда
        этот источник уже публикует (чекбоксы вместо ручного ввода chat_id).

        Показываем ВСЕ цели (в т.ч. неактивные — с пометкой), плюс «осиротевшие»
        chat_id из target_chat_ids источника, которых уже нет в таблице целей,
        чтобы галочка по ним не терялась молча при сохранении."""
        selected = set(parse_chat_ids_csv(source.target_chat_ids))
        targets = targets_repo.list_targets()
        known_chat_ids = {t.chat_id for t in targets}
        orphan_ids = sorted(selected - known_chat_ids)
        return {
            "source": source,
            "known_styles": KNOWN_STYLES,
            "targets": targets,
            "selected_chat_ids": selected,
            "orphan_ids": orphan_ids,
            "error": error,
        }

    @router.get("/sources/{source_id}", response_class=HTMLResponse)
    async def source_detail(request: Request, source_id: int) -> Response:
        source = sources_repo.get_source(source_id)
        if source is None:
            return RedirectResponse(url="/sources", status_code=303)
        return _templates.TemplateResponse(
            request, "source_detail.html", _source_detail_context(source),
        )

    @router.post("/sources/{source_id}")
    async def source_update(request: Request, source_id: int) -> Response:
        source = sources_repo.get_source(source_id)
        if source is None:
            return RedirectResponse(url="/sources", status_code=303)

        # `getlist` — чекбоксы целей шлют одноимённые поля target_chat_ids;
        # надёжнее, чем list[str]=Form() (тот молча отдавал пустой список для
        # повторяющихся полей на этой версии FastAPI — найдено тестом).
        form = await request.form()
        style_profile = str(form.get("style_profile", ""))
        enrich_mode = str(form.get("enrich_mode", "default"))
        checked_targets = [str(v) for v in form.getlist("target_chat_ids")]

        style = style_profile.strip().lower()
        if style and prompt_exists(style):
            sources_repo.set_source_style(source_id, style)
        if enrich_mode not in ("on", "off", "default"):
            return _templates.TemplateResponse(
                request, "source_detail.html",
                _source_detail_context(source, i18n.t("source_detail.error_invalid_enrich_mode")),
                status_code=400,
            )
        sources_repo.set_source_enrich(source_id, enrich_mode)
        # Чекбоксы шлют список выбранных chat_id; пусто — публикация во все
        # активные цели (target_chat_ids=None). Собираем в тот же CSV-формат,
        # что и раньше — set_source_targets валидирует, что всё числовое.
        csv = ",".join(c.strip() for c in checked_targets if c.strip())
        try:
            sources_repo.set_source_targets(source_id, csv or None)
        except ValueError:
            return _templates.TemplateResponse(
                request, "source_detail.html",
                _source_detail_context(
                    sources_repo.get_source(source_id),
                    i18n.t("source_detail.error_invalid_targets"),
                ),
                status_code=400,
            )
        audit.record_audit(
            "source_update", target=f"#{source_id}",
            detail=f"style={style or 'default'}, enrich={enrich_mode}, "
                   f"targets={csv or 'все'}",
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
        targets = targets_repo.list_targets()
        return _templates.TemplateResponse(request, "targets.html", {
            "targets": targets, "truncated": len(targets) >= _LIST_LIMIT, "error": None,
        })

    @router.post("/targets")
    async def targets_create(
        request: Request, chat_id: str = Form(...), title: str = Form("")
    ) -> Response:
        try:
            chat_id_int = int(chat_id.strip())
        except ValueError:
            return _templates.TemplateResponse(request, "targets.html", {
                "targets": targets_repo.list_targets(),
                "error": i18n.t("targets.error_invalid_chat_id"),
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

    # --- Доп. Telethon-сессии (F26) ---

    @router.get("/telethon-sessions", response_class=HTMLResponse)
    async def telethon_sessions_list(request: Request) -> Response:
        return _templates.TemplateResponse(request, "telethon_sessions.html", {
            "sessions": telethon_sessions_repo.list_sessions(), "error": None,
        })

    @router.post("/telethon-sessions")
    async def telethon_sessions_create(
        request: Request, label: str = Form(...), session_string: str = Form(...),
    ) -> Response:
        try:
            row = telethon_sessions_repo.add_session(label, session_string)
        except ValueError as exc:
            return _templates.TemplateResponse(request, "telethon_sessions.html", {
                "sessions": telethon_sessions_repo.list_sessions(), "error": str(exc),
            }, status_code=400)
        audit.record_audit("telethon_session_add", target=row.label)
        return RedirectResponse(url="/telethon-sessions", status_code=303)

    @router.post("/telethon-sessions/{session_id}/disable")
    async def telethon_sessions_disable(request: Request, session_id: int) -> Response:
        del request
        if telethon_sessions_repo.deactivate_session(session_id):
            audit.record_audit("telethon_session_disable", target=f"#{session_id}")
        return RedirectResponse(url="/telethon-sessions", status_code=303)

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
                 "error": i18n.t("moderation_detail.error_bot_not_running")},
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
        briefs = ads_repo.list_briefs()
        return _templates.TemplateResponse(request, "ads.html", {
            "briefs": briefs, "truncated": len(briefs) >= _LIST_LIMIT, "error": None,
        })

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
                "error": i18n.t("ads.error_invalid_max_uses"),
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
    async def stats_best_times(request: Request, applied: int = 0) -> Response:
        settings = get_settings()
        rec = compute_recommended_slots(
            settings.smart_schedule_window_days,
            settings.smart_schedule_top_n,
            settings.smart_schedule_min_posts,
        )
        return _templates.TemplateResponse(
            request, "best_times.html", {"rec": rec, "just_applied": bool(applied)},
        )

    @router.post("/stats/best-times/apply")
    async def stats_best_times_apply(request: Request) -> Response:
        """Применить текущую рекомендацию к `posting_slots` вручную, не
        дожидаясь ежедневной автоматической джобы (F19, доделка Фазы 4) —
        всегда доступно администратору, независимо от настройки
        `smart_schedule_auto_apply` (та управляет только периодическим
        автоприменением)."""
        del request
        settings = get_settings()
        rec = compute_recommended_slots(
            settings.smart_schedule_window_days,
            settings.smart_schedule_top_n,
            settings.smart_schedule_min_posts,
        )
        applied = apply_recommended_slots(rec)
        if applied:
            audit.record_audit(
                "setting_set", target="posting_slots",
                detail=", ".join(rec.recommended_slots) + " (умное расписание)",
            )
            if get_components().is_running:
                await resync_scheduler_jobs()
        return RedirectResponse(
            url=f"/stats/best-times?applied={int(applied)}", status_code=303,
        )

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
    async def audit_page(request: Request, page: int = 1) -> Response:
        page = max(page, 1)
        total = audit.count_audit_log()
        pages = max((total + audit.PAGE_SIZE - 1) // audit.PAGE_SIZE, 1)
        page = min(page, pages)
        entries = audit.list_audit_log(
            limit=audit.PAGE_SIZE, offset=(page - 1) * audit.PAGE_SIZE,
        )
        return _templates.TemplateResponse(request, "audit.html", {
            "entries": entries, "page": page, "pages": pages, "total": total,
        })

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
