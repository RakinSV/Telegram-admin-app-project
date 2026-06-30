"""FastAPI-приложение веб-админки (F23, Фаза 5.1).

Встраивается в общий asyncio-процесс через `main.py` (uvicorn как таска в том
же event loop, что и Telethon listener/бот/планировщик) — НЕ отдельный
процесс. См. план Фазы 5 (`C:\\Users\\Admin767\\.claude\\plans\\spicy-noodling-eich.md`).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from tg_repost import crypto
from tg_repost.config import get_settings, invalidate_settings_cache
from tg_repost.logging_conf import get_logger
from tg_repost.webui import dashboard, runtime_state, settings_store
from tg_repost.webui.auth import (
    NotAuthenticatedError,
    create_admin,
    is_bootstrapped,
    log_in,
    log_out,
    require_login,
    verify_login,
)

logger = get_logger(__name__)

_BASE_DIR = Path(__file__).parent
_templates = Jinja2Templates(directory=str(_BASE_DIR / "templates"))


def _ensure_session_secret() -> str:
    """WEBUI_SESSION_SECRET нужен ДО первого запроса (параметр конструктора
    SessionMiddleware) — генерируется сразу при сборке приложения, в отличие
    от WEBUI_MASTER_KEY, который ждёт первого реального секрета (см.
    `settings_store._ensure_master_key`). Потеря сессионного ключа не теряет
    данные (просто разлогинивает), поэтому безопасно генерировать eagerly.
    """
    settings = get_settings()
    if settings.webui_session_secret:
        return settings.webui_session_secret
    new_secret = crypto.generate_key()
    crypto.append_env_var("WEBUI_SESSION_SECRET", new_secret)
    invalidate_settings_cache()
    logger.info("Сгенерирован новый WEBUI_SESSION_SECRET")
    return new_secret


def _coerce_form_value(value_type: str, raw: object) -> object:
    """Привести значение HTML-формы к типу настройки (чистая функция).

    Чекбоксы (bool) при снятой галке вообще не попадают в form-data — `raw`
    будет None, что корректно означает False.
    """
    if value_type == "bool":
        return raw is not None and str(raw).strip().lower() in {"on", "true", "1"}
    text = "" if raw is None else str(raw)
    if value_type == "int":
        return int(text) if text.strip() else 0
    if value_type == "float":
        return float(text) if text.strip() else 0.0
    if value_type == "csv_list":
        return [s.strip() for s in text.split(",") if s.strip()]
    return text


def _public_router() -> APIRouter:
    """Роуты без авторизации: бутстрап-визард и логин."""
    router = APIRouter()

    @router.get("/setup", response_class=HTMLResponse)
    async def setup_form(request: Request) -> Response:
        if is_bootstrapped():
            return RedirectResponse(url="/login", status_code=303)
        return _templates.TemplateResponse(request, "setup.html", {"error": None})

    @router.post("/setup")
    async def setup_submit(
        request: Request,
        password: str = Form(...),
        password_confirm: str = Form(...),
        tg_api_id: str = Form(""),
        tg_api_hash: str = Form(""),
        tg_session_string: str = Form(""),
        tg_bot_token: str = Form(""),
        tg_owner_user_id: str = Form(""),
        openai_api_key: str = Form(""),
    ) -> Response:
        if is_bootstrapped():
            return RedirectResponse(url="/login", status_code=303)
        if password != password_confirm or len(password) < 8:
            return _templates.TemplateResponse(
                request, "setup.html",
                {"error": "Пароли не совпадают или короче 8 символов"},
                status_code=400,
            )

        create_admin(password)

        # Секреты — write-only, тем же путём, что и обычное редактирование.
        for key, value in (
            ("tg_api_hash", tg_api_hash),
            ("tg_session_string", tg_session_string),
            ("tg_bot_token", tg_bot_token),
            ("openai_api_key", openai_api_key),
        ):
            if value.strip():
                settings_store.set_secret(key, value.strip())

        if tg_api_id.strip().isdigit():
            settings_store.save_setting("tg_api_id", int(tg_api_id), "int")
        if tg_owner_user_id.strip().isdigit():
            settings_store.save_setting("tg_owner_user_id", int(tg_owner_user_id), "int")

        log_in(request)
        return RedirectResponse(url="/", status_code=303)

    @router.get("/login", response_class=HTMLResponse)
    async def login_form(request: Request) -> Response:
        if not is_bootstrapped():
            return RedirectResponse(url="/setup", status_code=303)
        return _templates.TemplateResponse(request, "login.html", {"error": None})

    @router.post("/login")
    async def login_submit(request: Request, password: str = Form(...)) -> Response:
        if not verify_login(password):
            return _templates.TemplateResponse(
                request, "login.html", {"error": "Неверный пароль"}, status_code=401,
            )
        log_in(request)
        return RedirectResponse(url="/", status_code=303)

    @router.post("/logout")
    async def logout(request: Request) -> Response:
        log_out(request)
        return RedirectResponse(url="/login", status_code=303)

    return router


def _protected_router() -> APIRouter:
    """Роуты, требующие активной сессии (см. `auth.require_login`)."""
    router = APIRouter(dependencies=[Depends(require_login)])

    @router.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> Response:
        settings = get_settings()
        context = {
            "funnel": dashboard.post_status_funnel(),
            "tokens_today": dashboard.todays_rewrite_tokens(),
            "recent": dashboard.recent_posts(limit=15),
            "error_rate": dashboard.error_rate(),
            "components": runtime_state.get_component_status(),
            "is_minimally_configured": settings.is_minimally_configured,
        }
        return _templates.TemplateResponse(request, "dashboard.html", context)

    @router.get("/settings", response_class=HTMLResponse)
    async def settings_page(request: Request) -> Response:
        groups = [
            {
                "key": group.key,
                "title": group.title,
                "fields": [
                    {
                        "name": f.name,
                        "label": f.label,
                        "value_type": f.value_type,
                        "needs_resync": f.needs_resync,
                        "value": settings_store.effective_value(f),
                    }
                    for f in group.fields
                ],
            }
            for group in settings_store.SETTINGS_GROUPS
        ]
        return _templates.TemplateResponse(request, "settings.html", {"groups": groups})

    @router.post("/settings/{group_key}")
    async def settings_save(request: Request, group_key: str) -> Response:
        group = next((g for g in settings_store.SETTINGS_GROUPS if g.key == group_key), None)
        if group is not None:
            form = await request.form()
            for field in group.fields:
                value = _coerce_form_value(field.value_type, form.get(field.name))
                settings_store.save_setting(field.name, value, field.value_type)
        return RedirectResponse(url="/settings", status_code=303)

    @router.get("/secrets", response_class=HTMLResponse)
    async def secrets_page(request: Request) -> Response:
        return _templates.TemplateResponse(
            request, "secrets.html", {"secrets": settings_store.list_secret_status()},
        )

    @router.post("/secrets/{key}")
    async def secrets_save(request: Request, key: str, value: str = Form("")) -> Response:
        if value.strip():
            try:
                settings_store.set_secret(key, value.strip())
            except ValueError as exc:
                logger.warning("Не удалось сохранить секрет '%s': %s", key, exc)
        return RedirectResponse(url="/secrets", status_code=303)

    return router


def create_app() -> FastAPI:
    """Собрать FastAPI-приложение веб-админки."""
    app = FastAPI(title="tg_repost admin", docs_url=None, redoc_url=None)
    app.add_middleware(
        SessionMiddleware,
        secret_key=_ensure_session_secret(),
        same_site="lax",
        https_only=False,  # localhost/VPN-доступ без TLS, см. план Фазы 5
    )
    app.mount("/static", StaticFiles(directory=str(_BASE_DIR / "static")), name="static")

    async def _not_authenticated_handler(request: Request, exc: Exception) -> RedirectResponse:
        # Сигнатура — `Exception`, а не `NotAuthenticatedError`, чтобы совпадать
        # с типом, который ожидает `add_exception_handler` (Starlette диспетчит
        # по зарегистрированному классу — сюда реально попадёт только
        # NotAuthenticatedError, но статическая типизация требует более общий
        # параметр).
        del request, exc
        return RedirectResponse(url="/login", status_code=303)

    app.add_exception_handler(NotAuthenticatedError, _not_authenticated_handler)

    app.include_router(_public_router())
    app.include_router(_protected_router())
    return app
