"""Аутентификация веб-админки (F23, Фаза 5).

Один администратор (см. CLAUDE.md — система для одного владельца), пароль —
Argon2id (`passlib`), сессия — подписанная httponly-cookie через Starlette
`SessionMiddleware` (оборачивает `itsdangerous`). Без CSRF-токенов: cookie
`samesite=lax` + порог доступа localhost/VPN (см. план Фазы 5) — осознанный
трейдофф для угрозной модели без сторонних origin, а не недосмотр.
"""

from __future__ import annotations

from passlib.context import CryptContext
from starlette.requests import Request

from tg_repost.db.models import AdminUser
from tg_repost.db.session import session_scope
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)

_pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

_SESSION_KEY = "logged_in"


class NotAuthenticatedError(Exception):
    """Запрос к защищённому роуту без активной сессии.

    Перехватывается обработчиком в `app.py` и превращается в редирект на
    `/login` — отдельный класс исключения вместо `HTTPException`, чтобы не
    зависеть от того, как FastAPI сериализует тело ответа для статус-кодов
    редиректа (HTTPException по умолчанию отдаёт JSON-тело).
    """


def hash_password(password: str) -> str:
    """Захэшировать пароль (Argon2id)."""
    return _pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Сверить пароль с хэшем."""
    return _pwd_context.verify(password, password_hash)


def is_bootstrapped() -> bool:
    """Создан ли уже администратор (т.е. /setup пройден)."""
    with session_scope() as session:
        return session.query(AdminUser.id).first() is not None


def create_admin(password: str) -> None:
    """Создать единственную учётку администратора.

    Бросает, если администратор уже существует — `/setup` не должен
    переписывать пароль повторно (для смены пароля — отдельный флоу, не
    в скоупе 5.1).
    """
    with session_scope() as session:
        if session.query(AdminUser.id).first() is not None:
            raise RuntimeError("Администратор уже создан")
        session.add(AdminUser(password_hash=hash_password(password)))
    logger.info("Создан администратор веб-админки")


def verify_login(password: str) -> bool:
    """Проверить пароль против сохранённого администратора."""
    with session_scope() as session:
        admin = session.query(AdminUser).first()
        if admin is None:
            return False
        return verify_password(password, admin.password_hash)


def log_in(request: Request) -> None:
    """Отметить сессию запроса как авторизованную."""
    request.session[_SESSION_KEY] = True


def log_out(request: Request) -> None:
    """Очистить сессию запроса."""
    request.session.clear()


def require_login(request: Request) -> None:
    """FastAPI-зависимость: бросает `NotAuthenticatedError`, если нет сессии.

    Применяется на уровне роутера (`APIRouter(dependencies=[Depends(require_login)])`),
    а не на каждый эндпоинт по отдельности — структурно невозможно забыть
    защитить новый роут в уже защищённой группе.
    """
    if not request.session.get(_SESSION_KEY):
        raise NotAuthenticatedError()
