"""Боты и сценарии-конструкторы (F75) — веб-роуты.

ВСЁ ЗДЕСЬ, И БОЛЬШЕ НИГДЕ. Требование владельца дословно: «все токены все
настройки ботов и все все все — в настройках в админке». Поэтому бот
добавляется, проверяется, включается и выключается страницей, а не файлом
окружения и не заходом по SSH. Отсюда же следует, что после каждой правки
опрос ботов перезапускается сразу: настройка, действующая «после перезапуска
контейнера», — это половина настройки.

ТОКЕН НАРУЖУ НЕ ОТДАЁТСЯ НИКОГДА, даже владельцу: `BotView` его не содержит
вовсе, и подставить в поле формы нечего. Поэтому пустое поле при правке
означает «не меняли», а не «очистить» — иначе переименование бота стирало бы
ему токен.

ХОЛСТ РИСУЕТ ЧЕРНОВИК, ПУБЛИКАЦИЯ СНИМАЕТ КОПИЮ. Правки уходят в версию 0
целиком (холст присылает всю схему), а «Опубликовать» проверяет граф и
отказывает с перечнем проблем: выпустить сценарий, в котором человек
застрянет, хуже, чем не выпустить.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from tg_repost import flow_schema, managed_bots_repo
from tg_repost import flows_repo as flows
from tg_repost.logging_conf import get_logger
from tg_repost.webui import audit, flash, i18n
from tg_repost.webui.auth import require_login
from tg_repost.webui.templating import build_templates

logger = get_logger(__name__)

_templates = build_templates()


async def _restart_bots() -> None:
    """Перечитать реестр живыми ботами.

    Импорт локальный: супервизор тянет за собой Telethon и бота модерации, а
    страница ботов должна открываться и в тестах, где ничего этого нет.
    """
    try:
        from tg_repost.webui import supervisor

        await supervisor.restart_flow_bots()
    except Exception as exc:  # noqa: BLE001
        # Не смогли перезапустить опрос — это стоит записать, но не стоит
        # отменять сохранение: бот уже в реестре, и следующий старт процесса
        # его поднимет.
        logger.warning("F75: опрос ботов не перезапущен: %s", exc)


def _kinds_for_canvas() -> list[dict]:
    """Описание типов узлов для холста, с переводами.

    Переводы резолвятся ЗДЕСЬ, а не в JavaScript: язык известен серверу, а
    каталог строк один на всю админку.
    """
    result = []
    for kind, node in flow_schema.KINDS.items():
        result.append({
            "kind": kind,
            "category": node.category,
            "label": i18n.t(f"flows.kind_{kind}"),
            "fields": [
                {
                    "name": field.name,
                    "type": field.kind,
                    "required": field.required,
                    "label": i18n.t(f"flows.field_{field.name}"),
                    "choices": [
                        {"value": choice, "label": i18n.t(f"flows.operator_{choice}")}
                        for choice in field.choices
                    ],
                    "default": field.default,
                }
                for field in node.fields
            ],
            "conditions": [
                {"value": condition, "label": i18n.t(f"flows.condition_{condition}")}
                for condition in flows.allowed_conditions(kind)
            ],
            "defaults": flow_schema.defaults_for(kind),
        })
    return result


# Строки для холста. Резолвятся на сервере по той же причине, что и названия
# узлов: каталог переводов один, и второй его копии в JavaScript быть не должно.
_CANVAS_TEXT_KEYS = (
    "unsaved", "saved", "saving", "save_failed", "connect", "connecting_hint",
    "choose_condition", "cancel", "select_hint", "node_key", "edges_out", "no_edges",
    "delete_edge", "delete_node", "condition_value", "buttons_hint",
    "list_hint", "hours_n", "undone", "nothing_to_undo", "copy_node",
)


def _canvas_text() -> dict[str, str]:
    text = {key: i18n.t(f"flows.canvas_{key}") for key in _CANVAS_TEXT_KEYS}
    for category in flow_schema.CATEGORIES:
        text[f"category_{category}"] = i18n.t(f"flows.category_{category}")
    return text


def build_bots_router() -> APIRouter:
    router = APIRouter(dependencies=[Depends(require_login)])

    def _bots_page(request: Request, error: str | None = None,
                   status: int = 200, name: str = "") -> Response:
        return _templates.TemplateResponse(
            request, "bots.html",
            {
                "bots": managed_bots_repo.list_all(),
                "error": error,
                "name": name,
            },
            status_code=status,
        )

    @router.get("/bots", response_class=HTMLResponse)
    async def bots_page(request: Request) -> Response:
        return _bots_page(request)

    @router.post("/bots/save")
    async def bots_save(
        request: Request,
        bot_id: str = Form(""),
        name: str = Form(""),
        token: str = Form(""),
        is_active: str = Form(""),
    ) -> Response:
        existing = int(bot_id) if bot_id.isdigit() else None
        try:
            saved_id = await managed_bots_repo.save(
                name, token, bot_id=existing, is_active=bool(is_active),
            )
        except managed_bots_repo.InvalidBot as exc:
            return _bots_page(request, error=str(exc), status=400, name=name)

        audit.record_audit(
            "bot_save", target=name.strip(),
            detail="новый" if existing is None else "правка",
        )
        await _restart_bots()
        flash.set_flash(request, i18n.t("bots.saved"))
        return RedirectResponse(url=f"/bots/{saved_id}/flows", status_code=303)

    @router.post("/bots/{bot_id}/toggle")
    async def bots_toggle(request: Request, bot_id: int) -> Response:
        view = managed_bots_repo.get(bot_id)
        if view is None:
            return RedirectResponse(url="/bots", status_code=303)
        managed_bots_repo.set_active(bot_id, not view.is_active)
        audit.record_audit(
            "bot_deactivate" if view.is_active else "bot_activate", target=view.name,
        )
        await _restart_bots()
        return RedirectResponse(url="/bots", status_code=303)

    @router.post("/bots/{bot_id}/delete")
    async def bots_delete(request: Request, bot_id: int) -> Response:
        view = managed_bots_repo.get(bot_id)
        if view is None:
            return RedirectResponse(url="/bots", status_code=303)
        if not managed_bots_repo.delete(bot_id):
            # Сценарии остались: бот выключен, но не удалён — прохождения
            # людей внутри его сценариев ссылаются на узлы.
            await _restart_bots()
            return _bots_page(
                request, error=i18n.t("bots.error_has_flows", n=view.flows_count),
                status=400,
            )
        audit.record_audit("bot_delete", target=view.name)
        await _restart_bots()
        return RedirectResponse(url="/bots", status_code=303)

    # --- сценарии бота ---

    def _flows_page(request: Request, bot_id: int, error: str | None = None,
                    status: int = 200) -> Response:
        view = managed_bots_repo.get(bot_id)
        if view is None:
            return RedirectResponse(url="/bots", status_code=303)
        rows = []
        for flow in flows.list_for_bot(bot_id):
            rows.append({"view": flow, "runs": flows.runs_of(flow.id)})
        return _templates.TemplateResponse(
            request, "flows.html",
            {
                "bot": view,
                "flows": rows,
                "error": error,
                "triggers": ("start", "command", "keyword"),
            },
            status_code=status,
        )

    @router.get("/bots/{bot_id}/flows", response_class=HTMLResponse)
    async def flows_page(request: Request, bot_id: int) -> Response:
        return _flows_page(request, bot_id)

    @router.post("/bots/{bot_id}/flows/create")
    async def flow_create(
        request: Request,
        bot_id: int,
        name: str = Form(""),
        trigger: str = Form("start"),
        trigger_value: str = Form(""),
    ) -> Response:
        if managed_bots_repo.get(bot_id) is None:
            return RedirectResponse(url="/bots", status_code=303)
        try:
            flow_id = flows.create(
                bot_id, name, trigger=trigger, trigger_value=trigger_value,
            )
        except flows.InvalidFlow as exc:
            return _flows_page(request, bot_id, error=str(exc), status=400)
        audit.record_audit("flow_create", target=name.strip())
        return RedirectResponse(url=f"/flows/{flow_id}", status_code=303)

    @router.get("/flows/{flow_id}", response_class=HTMLResponse)
    async def flow_edit(request: Request, flow_id: int) -> Response:
        flow = flows.get(flow_id)
        if flow is None:
            return RedirectResponse(url="/bots", status_code=303)
        graph = flows.load(flow_id, flows.DRAFT)
        return _templates.TemplateResponse(
            request, "flow_edit.html",
            {
                "flow": flow,
                "bot": managed_bots_repo.get(flow.bot_id),
                "runs": flows.runs_of(flow_id),
                # Схема и черновик уходят в страницу как JSON: холст рисуется
                # одним скриптом без сборки, и подставлять данные в разметку
                # построчно значило бы держать две правды об одном графе.
                "kinds_json": json.dumps(_kinds_for_canvas(), ensure_ascii=False),
                "text_json": json.dumps(_canvas_text(), ensure_ascii=False),
                "graph_json": json.dumps(
                    {
                        "nodes": [
                            {"node_key": n.node_key, "kind": n.kind,
                             "config": n.config, "x": n.x, "y": n.y}
                            for n in graph.nodes.values()
                        ],
                        "edges": [
                            {"from_key": e.from_key, "to_key": e.to_key,
                             "condition": e.condition,
                             "condition_value": e.condition_value}
                            for e in graph.edges
                        ],
                    },
                    ensure_ascii=False,
                ),
            },
        )

    @router.post("/flows/{flow_id}/save")
    async def flow_save(request: Request, flow_id: int) -> Response:
        """Сохранить черновик целиком (запрос от холста, JSON)."""
        if flows.get(flow_id) is None:
            return JSONResponse({"ok": False, "error": "нет такого сценария"},
                                status_code=404)
        payload = await request.json()
        try:
            flows.save_draft(
                flow_id, payload.get("nodes") or [], payload.get("edges") or [],
            )
        except flows.InvalidFlow as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        audit.record_audit(
            "flow_draft_save", target=str(flow_id),
            detail=f"узлов {len(payload.get('nodes') or [])}",
        )
        graph = flows.load(flow_id, flows.DRAFT)
        return JSONResponse({"ok": True, "problems": flows.validate(graph)})

    @router.post("/flows/{flow_id}/publish")
    async def flow_publish(request: Request, flow_id: int) -> Response:
        flow = flows.get(flow_id)
        if flow is None:
            return RedirectResponse(url="/bots", status_code=303)
        try:
            version = flows.publish(flow_id)
        except flows.InvalidFlow as exc:
            flash.set_flash(request, i18n.t("flows.publish_failed", problems=str(exc)))
            return RedirectResponse(url=f"/flows/{flow_id}", status_code=303)
        audit.record_audit("flow_publish", target=flow.name, detail=f"версия {version}")
        flash.set_flash(request, i18n.t("flows.publish_done", n=version), kind="ok")
        return RedirectResponse(url=f"/flows/{flow_id}", status_code=303)

    @router.post("/flows/{flow_id}/delete")
    async def flow_delete(request: Request, flow_id: int) -> Response:
        flow = flows.get(flow_id)
        if flow is None:
            return RedirectResponse(url="/bots", status_code=303)
        bot_id = flow.bot_id
        if flows.delete(flow_id):
            audit.record_audit("flow_delete", target=flow.name)
        return RedirectResponse(url=f"/bots/{bot_id}/flows", status_code=303)

    return router
