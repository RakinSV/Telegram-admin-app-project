"""Управление пользователями админки (F37) — веб-роуты.

Доступно только владельцу: политика в `access.py` относит `/users` к
владельцу, а middleware её применяет.

ПОСЛЕДНЕГО ВЛАДЕЛЬЦА УДАЛИТЬ НЕЛЬЗЯ. Система без владельца — это система,
куда некому войти за настройками и секретами, и выбраться из этого состояния
через интерфейс невозможно: страницу управления пользователями тоже
открывает только владелец. Единственным выходом осталась бы правка базы
руками.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.exc import IntegrityError

from tg_repost.db.models import AdminUser
from tg_repost.db.session import session_scope
from tg_repost.webui import access, audit, i18n
from tg_repost.webui.templating import build_templates
from tg_repost.webui.auth import hash_password, require_login

_BASE_DIR = Path(__file__).parent
_templates = build_templates()

# Тот же порог, что у пароля владельца при установке: у редактора доступ к
# публикации от имени канала, и слабый пароль здесь стоит не меньше.
MIN_PASSWORD_LEN = 12


def build_users_router() -> APIRouter:
    router = APIRouter(dependencies=[Depends(require_login)])

    @router.get("/users", response_class=HTMLResponse)
    async def users_page(request: Request, error: str = "") -> Response:
        return _templates.TemplateResponse(
            request, "users.html", _context(error or None),
        )

    @router.post("/users")
    async def user_create(
        request: Request,
        username: str = Form(""),
        password: str = Form(""),
        role: str = Form(access.ROLE_EDITOR),
    ) -> Response:
        name = username.strip().lower()
        if not name or not password:
            return _error(request, i18n.t("users.error_need_fields"))
        if len(password) < MIN_PASSWORD_LEN:
            return _error(request, i18n.t("users.error_short_password"))
        if role not in access.ALL_ROLES:
            # Роль приходит из формы, но проверяется всё равно: подставить в
            # запрос произвольную строку тривиально, а неизвестная роль в
            # базе означала бы учётку, которую `can()` не пропустит никуда —
            # то есть тихо сломанный доступ вместо явной ошибки.
            return _error(request, i18n.t("users.error_need_fields"))

        with session_scope() as session:
            session.add(
                AdminUser(
                    username=name, role=role, password_hash=hash_password(password),
                )
            )
            try:
                session.flush()
            except IntegrityError:
                session.rollback()
                return _error(request, i18n.t("users.error_exists"))

        audit.record_audit("user_create", target=name, detail=role)
        return RedirectResponse(url="/users", status_code=303)

    @router.post("/users/{user_id}/delete")
    async def user_delete(request: Request, user_id: int) -> Response:
        with session_scope() as session:
            row = session.get(AdminUser, user_id)
            if row is None:
                return RedirectResponse(url="/users", status_code=303)

            if row.role == access.ROLE_OWNER:
                owners = (
                    session.query(AdminUser)
                    .filter(AdminUser.role == access.ROLE_OWNER)
                    .count()
                )
                if owners <= 1:
                    return _error(request, i18n.t("users.error_last_owner"))

            name = row.username or str(row.id)
            session.delete(row)

        audit.record_audit("user_delete", target=name)
        return RedirectResponse(url="/users", status_code=303)

    def _error(request: Request, message: str) -> Response:
        return _templates.TemplateResponse(
            request, "users.html", _context(message), status_code=400,
        )

    return router


def _context(error: str | None) -> dict:
    with session_scope() as session:
        rows = session.query(AdminUser).order_by(AdminUser.id.asc()).all()
        users = [
            {
                "id": row.id,
                "username": row.username or f"#{row.id}",
                "role": row.role,
                "created_at": row.created_at,
            }
            for row in rows
        ]
    return {"users": users, "roles": access.ALL_ROLES, "error": error}
