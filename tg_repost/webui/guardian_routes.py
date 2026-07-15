"""Управление Guardian (отдельный бот-модератор группы, `guardian/`) из
веб-админки tg_repost — единая админ-панель на оба бота, по явному запросу
пользователя ("вывести управление этим ботом в админку").

Guardian — отдельный процесс/контейнер со своей БД (см. `guardian/GUARDIAN.md`),
но этот модуль читает и пишет её НАПРЯМУЮ (кросс-пакетный импорт `guardian.*`
прямо из процесса tg_repost) — оба пакета живут в одном репозитории/venv,
отдельного API между ними заводить избыточно для однопользовательского
инструмента. Оверлей настроек Guardian (`guardian.config.get_guardian_settings()`)
спроектирован читать `bot_config` заново на каждый вызов именно ради этого —
см. его docstring про кросс-процессную свежесть: запись отсюда обязана быть
видна процессу Guardian без перезапуска.

Аутентификация — та же сессия tg_repost (`Depends(require_login)`), отдельного
логина для Guardian нет. Мутации пишут В АУДИТ tg_repost (`webui/audit.py`),
не в лог-канал Guardian — тот зарезервирован под Telegram-уведомления о
действиях модерации (см. `guardian/services/log_channel.py`), веб-панель уже
имеет свой независимый журнал."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from guardian import domains_repo, settings_store, stopwords_repo, trusted_repo
from guardian.config import get_guardian_settings
from tg_repost.webui import audit, guardian_dashboard, i18n
from tg_repost.webui.auth import require_login
from tg_repost.webui.form_utils import coerce_form_value

_BASE_DIR = Path(__file__).parent
_templates = Jinja2Templates(directory=str(_BASE_DIR / "templates"))
# См. аналогичный комментарий в crud_routes.py — отдельный Environment,
# глобалы регистрируются в каждом модуле, что строит Jinja2Templates.
_templates.env.globals["t"] = i18n.t
_templates.env.globals["current_lang"] = i18n.get_current_lang
_templates.env.globals["humanize_action"] = i18n.humanize_action


def _settings_groups_context() -> list[dict]:
    return [
        {
            "key": group.key,
            "title": i18n.t(f"guardian.settings.group.{group.key}.title"),
            "description": i18n.t(f"guardian.settings.group.{group.key}.desc"),
            "fields": [
                {
                    "name": f.name,
                    "label": i18n.t(f"guardian.settings.field.{f.name}.label"),
                    "value_type": f.value_type,
                    "choices": f.choices,
                    "value": settings_store.effective_value(f),
                }
                for f in group.fields
            ],
        }
        for group in settings_store.SETTINGS_GROUPS
    ]


def build_guardian_router() -> APIRouter:
    router = APIRouter(prefix="/guardian", dependencies=[Depends(require_login)])

    @router.get("", response_class=HTMLResponse)
    async def guardian_dashboard_page(request: Request) -> Response:
        settings = get_guardian_settings()
        context = {
            "is_configured": settings.is_configured,
            "spam_mode": settings.spam_mode,
            "captcha_type": settings.captcha_type,
            "warn_thresholds": (
                settings.warn_threshold_mute,
                settings.warn_threshold_kick,
                settings.warn_threshold_ban,
            ),
            "counts": guardian_dashboard.counts(settings.guardian_group_id),
            "recent_log": guardian_dashboard.recent_moderation_log(
                settings.guardian_group_id
            ),
        }
        return _templates.TemplateResponse(request, "guardian_dashboard.html", context)

    # --- Настройки ---

    @router.get("/settings", response_class=HTMLResponse)
    async def guardian_settings_page(request: Request) -> Response:
        return _templates.TemplateResponse(
            request,
            "guardian_settings.html",
            {"groups": _settings_groups_context(), "error": None},
        )

    @router.post("/settings/{group_key}")
    async def guardian_settings_save(request: Request, group_key: str) -> Response:
        group = next(
            (g for g in settings_store.SETTINGS_GROUPS if g.key == group_key), None
        )
        if group is not None:
            form = await request.form()
            try:
                coerced = {
                    field.name: coerce_form_value(
                        field.value_type, form.get(field.name)
                    )
                    for field in group.fields
                }
            except ValueError:
                return _templates.TemplateResponse(
                    request,
                    "guardian_settings.html",
                    {
                        "groups": _settings_groups_context(),
                        "error": i18n.t(
                            "settings.error_invalid_number",
                            group=i18n.t(f"guardian.settings.group.{group.key}.title"),
                        ),
                    },
                    status_code=400,
                )
            for field in group.fields:
                if (
                    field.choices is not None
                    and coerced[field.name] not in field.choices
                ):
                    return _templates.TemplateResponse(
                        request,
                        "guardian_settings.html",
                        {
                            "groups": _settings_groups_context(),
                            "error": i18n.t(
                                "settings.error_invalid_choice",
                                field=i18n.t(f"guardian.settings.field.{field.name}.label"),
                                choices=", ".join(field.choices),
                            ),
                        },
                        status_code=400,
                    )
            for field in group.fields:
                settings_store.save_setting(
                    field.name, coerced[field.name], field.value_type
                )
                audit.record_audit(
                    "guardian_setting_set",
                    target=field.name,
                    detail=str(coerced[field.name]),
                )
        return RedirectResponse(url="/guardian/settings", status_code=303)

    # --- Стоп-слова (G03) ---

    @router.get("/stopwords", response_class=HTMLResponse)
    async def guardian_stopwords_page(request: Request) -> Response:
        return _templates.TemplateResponse(
            request,
            "guardian_stopwords.html",
            {"words": stopwords_repo.list_stopwords()},
        )

    @router.post("/stopwords")
    async def guardian_stopwords_add(
        request: Request, word: str = Form(...)
    ) -> Response:
        del request
        if stopwords_repo.add_stopword(word, added_by="webui"):
            audit.record_audit("guardian_stopword_add", target=word.strip().lower())
        return RedirectResponse(url="/guardian/stopwords", status_code=303)

    @router.post("/stopwords/delete")
    async def guardian_stopwords_delete(
        request: Request, word: str = Form(...)
    ) -> Response:
        del request
        if stopwords_repo.remove_stopword(word):
            audit.record_audit("guardian_stopword_remove", target=word.strip().lower())
        return RedirectResponse(url="/guardian/stopwords", status_code=303)

    # --- Whitelist доменов (G04) ---

    @router.get("/domains", response_class=HTMLResponse)
    async def guardian_domains_page(request: Request) -> Response:
        return _templates.TemplateResponse(
            request,
            "guardian_domains.html",
            {"domains": domains_repo.list_allowed_domains()},
        )

    @router.post("/domains")
    async def guardian_domains_add(
        request: Request, domain: str = Form(...)
    ) -> Response:
        del request
        added = domains_repo.add_allowed_domain(domain, updated_by="webui")
        if added:
            audit.record_audit("guardian_domain_add", target=added)
        return RedirectResponse(url="/guardian/domains", status_code=303)

    @router.post("/domains/delete")
    async def guardian_domains_delete(
        request: Request, domain: str = Form(...)
    ) -> Response:
        del request
        if domains_repo.remove_allowed_domain(domain, updated_by="webui"):
            audit.record_audit("guardian_domain_remove", target=domain.strip().lower())
        return RedirectResponse(url="/guardian/domains", status_code=303)

    # --- Доверенные пользователи, "исключения" (G12) ---

    @router.get("/trusted", response_class=HTMLResponse)
    async def guardian_trusted_page(request: Request) -> Response:
        chat_id = get_guardian_settings().guardian_group_id
        return _templates.TemplateResponse(
            request,
            "guardian_trusted.html",
            {
                "trusted": trusted_repo.list_trusted(chat_id) if chat_id else [],
                "chat_id_missing": not chat_id,
                "error": None,
            },
        )

    @router.post("/trusted")
    async def guardian_trusted_add(
        request: Request, user_id: str = Form(...), reason: str = Form("")
    ) -> Response:
        chat_id = get_guardian_settings().guardian_group_id
        if not chat_id:
            return _templates.TemplateResponse(
                request,
                "guardian_trusted.html",
                {
                    "trusted": [],
                    "chat_id_missing": True,
                    "error": i18n.t("guardian_trusted.error_no_group"),
                },
                status_code=400,
            )
        if not user_id.strip().lstrip("-").isdigit():
            return _templates.TemplateResponse(
                request,
                "guardian_trusted.html",
                {
                    "trusted": trusted_repo.list_trusted(chat_id),
                    "chat_id_missing": False,
                    "error": i18n.t("guardian_trusted.error_invalid_user_id"),
                },
                status_code=400,
            )
        user_id_int = int(user_id.strip())
        if trusted_repo.add_trusted(
            user_id_int, chat_id, added_by="webui", reason=reason.strip() or None
        ):
            audit.record_audit(
                "guardian_trust_add",
                target=str(user_id_int),
                detail=reason.strip() or None,
            )
        return RedirectResponse(url="/guardian/trusted", status_code=303)

    @router.post("/trusted/{user_id}/delete")
    async def guardian_trusted_delete(request: Request, user_id: int) -> Response:
        del request
        chat_id = get_guardian_settings().guardian_group_id
        if trusted_repo.remove_trusted(user_id, chat_id, actor="webui"):
            audit.record_audit("guardian_trust_remove", target=str(user_id))
        return RedirectResponse(url="/guardian/trusted", status_code=303)

    return router
