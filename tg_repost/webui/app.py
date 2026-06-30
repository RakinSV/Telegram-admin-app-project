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
from tg_repost.webui import dashboard, runtime_state, settings_store, telethon_login
from tg_repost.webui.auth import (
    NotAuthenticatedError,
    create_admin,
    is_bootstrapped,
    log_in,
    log_out,
    require_login,
    verify_login,
)
from tg_repost.webui.supervisor import (
    get_components,
    resync_scheduler_jobs,
    restart_moderation_bot,
    restart_telethon_listener,
    start_components,
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


def _telethon_wizard_routes(
    router: APIRouter, base_path: str, success_redirect: str, base_template: str
) -> None:
    """Зарегистрировать 3-шаговый визард Telethon-логина (телефон → код →
    опционально пароль 2FA) на переданном роутере (F23, Фаза 5.2).

    Общая реализация для `/setup/telethon` (до бутстрапа, без авторизации —
    нужен для самого первого подключения) и `/components/telethon` (после
    бутстрапа, с авторизацией — для повторного входа/смены аккаунта). Логика
    шагов — в `webui/telethon_login.py`, эта функция только рендерит формы.
    """

    def _ctx(step: str, *, error: str | None = None) -> dict:
        return {
            "step": step, "base_path": base_path, "success_redirect": success_redirect,
            "base_template": base_template, "error": error,
        }

    @router.get(base_path, response_class=HTMLResponse)
    async def telethon_phone_form(request: Request) -> Response:
        return _templates.TemplateResponse(request, "telethon_login.html", _ctx("phone"))

    @router.post(base_path)
    async def telethon_phone_submit(
        request: Request,
        phone: str = Form(...),
        api_id: str = Form(""),
        api_hash: str = Form(""),
    ) -> Response:
        settings = get_settings()
        final_api_id = int(api_id) if api_id.strip().isdigit() else settings.tg_api_id
        final_api_hash = api_hash.strip() or settings.tg_api_hash
        if not final_api_id or not final_api_hash:
            return _templates.TemplateResponse(
                request, "telethon_login.html",
                _ctx("phone", error="Укажи TG_API_ID и TG_API_HASH."),
                status_code=400,
            )

        # Сохраняем идентичность сразу — нужна не только этому визарду, но и
        # самому Telethon-клиенту в принципе.
        if api_id.strip().isdigit():
            settings_store.save_setting("tg_api_id", final_api_id, "int")
        if api_hash.strip():
            settings_store.set_secret("tg_api_hash", final_api_hash)

        ok, message = await telethon_login.begin(final_api_id, final_api_hash, phone.strip())
        if not ok:
            return _templates.TemplateResponse(
                request, "telethon_login.html", _ctx("phone", error=message), status_code=400,
            )
        return RedirectResponse(url=f"{base_path}/code", status_code=303)

    @router.get(f"{base_path}/code", response_class=HTMLResponse)
    async def telethon_code_form(request: Request) -> Response:
        if not telethon_login.is_in_progress():
            return RedirectResponse(url=base_path, status_code=303)
        return _templates.TemplateResponse(request, "telethon_login.html", _ctx("code"))

    @router.post(f"{base_path}/code")
    async def telethon_code_submit(request: Request, code: str = Form(...)) -> Response:
        status, payload = await telethon_login.submit_code(code.strip())
        if status == "error":
            return _templates.TemplateResponse(
                request, "telethon_login.html", _ctx("code", error=payload), status_code=400,
            )
        if status == "need_password":
            return RedirectResponse(url=f"{base_path}/password", status_code=303)
        # status == "done" — по контракту telethon_login.submit_code это
        # единственный оставшийся случай, и только в нём payload не None.
        assert payload is not None
        settings_store.set_secret("tg_session_string", payload)
        return _templates.TemplateResponse(request, "telethon_login.html", _ctx("done"))

    @router.get(f"{base_path}/password", response_class=HTMLResponse)
    async def telethon_password_form(request: Request) -> Response:
        if not telethon_login.awaiting_password():
            return RedirectResponse(url=base_path, status_code=303)
        return _templates.TemplateResponse(request, "telethon_login.html", _ctx("password"))

    @router.post(f"{base_path}/password")
    async def telethon_password_submit(request: Request, password: str = Form(...)) -> Response:
        status, payload = await telethon_login.submit_password(password)
        if status == "error":
            return _templates.TemplateResponse(
                request, "telethon_login.html", _ctx("password", error=payload), status_code=400,
            )
        # status == "done" — единственный оставшийся случай по контракту
        # telethon_login.submit_password, payload гарантированно не None.
        assert payload is not None
        settings_store.set_secret("tg_session_string", payload)
        return _templates.TemplateResponse(request, "telethon_login.html", _ctx("done"))


def _public_router() -> APIRouter:
    """Роуты без авторизации: бутстрап-визард и логин."""
    router = APIRouter()
    _telethon_wizard_routes(router, "/setup/telethon", "/setup", "auth_base.html")

    @router.get("/setup", response_class=HTMLResponse)
    async def setup_form(request: Request) -> Response:
        if is_bootstrapped():
            return RedirectResponse(url="/login", status_code=303)
        telethon_connected = any(
            s.key == "tg_session_string" and s.is_set
            for s in settings_store.list_secret_status()
        )
        return _templates.TemplateResponse(
            request, "setup.html", {"error": None, "telethon_connected": telethon_connected},
        )

    @router.post("/setup")
    async def setup_submit(
        request: Request,
        password: str = Form(...),
        password_confirm: str = Form(...),
        tg_api_id: str = Form(""),
        tg_api_hash: str = Form(""),
        tg_bot_token: str = Form(""),
        tg_owner_user_id: str = Form(""),
        openai_api_key: str = Form(""),
    ) -> Response:
        if is_bootstrapped():
            return RedirectResponse(url="/login", status_code=303)
        if password != password_confirm or len(password) < 8:
            telethon_connected = any(
                s.key == "tg_session_string" and s.is_set
                for s in settings_store.list_secret_status()
            )
            return _templates.TemplateResponse(
                request, "setup.html",
                {"error": "Пароли не совпадают или короче 8 символов",
                 "telethon_connected": telethon_connected},
                status_code=400,
            )

        create_admin(password)

        # Секреты — write-only, тем же путём, что и обычное редактирование.
        # tg_session_string сюда НЕ входит — он получается только через
        # визард /setup/telethon (Фаза 5.2), не вставляется вручную.
        for key, value in (
            ("tg_api_hash", tg_api_hash),
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

        # Если все обязательные секреты уже на месте (включая сессию,
        # полученную через визард до создания пароля) — поднимаем компоненты
        # сразу, без перезапуска процесса.
        settings = get_settings()
        if settings.is_minimally_configured and not get_components().is_running:
            await start_components(settings)

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
            # F19/Фаза 5.2: поля с needs_resync меняют состав/параметры джобов
            # планировщика — применяем сразу, если компоненты уже запущены.
            if any(f.needs_resync for f in group.fields) and get_components().is_running:
                await resync_scheduler_jobs()
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

    @router.get("/components", response_class=HTMLResponse)
    async def components_page(request: Request) -> Response:
        settings = get_settings()
        return _templates.TemplateResponse(request, "components.html", {
            "status": runtime_state.get_component_status(),
            "is_running": get_components().is_running,
            "is_minimally_configured": settings.is_minimally_configured,
        })

    @router.post("/components/start")
    async def components_start(request: Request) -> Response:
        del request
        settings = get_settings()
        if settings.is_minimally_configured and not get_components().is_running:
            await start_components(settings)
        return RedirectResponse(url="/components", status_code=303)

    @router.post("/components/listener/restart")
    async def components_restart_listener(request: Request) -> Response:
        del request
        await restart_telethon_listener()
        return RedirectResponse(url="/components", status_code=303)

    @router.post("/components/bot/restart")
    async def components_restart_bot(request: Request) -> Response:
        del request
        await restart_moderation_bot()
        return RedirectResponse(url="/components", status_code=303)

    @router.post("/components/scheduler/resync")
    async def components_resync_scheduler(request: Request) -> Response:
        del request
        await resync_scheduler_jobs()
        return RedirectResponse(url="/components", status_code=303)

    _telethon_wizard_routes(router, "/components/telethon", "/components", "base.html")

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
