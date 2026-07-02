"""Аутентификация веб-админки (F23, Фаза 5).

Один администратор (см. CLAUDE.md — система для одного владельца), пароль —
Argon2id (`passlib`), сессия — подписанная httponly-cookie через Starlette
`SessionMiddleware` (оборачивает `itsdangerous`). Без CSRF-токенов: cookie
`samesite=lax` + порог доступа localhost/VPN (см. план Фазы 5) — осознанный
трейдофф для угрозной модели без сторонних origin, а не недосмотр.
"""

from __future__ import annotations

import time

from passlib.context import CryptContext
from sqlalchemy.exc import IntegrityError
from starlette.requests import Request

from tg_repost.db.models import AdminUser
from tg_repost.db.session import session_scope
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)

_pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

_SESSION_KEY = "logged_in"
_LOGIN_AT_KEY = "login_at"
_LAST_SEEN_KEY = "last_seen"

# Сессия истекает по двум порогам (найдено при security-аудите Фазы 5: без
# этого куки `session` были валидны бессрочно). Константы, а не настройка из
# админки — это скорее security-параметр, чем поведенческая ручка.
_IDLE_TIMEOUT_SECONDS = 12 * 3600  # 12 часов бездействия
_ABSOLUTE_TIMEOUT_SECONDS = 7 * 24 * 3600  # 7 дней с момента входа

# Простой rate-limit на /login: счётчик неудачных попыток в памяти процесса
# по IP клиента. Не переживает рестарт процесса — это ок, т.к. защищает от
# онлайн-перебора пароля в течение сессии работы сервера, а не от
# распределённой атаки (см. security-аудит Фазы 5).
_MAX_FAILED_ATTEMPTS = 5
_LOGIN_LOCKOUT_SECONDS = 30
_failed_attempts: dict[str, list[float]] = {}


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

    Бросает `RuntimeError`, если администратор уже существует — либо
    обнаружен предварительной проверкой, либо (при гонке двух одновременных
    запросов до создания первого админа — TOCTOU, найдено при security-
    аудите Фазы 5) отловлен через `IntegrityError` на фиксированном `id=1`:
    вторая одновременная вставка с тем же PK гарантированно упадёт на
    уровне БД, а не просто на прочитанном раньше состоянии в Python.
    """
    with session_scope() as session:
        if session.query(AdminUser.id).first() is not None:
            raise RuntimeError("Администратор уже создан")
        session.add(AdminUser(id=1, password_hash=hash_password(password)))
        try:
            session.flush()
        except IntegrityError as exc:
            raise RuntimeError("Администратор уже создан") from exc
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
    now = time.time()
    request.session[_SESSION_KEY] = True
    request.session[_LOGIN_AT_KEY] = now
    request.session[_LAST_SEEN_KEY] = now


def log_out(request: Request) -> None:
    """Очистить сессию запроса."""
    request.session.clear()


def require_login(request: Request) -> None:
    """FastAPI-зависимость: бросает `NotAuthenticatedError`, если нет сессии
    или она истекла (по бездействию или по абсолютному сроку).

    Применяется на уровне роутера (`APIRouter(dependencies=[Depends(require_login)])`),
    а не на каждый эндпоинт по отдельности — структурно невозможно забыть
    защитить новый роут в уже защищённой группе.

    Раньше сессия была валидна бессрочно (только куки-подпись, без проверки
    времени) — украденная или забытая куки давала вечный доступ (найдено
    при security-аудите Фазы 5). Теперь сессия без временных меток (созданная
    до этого фикса) считается истёкшей — не пытаемся мигрировать старые
    сессии, просто требуем повторный вход один раз.
    """
    if not request.session.get(_SESSION_KEY):
        raise NotAuthenticatedError()

    now = time.time()
    login_at = request.session.get(_LOGIN_AT_KEY)
    last_seen = request.session.get(_LAST_SEEN_KEY)
    if login_at is None or last_seen is None:
        log_out(request)
        raise NotAuthenticatedError()
    if now - login_at > _ABSOLUTE_TIMEOUT_SECONDS or now - last_seen > _IDLE_TIMEOUT_SECONDS:
        log_out(request)
        raise NotAuthenticatedError()
    request.session[_LAST_SEEN_KEY] = now


def is_login_locked(client_key: str) -> bool:
    """Превышен ли лимит неудачных попыток входа для данного клиента
    (обычно IP) за последнее окно `_LOGIN_LOCKOUT_SECONDS`."""
    attempts = _failed_attempts.get(client_key)
    if not attempts:
        return False
    cutoff = time.time() - _LOGIN_LOCKOUT_SECONDS
    attempts[:] = [t for t in attempts if t > cutoff]
    if not attempts:
        # Ключ с одной давно устаревшей попыткой иначе оставался бы в
        # словаре НАВСЕГДА (пустой список — не None, .get() выше не
        # удаляет) — на loopback-only периметре не эксплуатируемо снаружи
        # (найдено security-ревью), но чистить дёшево.
        _failed_attempts.pop(client_key, None)
        return False
    return len(attempts) >= _MAX_FAILED_ATTEMPTS


def register_failed_login(client_key: str) -> None:
    """Учесть неудачную попытку входа для данного клиента."""
    _failed_attempts.setdefault(client_key, []).append(time.time())


def clear_failed_logins(client_key: str) -> None:
    """Сбросить счётчик после успешного входа."""
    _failed_attempts.pop(client_key, None)
