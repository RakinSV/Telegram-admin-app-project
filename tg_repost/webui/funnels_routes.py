"""Воронки (F71) — веб-роуты.

ФОРМА, А НЕ КОНСТРУКТОР. У конкурентов визуальный редактор с drag-n-drop —
главный аргумент продажи, потому что их пользователь не программист. Здесь
пользователь — автор системы, и обычная форма даёт тот же результат за долю
усилий. Шаги вводятся парами «через сколько часов» + «текст»; пустые строки
отбрасываются, поэтому «добавить шаг» — это просто заполнить следующую, а
«удалить» — очистить текст.

ДВА МЕСТА, ГДЕ ИНТЕРФЕЙС ОБЯЗАН ПРЕДУПРЕДИТЬ, А НЕ СДЕЛАТЬ МОЛЧА:

* **правка шагов у воронки, по которой уже идут люди.** Позиция человека
  хранится номером шага, а не текстом. Вставили шаг в середину — и те, кто
  уже прошёл дальше, получат чужое сообщение; убрали хвост — цепочка у них
  закончится досрочно. Число идущих показано прямо над формой;
* **включение воронки.** Выключенная воронка безобидна, включённая начинает
  писать живым людям с первого же `/start`.

Удаление подтверждается отдельно: вместе с воронкой пропадает история
прохождений, а её ничем не восстановить.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from tg_repost import funnels_repo
from tg_repost.webui import audit, i18n
from tg_repost.webui.templating import build_templates
from tg_repost.webui.auth import require_login

_BASE_DIR = Path(__file__).parent
_templates = build_templates()

# Сколько пустых строк дорисовать под новые шаги. Три — чтобы добавление
# пары шагов не требовало сохранять и открывать форму заново, и при этом
# форма не превращалась в простыню на весь предел в 20 шагов.
_SPARE_ROWS = 3


def _rows(view: funnels_repo.FunnelView | None) -> list[dict]:
    """Строки формы: существующие шаги плюс запас пустых."""
    rows = [
        {"delay_hours": step.delay_hours, "text": step.text}
        for step in (view.steps if view is not None else ())
    ]
    spare = min(_SPARE_ROWS, funnels_repo.MAX_STEPS - len(rows))
    rows.extend({"delay_hours": 24, "text": ""} for _ in range(spare))
    return rows


def _steps_from_form(delays: list[str], texts: list[str]) -> list[dict]:
    """Собрать шаги из формы, отбросив пустые строки.

    Пустая строка — это НЕ ошибка ввода, а способ не заполнять запас до
    конца и способ удалить шаг. А вот задержка без текста отбрасывается
    вместе со строкой: сообщения в ней нет, отправлять нечего.
    """
    steps: list[dict] = []
    for index, text in enumerate(texts):
        if not text.strip():
            continue
        raw_delay = delays[index].strip() if index < len(delays) else "0"
        try:
            delay = int(raw_delay or 0)
        except ValueError:
            raise funnels_repo.InvalidFunnel(
                i18n.t("funnels.error_delay_not_number", n=index + 1)
            ) from None
        steps.append({"delay_hours": delay, "text": text.strip()})
    return steps


def build_funnels_router() -> APIRouter:
    router = APIRouter(dependencies=[Depends(require_login)])

    def _listing(request: Request, error: str | None = None, status: int = 200) -> Response:
        views = funnels_repo.list_all()
        return _templates.TemplateResponse(
            request, "funnels.html",
            {
                "funnels": [
                    {"view": view, "runs": funnels_repo.runs_of(view.id)}
                    for view in views
                ],
                "error": error,
            },
            status_code=status,
        )

    @router.get("/funnels", response_class=HTMLResponse)
    async def funnels_page(request: Request) -> Response:
        return _listing(request)

    @router.get("/funnels/new", response_class=HTMLResponse)
    async def funnel_new(request: Request) -> Response:
        return _templates.TemplateResponse(
            request, "funnel_edit.html",
            {"funnel": None, "rows": _rows(None), "running": 0, "error": None},
        )

    @router.get("/funnels/{funnel_id}", response_class=HTMLResponse)
    async def funnel_edit(request: Request, funnel_id: int) -> Response:
        view = funnels_repo.get(funnel_id)
        if view is None:
            return RedirectResponse(url="/funnels", status_code=303)
        return _templates.TemplateResponse(
            request, "funnel_edit.html",
            {
                "funnel": view,
                "rows": _rows(view),
                # Предупреждение о людях в пути — см. docstring модуля.
                "running": funnels_repo.runs_of(funnel_id)["running"],
                "error": None,
            },
        )

    @router.post("/funnels/save")
    async def funnel_save(
        request: Request,
        funnel_id: str = Form(""),
        name: str = Form(""),
        delay_hours: list[str] = Form(default=[]),
        text: list[str] = Form(default=[]),
    ) -> Response:
        existing = int(funnel_id) if funnel_id.isdigit() else None
        view = funnels_repo.get(existing) if existing is not None else None
        if existing is not None and view is None:
            return RedirectResponse(url="/funnels", status_code=303)

        try:
            steps = _steps_from_form(delay_hours, text)
            # Состояние «включена» правкой не меняется: включение — отдельное
            # действие со своей записью в журнале, иначе сохранение текста
            # незаметно запускало бы рассылку живым людям.
            saved_id = funnels_repo.save(
                name, steps,
                funnel_id=existing,
                is_active=view.is_active if view is not None else False,
            )
        except funnels_repo.InvalidFunnel as exc:
            return _templates.TemplateResponse(
                request, "funnel_edit.html",
                {
                    "funnel": view,
                    "rows": [
                        {"delay_hours": d, "text": t}
                        for d, t in zip(delay_hours, text, strict=False)
                    ] or _rows(None),
                    "running": funnels_repo.runs_of(existing)["running"] if existing else 0,
                    "name": name,
                    "error": str(exc),
                },
                status_code=400,
            )

        audit.record_audit(
            "funnel_save", target=name.strip(),
            detail=f"шагов {len(steps)}",
        )
        return RedirectResponse(url=f"/funnels/{saved_id}", status_code=303)

    @router.post("/funnels/{funnel_id}/toggle")
    async def funnel_toggle(request: Request, funnel_id: int) -> Response:
        view = funnels_repo.get(funnel_id)
        if view is None:
            return RedirectResponse(url="/funnels", status_code=303)
        if not view.steps and not view.is_active:
            # Включить воронку без шагов — значит записывать людей в цепочку,
            # которая ничего им не пришлёт.
            return _listing(request, error=i18n.t("funnels.error_no_steps"), status=400)

        funnels_repo.set_active(funnel_id, not view.is_active)
        audit.record_audit(
            "funnel_activate" if not view.is_active else "funnel_deactivate",
            target=view.name,
        )
        return RedirectResponse(url="/funnels", status_code=303)

    @router.post("/funnels/{funnel_id}/delete")
    async def funnel_delete(funnel_id: int) -> Response:
        view = funnels_repo.get(funnel_id)
        if view is not None and funnels_repo.delete(funnel_id):
            audit.record_audit("funnel_delete", target=view.name)
        return RedirectResponse(url="/funnels", status_code=303)

    return router
