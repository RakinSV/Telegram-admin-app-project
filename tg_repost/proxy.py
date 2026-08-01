"""Единая точка выбора прокси для всех исходящих соединений.

Три ТИПА прокси, каждый включается своей галочкой и имеет свои поля:
  • MTProto — адрес:порт + секрет (только для Telethon-сессии);
  • SOCKS5 — адрес:порт + логин + пароль;
  • HTTP(S) — адрес:порт + логин + пароль.

Три ГАЛОЧКИ применения решают, какой трафик гнать через прокси:
  • Telegram       (Telethon + Bot API);
  • рерайт-нейросеть (OpenAI-совместимый клиент рерайта);
  • картиночная    (генерация обложек).

Адрес/порт/логин — обычные редактируемые настройки; пароль/секрет — секреты
(маскируются, с кнопкой «показать»). Раньше весь proxy-URL прятался целиком
одним секретом и не редактировался — отсюда жалоба «прячет, не даёт править».

Логика чистая (без сети) — тестируется без запросов наружу.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import quote

if TYPE_CHECKING:
    from tg_repost.config import Settings

# Порядок предпочтения прокси-типа под задачу. Для Telegram MTProto/SOCKS5
# роднее; для HTTP-клиентов (Bot API, нейросети) — HTTP/SOCKS5. MTProto для
# httpx неприменим (это Telegram-специфичный протокол), поэтому его нет в
# httpx-порядках.
_HTTPX_ORDER = {
    "telegram": ("socks5", "http"),
    "rewrite": ("http", "socks5"),
    "images": ("http", "socks5"),
}
_USE_FLAG = {
    "telegram": "proxy_use_for_telegram",
    "rewrite": "proxy_use_for_rewrite",
    "images": "proxy_use_for_images",
}


def split_host_port(address: str) -> tuple[str, int] | None:
    """`"host:port"` → `(host, port)`; None, если формат не тот.

    Порт обязателен: прокси без порта бессмыслен, а молча подставлять
    дефолт опаснее, чем честно вернуть None (соединение пойдёт напрямую, и
    это видно в логах, а не «прокси есть, но не туда»).
    """
    address = (address or "").strip()
    if not address or ":" not in address:
        return None
    host, _, port = address.rpartition(":")
    host = host.strip().strip("[]")  # на случай literal IPv6 в скобках
    if not host or not port.strip().isdigit():
        return None
    return host, int(port)


def _proxy_url(scheme: str, address: str, login: str, password: str) -> str | None:
    """Собрать URL прокси для httpx: `scheme://[user:pass@]host:port`.

    Логин/пароль URL-экранируются: спецсимволы в пароле (`@`, `:`, `/`)
    иначе разорвали бы разбор URL.
    """
    hp = split_host_port(address)
    if hp is None:
        return None
    host, port = hp
    auth = ""
    if login:
        auth = quote(login, safe="")
        if password:
            auth += ":" + quote(password, safe="")
        auth += "@"
    return f"{scheme}://{auth}{host}:{port}"


def _http_scheme(settings: "Settings", scheme: str) -> str | None:
    """URL включённого прокси данного типа, либо None."""
    if scheme == "socks5" and settings.proxy_socks5_enabled:
        return _proxy_url(
            "socks5", settings.proxy_socks5_address,
            settings.proxy_socks5_login, settings.proxy_socks5_password,
        )
    if scheme == "http" and settings.proxy_http_enabled:
        # httpx одинаково туннелирует и http-, и https-прокси через схему
        # http:// (это адрес САМОГО прокси, а не целевого сайта).
        return _proxy_url(
            "http", settings.proxy_http_address,
            settings.proxy_http_login, settings.proxy_http_password,
        )
    return None


def httpx_proxy_url(settings: "Settings", purpose: str) -> str | None:
    """Прокси-URL для httpx-клиента задачи (`telegram`/`rewrite`/`images`).

    None — если галочка применения выключена или ни один подходящий прокси
    не настроен: тогда соединение идёт напрямую (прежнее поведение).
    """
    if not getattr(settings, _USE_FLAG[purpose], False):
        return None
    for scheme in _HTTPX_ORDER[purpose]:
        url = _http_scheme(settings, scheme)
        if url:
            return url
    return None


def telethon_proxy_kwargs(settings: "Settings") -> dict:
    """Аргументы прокси для `TelegramClient` (Telethon-сессия).

    Порядок: SOCKS5 → HTTP → MTProto. SOCKS5/HTTP — обычные туннели (python_socks),
    Telethon ходит через них напрямую к серверам Telegram; MTProto — крайний
    вариант (у Telethon нет полноценного fake-TLS, `ee`-секреты зависают —
    ограничение библиотеки). Пусто = прямое соединение.
    """
    if not settings.proxy_use_for_telegram:
        return {}

    for scheme, enabled, address, login, password in (
        ("socks5", settings.proxy_socks5_enabled, settings.proxy_socks5_address,
         settings.proxy_socks5_login, settings.proxy_socks5_password),
        ("http", settings.proxy_http_enabled, settings.proxy_http_address,
         settings.proxy_http_login, settings.proxy_http_password),
    ):
        if not enabled:
            continue
        hp = split_host_port(address)
        if hp is None:
            continue
        host, port = hp
        # Кортеж python_socks/PySocks: (тип, host, port, rdns, [user], [pass]);
        # rdns=True — резолвить DNS на стороне прокси.
        proxy: tuple = (scheme, host, port, True)
        if login or password:
            proxy = proxy + (login or "", password or "")
        return {"proxy": proxy}

    if settings.proxy_mtproto_enabled and settings.proxy_mtproto_secret:
        hp = split_host_port(settings.proxy_mtproto_address)
        if hp is not None:
            # Импорт внутри: telethon тяжёлый, а этот модуль зовётся и из
            # чисто-httpx путей, где telethon не нужен.
            from telethon.network.connection.tcpmtproxy import (
                ConnectionTcpMTProxyIntermediate,
                ConnectionTcpMTProxyRandomizedIntermediate,
            )

            host, port = hp
            secret = settings.proxy_mtproto_secret
            # Класс connection зависит от формата секрета (соглашение MTProxy):
            # dd/ee — randomized intermediate, иначе — простой intermediate.
            connection = (
                ConnectionTcpMTProxyRandomizedIntermediate
                if secret[:2].lower() in ("dd", "ee")
                else ConnectionTcpMTProxyIntermediate
            )
            return {"connection": connection, "proxy": (host, port, secret)}

    return {}
