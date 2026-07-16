"""Telethon listener (F02) — слушает новые посты в источниках.

Подключается под юзер-сессией, подписывается на `events.NewMessage` для
каналов из таблицы `sources`, применяет фильтр (F03) и хэш-дедупликацию (F04),
сохраняет пост в `posts` с корректным начальным статусом.

F26 — распределение источников между НЕСКОЛЬКИМИ Telethon-аккаунтами (снижает
риск ограничений при большом числе источников на одном аккаунте): основной
клиент (`build_client()`) плюс опциональные дополнительные из
`telethon_sessions_repo`. `_handle_new_message` не меняется вообще — он не
привязан к конкретному клиенту (работает через `event`), поэтому регистрируется
как есть на каждом клиенте с его собственным подмножеством источников
(`start_listeners`). Почасовой лимит «тяжёлых» действий (F17) — ОТДЕЛЬНЫЙ на
каждый клиент (`event.client`), а не общий на всех — иначе объединение
нескольких аккаунтов не увеличивало бы реальную пропускную способность.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from telethon import TelegramClient, events
from telethon.network.connection.tcpmtproxy import (
    ConnectionTcpMTProxyIntermediate,
    ConnectionTcpMTProxyRandomizedIntermediate,
)
from telethon.sessions import StringSession

from tg_repost import telethon_sessions_repo
from tg_repost.antiban import HourlyRateLimiter, jitter_sleep
from tg_repost.config import Settings, get_settings
from tg_repost.db.models import Post, PostStatus, Source
from tg_repost.db.session import session_scope
from tg_repost.dedup.hash_dedup import content_hash
from tg_repost.dedup.semantic import find_similar_post, pack_embedding
from tg_repost.filtering import check_keywords
from tg_repost.logging_conf import get_logger
from tg_repost.rewriter.client import get_rewriter
from tg_repost.text_sanitize import strip_bidi_control_chars

logger = get_logger(__name__)

# F17/F26: почасовой лимит «тяжёлых» действий (скачивание медиа) — ОТДЕЛЬНЫЙ
# на каждый Telethon-клиент (ключ — id(client)), создаётся лениво при первом
# обращении для этого клиента.
_rate_limiters: dict[int, HourlyRateLimiter] = {}

# Допустимое расширение: точка + 1-8 латинских букв/цифр (например ".jpg").
_SAFE_EXT_RE = re.compile(r"^\.[A-Za-z0-9]{1,8}$")


def _safe_media_extension(message: events.NewMessage.Event) -> str:
    """Безопасное расширение медиафайла (защита от path traversal, CWE-22).

    `message.file.ext` Telethon вычисляет через `mimetypes.guess_extension()`
    по MIME-типу вложения, а не из произвольного имени файла, присланного
    автором поста — это уже безопасно, но дополнительно валидируем формат
    как defense-in-depth на случай нестандартного значения.
    """
    try:
        ext = message.file.ext if message.file else None
    except Exception:  # noqa: BLE001
        ext = None
    if ext and _SAFE_EXT_RE.match(ext):
        return ext
    return ".bin"


def _get_rate_limiter(client: TelegramClient) -> HourlyRateLimiter:
    """Лимитер конкретного клиента (F26) — свой почасовой бюджет на аккаунт."""
    key = id(client)
    limiter = _rate_limiters.get(key)
    if limiter is None:
        limiter = HourlyRateLimiter(get_settings().max_reads_per_hour)
        _rate_limiters[key] = limiter
    return limiter


def _mtproxy_kwargs(settings: Settings) -> dict:
    """Аргументы MTProto-прокси для `TelegramClient` — пусто, если не
    настроено (host — обязательный маркер "прокси включён"). Один общий
    прокси на ВСЕ Telethon-клиенты (основной + F26-ротация), см. config.py.

    Класс `connection` зависит от ФОРМАТА секрета (соглашение MTProxy,
    не наша выдумка): секрет с префиксом `dd` ТРЕБУЕТ randomized
    intermediate (Telethon сам бросает ValueError при несовпадении —
    см. `tcpmtproxy.py::MTProxyIO.init_header`); обычный hex-секрет без
    префикса рассчитан на простой intermediate. Раньше здесь был
    захардкожен один RandomizedIntermediate на все секреты — с обычным
    (не `dd`) секретом сервер обрывал соединение сразу после хендшейка
    ("0 bytes read on a total of 4 expected bytes", найдено на реальном
    деплое). `ee`-секреты (fake-TLS) сюда тоже попадают как
    RandomizedIntermediate, но Telethon в принципе не умеет полноценный
    fake-TLS handshake — с таким секретом соединение зависает независимо
    от выбора класса ниже (ограничение библиотеки, не этой функции).
    """
    if not settings.mtproto_proxy_host:
        return {}
    secret = settings.mtproto_proxy_secret
    connection = (
        ConnectionTcpMTProxyRandomizedIntermediate
        if secret[:2].lower() in ("dd", "ee")
        else ConnectionTcpMTProxyIntermediate
    )
    return {
        "connection": connection,
        "proxy": (settings.mtproto_proxy_host, settings.mtproto_proxy_port, secret),
    }


def _socks5_proxy_kwargs(settings: Settings) -> dict:
    """Аргументы SOCKS5-туннеля для `TelegramClient` (TELETHON_PROXY_URL).

    В отличие от MTProto-прокси, это обычный TCP-туннель — Telethon через него
    ходит НАПРЯМУЮ к серверам Telegram, без MTProxy-класса и без ограничения
    fake-TLS. `proxy`-кортеж в формате python_socks/PySocks:
    (тип, host, port, rdns, [user], [pass]); rdns=True — резолвить DNS на
    стороне прокси. Битый URL не роняет процесс (веб-панель должна
    подниматься всегда, см. main.py) — логируем и идём без прокси."""
    url = settings.telethon_proxy_url.strip()
    if not url:
        return {}
    parsed = urlparse(url)
    if parsed.scheme not in ("socks5", "socks5h") or not parsed.hostname or not parsed.port:
        logger.error(
            "TELETHON_PROXY_URL некорректен (ожидался socks5://[user:pass@]host:port) "
            "— Telethon запускается БЕЗ прокси. Проверь формат на /secrets."
        )
        return {}
    proxy: tuple = ("socks5", parsed.hostname, parsed.port, True)
    if parsed.username or parsed.password:
        proxy = proxy + (parsed.username or "", parsed.password or "")
    return {"proxy": proxy}


def _telethon_proxy_kwargs(settings: Settings) -> dict:
    """Единый выбор прокси для ВСЕХ Telethon-клиентов (основной, F26-ротация,
    визард логина в gen_session). SOCKS5-туннель ИМЕЕТ ПРИОРИТЕТ над
    MTProto-прокси: он не упирается в fake-TLS-ограничение Telethon и обычно
    надёжнее (см. config.py::telethon_proxy_url). Оба пусты — прямое
    соединение."""
    socks = _socks5_proxy_kwargs(settings)
    return socks if socks else _mtproxy_kwargs(settings)


def build_client() -> TelegramClient:
    """Создать ОСНОВНОЙ Telethon-клиент из настроек (без подключения)."""
    settings = get_settings()
    return TelegramClient(
        StringSession(settings.tg_session_string),
        settings.tg_api_id,
        settings.tg_api_hash,
        **_telethon_proxy_kwargs(settings),
    )


def build_extra_clients() -> list[TelegramClient]:
    """Собрать ДОПОЛНИТЕЛЬНЫЕ Telethon-клиенты (F26) — по одному на каждую
    активную и успешно расшифрованную запись `telethon_sessions_repo`.
    Основной клиент (`build_client()`) сюда не входит."""
    settings = get_settings()
    active_count = sum(1 for s in telethon_sessions_repo.list_sessions() if s.is_active)
    decrypted = telethon_sessions_repo.list_active_decrypted_sessions()
    if len(decrypted) < active_count:
        # Найдено при security-аудите Фазы 5+: одна повреждённая/нерасшифро-
        # ванная сессия и так не блокирует остальные (список просто короче),
        # но иначе это осталось бы заметно только по строке warning на
        # КАЖДУЮ пропущенную запись в общем логе — легко пропустить.
        logger.warning(
            "F26: %d из %d доп. Telethon-сессий не удалось расшифровать — "
            "проверь WEBUI_MASTER_KEY. Источники этих аккаунтов временно "
            "распределяются только между оставшимися сессиями.",
            active_count - len(decrypted), active_count,
        )
    proxy_kwargs = _telethon_proxy_kwargs(settings)
    clients = []
    for _label, session_string in decrypted:
        clients.append(
            TelegramClient(
                StringSession(session_string), settings.tg_api_id, settings.tg_api_hash, **proxy_kwargs
            )
        )
    return clients


def _load_active_source_entities() -> list[str]:
    """Список username активных источников для подписки на события."""
    with session_scope() as session:
        sources = session.query(Source).filter(Source.is_active.is_(True)).order_by(Source.id).all()
        return [s.channel_username for s in sources]


def partition_sources(usernames: list[str], partition_count: int) -> list[list[str]]:
    """Разбить список источников на `partition_count` групп round-robin по
    порядку (F26) — чистая функция, вынесена для тестируемости отдельно от
    Telethon-подключений."""
    if partition_count < 1:
        raise ValueError("partition_count должен быть >= 1")
    partitions: list[list[str]] = [[] for _ in range(partition_count)]
    for i, username in enumerate(usernames):
        partitions[i % partition_count].append(username)
    return partitions


def _find_source_id(
    channel_id: int, channel_username: str | None, channel_title: str | None = None,
) -> int | None:
    """Найти id источника в БД по channel_id или username; обновить channel_id.

    Заодно заполняет `channel_title` (если ещё пусто) — раньше это поле
    объявлено в модели и показывается в CLI, но никогда не заполнялось нигде
    в коде (найдено на аудите ведения групп): `/sources` показывал только
    голый @username без человекочитаемого названия канала."""
    with session_scope() as session:
        query = session.query(Source).filter(Source.is_active.is_(True))
        source = query.filter(Source.channel_id == channel_id).one_or_none()
        if source is None and channel_username:
            source = query.filter(
                Source.channel_username == channel_username
            ).one_or_none()
            if source is not None and source.channel_id is None:
                source.channel_id = channel_id
        if source is not None and channel_title and not source.channel_title:
            # channel_title — из канала-источника, полностью подконтролен
            # его владельцу; санитизируем от zero-width/bidi-трюков перед
            # сохранением (найдено на security-ревью), как и для DiscoveredChat/
            # TargetGroup.title.
            source.channel_title = strip_bidi_control_chars(channel_title)
        return source.id if source else None


async def _process_message(client: TelegramClient, chat: Any, message: Any) -> None:
    """Общая логика F02→F03→F04→F13 для одного сообщения — извлечена из
    `_handle_new_message`, чтобы её же переиспользовал `backfill_source`
    (F02-доп): live-обработчик получает `chat`/`message` из Telethon-события,
    бэкфилл — из `client.iter_messages()`, дальше путь идентичный (включая
    антибан-джиттер F17 — бэкфилл не должен идти быстрее живого потока)."""
    settings = get_settings()
    text = message.message or ""

    # F17 — джиттер: случайная пауза, чтобы не обрабатывать пачку мгновенно.
    await jitter_sleep(
        settings.listener_min_delay_seconds, settings.listener_max_delay_seconds
    )

    username = getattr(chat, "username", None)
    channel_id = getattr(chat, "id", None)
    channel_title = getattr(chat, "title", None)
    if channel_id is None:
        return

    source_id = _find_source_id(channel_id, username, channel_title)
    if source_id is None:
        # Сообщение из канала, которого нет среди активных источников.
        return

    if not text.strip():
        logger.debug("Пропуск пустого/медиа-без-текста сообщения %s", message.id)
        return

    digest = content_hash(text)
    source_link = f"https://t.me/{username}/{message.id}" if username else None

    # F03 — фильтр ключевых слов (чистая функция, до обращения к БД и эмбеддингам).
    filter_result = check_keywords(
        text, settings.filter_stop_words, settings.filter_required_words
    )

    # F13 — эмбеддинг считаем только если он понадобится (фильтр прошёл и включён
    # семантический дубль-чек), чтобы не тратить токены зря.
    embedding: list[float] | None = None
    if settings.semantic_dedup_enabled and filter_result.passed:
        try:
            embedding = await get_rewriter().embed(text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Не удалось получить эмбеддинг поста %s: %s", message.id, exc)

    with session_scope() as session:
        # Анти-дубль по (source_id, message_id) — уже видели это сообщение.
        exists = (
            session.query(Post.id)
            .filter(Post.source_id == source_id, Post.source_message_id == message.id)
            .first()
        )
        if exists:
            return

        post = Post(
            source_id=source_id,
            source_message_id=message.id,
            source_link=source_link,
            original_text=text,
            content_hash=digest,
            status=PostStatus.NEW,
        )
        if embedding is not None:
            post.embedding = pack_embedding(embedding)

        if not filter_result.passed:
            post.set_status(PostStatus.FILTERED_OUT, reason=filter_result.reason)
            session.add(post)
            logger.info("Пост %s отфильтрован: %s", message.id, filter_result.reason)
            return

        # F04 — хэш-дедупликация (точный дубль из другого источника).
        dup = (
            session.query(Post.id)
            .filter(
                Post.content_hash == digest,
                Post.status != PostStatus.DUPLICATE,
                Post.status != PostStatus.FILTERED_OUT,
            )
            .first()
        )
        if dup:
            post.set_status(PostStatus.DUPLICATE, reason="точный дубль по хэшу")
            session.add(post)
            logger.info("Пост %s — дубль (хэш), пропущен", message.id)
            return

        # F13 — семантический дубль-чек (перефразированный повтор).
        if embedding is not None:
            similar = find_similar_post(
                session,
                embedding,
                threshold=settings.semantic_similarity_threshold,
                window_days=settings.dedup_window_days,
            )
            if similar is not None:
                sim_id, sim_score = similar
                post.set_status(
                    PostStatus.DUPLICATE,
                    reason=f"семантический дубль #{sim_id} (sim={sim_score:.3f})",
                )
                session.add(post)
                logger.info(
                    "Пост %s — семантический дубль #%s (sim=%.3f)",
                    message.id, sim_id, sim_score,
                )
                return

        # Пост-кипер. Сохраняем сразу, БЕЗ медиа: скачивание медиа и ожидание
        # почасового лимита (может спать долго) выносим за пределы транзакции,
        # чтобы не держать соединение с БД открытым во время сетевого I/O.
        session.add(post)
        session.flush()
        post_id = post.id
        logger.info("Новый пост в очереди: source_id=%s msg=%s", source_id, message.id)

    # Скачивание медиа вне сессии (F17: под почасовым лимитом «тяжёлых» действий,
    # свой лимит на каждый клиент — F26).
    if message.media:
        await _get_rate_limiter(client).acquire()
        try:
            # Скачиваем В ПАМЯТЬ (file=bytes), а не доверяем Telethon выбор
            # имени файла из вложения: при file=<директория> Telethon берёт имя
            # из DocumentAttributeFilename, которое полностью контролируется
            # автором исходного поста и может содержать `../../` — это привело
            # бы к перезаписи произвольного файла за пределами media_dir
            # (path traversal, CWE-22). Имя файла формируем сами ниже.
            media_bytes = await message.download_media(file=bytes)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Не удалось скачать медиа поста %s: %s", message.id, exc)
            media_bytes = None

        if media_bytes:
            ext = _safe_media_extension(message)
            media_dir = Path(settings.media_dir)
            dest = media_dir / f"media_{post_id}_{uuid.uuid4().hex}{ext}"

            def _save(data: bytes = media_bytes, target: Path = dest) -> None:
                media_dir.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)

            await asyncio.to_thread(_save)
            with session_scope() as session:
                saved = session.get(Post, post_id)
                if saved is not None:
                    saved.media_path = str(dest)


async def _handle_new_message(event: events.NewMessage.Event) -> None:
    """Обработчик живого потока (F02) — тонкая обёртка над `_process_message`."""
    chat = await event.get_chat()
    await _process_message(event.client, chat, event.message)


async def backfill_source(
    client: TelegramClient, source: Source, limit: int = 50
) -> int:
    """F02-доп: разово собрать последние `limit` сообщений источника через
    ТОТ ЖЕ пайплайн фильтр/дедуп/эмбеддинг/медиа, что и live-слушатель.

    Нужен, т.к. `start_listeners` — чисто live-обработчик: сообщения,
    вышедшие ДО момента, когда Telegram начал присылать апдейты по каналу
    этому аккаунту (обычно — до подписки аккаунта на канал), никогда не
    попадут в очередь сами по себе (жалоба пользователя: "как собрать
    старые посты"). `client.iter_messages()` без `reverse` отдаёт от
    новых к старым — набираем `limit` штук и разворачиваем, чтобы отправить
    в `_process_message` в хронологическом порядке (старые → новые), как
    если бы это был настоящий живой поток; дедуп/джиттер не зависят от
    порядка, но так естественнее читать очередь модерации потом.

    Возвращает число сообщений, дошедших до `_process_message` (не то же
    самое, что число реально поставленных в очередь — часть могла
    отфильтроваться/оказаться дублём, это штатно, см. `_process_message`).
    """
    entity = await client.get_entity(source.channel_username)
    messages = [m async for m in client.iter_messages(entity, limit=limit)]
    for message in reversed(messages):
        await _process_message(client, entity, message)
    return len(messages)


async def start_listeners(clients: list[TelegramClient]) -> None:
    """Подключить N клиентов и распределить активные источники между ними
    round-robin по id (F26). Каждый клиент должен быть уже авторизован
    (валидный session string).

    При ОДНОМ клиенте (обычный случай без дополнительных сессий) поведение
    идентично прежнему: пустой список источников → `chats=None` (слушаем всё,
    фильтр — внутри `_handle_new_message`). При НЕСКОЛЬКИХ клиентах пустая
    партиция НЕ получает `chats=None` — иначе такой клиент слушал бы вообще
    все свои диалоги, и сообщение источника, назначенного ДРУГОМУ клиенту,
    могло бы обработаться дважды (гонка/дублирование).
    """
    if not clients:
        raise ValueError("Нужен хотя бы один Telethon-клиент")

    # `_rate_limiters` ключуется по `id(client)` — без явной очистки при
    # каждом (пере)старте лимитеры отключённых клиентов из предыдущего
    # запуска копились бы бесконечно, а после сборки мусора их `id()` мог бы
    # СОВПАСТЬ с id нового клиента, незаметно унаследовавшего чужой остаток
    # почасового бюджета (найдено при код-ревью Фазы 5+). Свежий старт —
    # свежие лимитеры для всех клиентов.
    _rate_limiters.clear()

    entities = _load_active_source_entities()
    partitions = partition_sources(entities, len(clients))
    assert len(partitions) == len(clients)

    for idx, client in enumerate(clients):
        await client.connect()
        if not await client.is_user_authorized():
            raise RuntimeError(
                f"Telethon-клиент #{idx} не авторизован. Сгенерируй session string: "
                "python -m tg_repost.tools.gen_session"
            )
        me = await client.get_me()
        partition = partitions[idx]

        if len(clients) == 1:
            chats = partition or None
        elif partition:
            chats = partition
        else:
            logger.info(
                "Telethon-клиент #%d (%s): нет назначенных источников — "
                "обработчик не регистрируется", idx, getattr(me, "username", me.id),
            )
            continue

        client.add_event_handler(_handle_new_message, events.NewMessage(chats=chats))
        logger.info(
            "Telethon-клиент #%d авторизован как %s, слушает %s",
            idx, getattr(me, "username", me.id),
            f"{len(partition)} источник(ов)" if chats else "все диалоги (фильтр в БД)",
        )

    logger.info(
        "Listener запущен: %d клиент(ов), %d активных источников",
        len(clients), len(entities),
    )


async def start_listener(client: TelegramClient) -> None:
    """Обратная совместимость (один клиент, все источники) — см. `start_listeners`."""
    await start_listeners([client])
