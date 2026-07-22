"""Бот ручной модерации (F07) на python-telegram-bot.

Шлёт владельцу (`TG_OWNER_USER_ID`) рерайченные посты с inline-кнопками
✅ Одобрить / ❌ Отклонить / ✏️ Редактировать. Обрабатывает нажатия, меняет
статус поста в БД. При одобрении пост сразу публикуется (F08).
"""

from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Update,
)
from telegram.error import NetworkError, RetryAfter, TimedOut
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatJoinRequestHandler,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from tg_repost import discovered_chats_repo, invites_repo, post_variants_repo, targets_repo
from tg_repost.config import get_settings
from tg_repost.db.models import InvalidStatusTransition, Post, PostKind, PostStatus
from tg_repost.db.session import session_scope
from tg_repost.logging_conf import get_logger, sanitize_proxy_error
from tg_repost.moderation import approve_post, edit_post_text, reject_post
from tg_repost.retry import retry_async
from tg_repost.telegram.invites import approve_join_request, decline_join_request
from tg_repost.telegram.publisher import resolve_target_labels_for_post

logger = get_logger(__name__)

# Ключ в user_data: id поста, для которого ждём новый текст (режим редактирования).
_EDIT_KEY = "editing_post_id"
_PREVIEW_LEN = 3500
# Telegram-лимит подписи к фото — 1024 символа, короче лимита текста
# сообщения (4096) выше. Оставляем запас под многоточие/эмодзи-приписки.
_CAPTION_LEN = 1000
# Сколько текста поста показываем даже когда обвязка (шапка, ссылка на
# источник, список целевых групп) съела почти весь лимит: превью без текста
# бессмысленно, лучше урезать саму обвязку.
_MIN_BODY_LEN = 200
# Сколько раз пробуем отправить пост на модерацию, прежде чем признать
# отправку невозможной (см. send_pending_for_approval). Счётчик живёт в
# памяти процесса: после рестарта попытки начинаются заново — это осознанно,
# рестарт как раз и есть повод перепроверить. Словарь чистится и при успехе,
# и при уходе поста в failed, поэтому расти неограниченно не может.
_MAX_SEND_ATTEMPTS = 3
_send_failures: dict[int, int] = {}

# Сбои, которые НЕ означают «этот пост непригоден»: сеть, таймаут, флуд-лимит.
# Считать их в бюджет попыток нельзя — при обрыве связи не проходит ВООБЩЕ
# ничего, значит очередь никто не загораживает, и списывать посты в failed
# бессмысленно и вредно. Найдено на живом стенде: за время недоступности
# провайдера в failed уехал 71 совершенно здоровый пост с причиной
# «Отправка на модерацию: Timed out».
_TRANSIENT_SEND_ERRORS = (TimedOut, NetworkError, RetryAfter, asyncio.TimeoutError, TimeoutError)


def is_transient_send_error(exc: BaseException) -> bool:
    """Временный ли это сбой отправки (сеть/таймаут), а не отказ по посту."""
    return isinstance(exc, _TRANSIENT_SEND_ERRORS)


def forget_send_failures(post_id: int) -> None:
    """Забыть накопленные неудачные попытки отправки поста.

    Зовётся при ручном ретрае из админки: пост возвращают в очередь именно
    потому, что причина сбоя устранена, и бюджет попыток должен начаться
    заново, а не продолжиться с остатка.
    """
    _send_failures.pop(post_id, None)


def _tg_len(text: str) -> int:
    """Длина строки так, как её считает Telegram, — в UTF-16 code units.

    Эмодзи вне BMP занимают ДВЕ единицы, поэтому подпись из 1000 «питоновских»
    символов с эмодзи спокойно перебирает лимит в 1024 и API отвечает
    `Message caption is too long`. Считать `len()` тут недостаточно.
    """
    return len(text.encode("utf-16-le")) // 2


def _clip(text: str, budget: int) -> str:
    """Обрезать до `budget` единиц в мере Telegram, не разорвав эмодзи."""
    if budget <= 0:
        return ""
    if _tg_len(text) <= budget:
        return text
    raw = text.encode("utf-16-le")[: budget * 2]
    while raw:
        try:
            return raw.decode("utf-16-le")
        except UnicodeDecodeError:
            raw = raw[:-2]  # отрезали половину суррогатной пары — сдаём назад
    return ""

# Статусы ChatMember, при которых бот реально состоит в чате (F08-доп.) —
# остальные ("left", "kicked", "restricted" без прав) значат, что бота
# из чата убрали/он вышел.
_ACTIVE_MEMBER_STATUSES = {"member", "administrator", "creator"}


def _keyboard(
    post_id: int,
    *,
    rewrite_count: int = 1,
    rewrite_index: int = 0,
    cover_count: int = 1,
    cover_index: int = 0,
) -> InlineKeyboardMarkup:
    """Клавиатура модерации. F06/F18-доп.: если у поста больше одного
    варианта текста/обложки — добавляются строки ◀/▶ для переключения
    (`_cycle_rewrite`/`_cycle_cover`); при variant_count=1 (старое
    поведение) строки не показываются вообще."""
    rows = [
        [
            InlineKeyboardButton("✅ Одобрить", callback_data=f"approve:{post_id}"),
            InlineKeyboardButton("❌ Отклонить", callback_data=f"reject:{post_id}"),
        ],
        [InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit:{post_id}")],
    ]
    if rewrite_count > 1:
        rows.append([
            InlineKeyboardButton("◀", callback_data=f"rwprev:{post_id}"),
            InlineKeyboardButton(
                f"📝 Текст {rewrite_index + 1}/{rewrite_count}", callback_data=f"noop:{post_id}",
            ),
            InlineKeyboardButton("▶", callback_data=f"rwnext:{post_id}"),
        ])
    if cover_count > 1:
        rows.append([
            InlineKeyboardButton("◀", callback_data=f"cvprev:{post_id}"),
            InlineKeyboardButton(
                f"🖼 Обложка {cover_index + 1}/{cover_count}", callback_data=f"noop:{post_id}",
            ),
            InlineKeyboardButton("▶", callback_data=f"cvnext:{post_id}"),
        ])
    return InlineKeyboardMarkup(rows)


_KIND_LABELS = {
    PostKind.AD: "🎯 РЕКЛАМА",
    PostKind.DIGEST: "📰 ДАЙДЖЕСТ",
}


def _format_preview(
    post: Post, *, for_caption: bool = False, target_labels: list[str] | None = None,
) -> str:
    """Текст превью. `for_caption=True` — сообщение отправляется как подпись
    к фото обложки (лимит Telegram короче, чем у обычного текста, см.
    `_CAPTION_LEN`); фото уже само по себе показывает, что медиа есть —
    отдельная строка-индикатор не нужна (в отличие от старого текст-only режима).

    `target_labels` — куда пост уйдёт при одобрении (F12-роутинг), см.
    `publisher.resolve_target_labels_for_post`. `None` — не считали (не
    ломает старые вызовы); пустой список — реальное предупреждение
    "публиковать некуда" (найдено на аудите ведения групп: раньше это было
    не видно нигде до самой публикации)."""
    text = post.rewritten_text or post.original_text or "(пусто)"
    limit = _CAPTION_LEN if for_caption else _PREVIEW_LEN
    src = f"\n\n🔗 Источник: {post.source_link}" if post.source_link else ""
    kind_label = _KIND_LABELS.get(post.kind)
    kind_line = f"\n{kind_label}" if kind_label else ""
    if target_labels:
        targets_line = f"\n📤 Опубликуется в: {', '.join(target_labels)}"
    elif target_labels is not None:
        targets_line = "\n⚠️ Публиковать некуда — нет активных целевых групп"
    else:
        targets_line = ""

    # Лимит Telegram считается по ВСЕМУ сообщению, а не по одному телу поста.
    # Раньше тело резалось по `limit`, а шапка, ссылка-источник и список
    # целевых групп добавлялись сверху — и подпись стабильно вылезала за 1024
    # («Message caption is too long», пост навсегда застревал в `rewritten`).
    header = f"📝 Пост #{post.id} на модерацию:{kind_line}\n\n"
    tail = f"{src}{targets_line}"
    # Обвязка сама может съесть весь лимит (целевых групп бывает много) —
    # тогда режем её, а не превью поста.
    tail = _clip(tail, limit - _tg_len(header) - _MIN_BODY_LEN)
    budget = limit - _tg_len(header) - _tg_len(tail)
    body = _clip(text, budget)
    if body != text:
        body = _clip(body, budget - 1) + "…"
    return f"{header}{body}{tail}"


async def send_pending_for_approval(application: Application) -> None:
    """Отправить владельцу все посты со статусом `rewritten` (F07).

    Вызывается периодически из планировщика. После отправки статус →
    `pending_approval`, чтобы не слать повторно. F18-доп.: если у поста есть
    обложка — шлём её как фото с подписью (не текстом с пометкой "есть
    медиа", как раньше), иначе кнопки ◀▶ переключения вариантов обложки
    (F06/F18-доп.) нечего было бы показывать во время модерации.

    Пачка ограничена и берётся от старых к новым, поэтому пост, который
    Telegram отвергает СТАБИЛЬНО (битый файл обложки, неподъёмный текст),
    занимал бы место в пачке вечно и загораживал всю очередь за собой —
    найдено вживую: десяток таких постов, и на модерацию не приходило вообще
    ничего. После `_MAX_SEND_ATTEMPTS` неудач пост уходит в `failed` с
    причиной: очередь едет дальше, а поломка видна в админке, а не только
    в логах.
    """
    settings = get_settings()
    bot = application.bot

    with session_scope() as session:
        post_ids = [
            row[0]
            for row in session.query(Post.id)
            .filter(Post.status == PostStatus.REWRITTEN)
            .order_by(Post.created_at.asc())
            .limit(10)
            .all()
        ]

    for post_id in post_ids:
        # ВНЕ session_scope ниже: сама функция открывает свою сессию, а
        # вложенный session_scope внутри уже открытого — риск лишний раз не
        # проверенного поведения SQLite-блокировок (см. аудит ведения групп).
        target_labels = resolve_target_labels_for_post(post_id)
        with session_scope() as session:
            post = session.get(Post, post_id)
            if post is None:
                continue
            rewrite_count = len(post_variants_repo.list_rewrite_variants(post_id)) or 1
            cover_count = len(post_variants_repo.list_cover_variants(post_id)) or 1
            media_path = post.media_path
            keyboard = _keyboard(
                post_id,
                rewrite_count=rewrite_count, rewrite_index=post.active_rewrite_variant_index or 0,
                cover_count=cover_count, cover_index=post.active_cover_variant_index or 0,
            )

            # Файл читаем ЗДЕСЬ (пока сессия открыта, `post` не detach-нут) —
            # при неудаче (файл пропал) откатываемся на текстовый режим, а
            # не молчим весь пост: тогда его пометка "уже отправлен" не
            # выставится, и он навсегда застрял бы в `rewritten`.
            photo_bytes: bytes | None = None
            if media_path:
                try:
                    photo_bytes = await asyncio.to_thread(Path(media_path).read_bytes)
                except OSError as exc:
                    logger.warning(
                        "Не удалось прочитать файл обложки поста %s (%s): %s",
                        post_id, media_path, exc,
                    )
            preview = _format_preview(post, for_caption=bool(photo_bytes), target_labels=target_labels)

        try:
            if photo_bytes:
                msg = await bot.send_photo(
                    chat_id=settings.tg_owner_user_id,
                    photo=BytesIO(photo_bytes),
                    caption=preview,
                    reply_markup=keyboard,
                )
            else:
                msg = await bot.send_message(
                    chat_id=settings.tg_owner_user_id,
                    text=preview,
                    reply_markup=keyboard,
                    parse_mode=None,  # превью — plain text, без риска парсинга
                )
        except Exception as exc:  # noqa: BLE001
            # sanitize_proxy_error — на случай сбоя подключения через
            # BOT_API_PROXY_URL (см. retry.py::retry_async про ту же находку).
            reason = sanitize_proxy_error(str(exc))
            logger.error("Не удалось отправить пост %s на модерацию: %s", post_id, reason)
            if is_transient_send_error(exc):
                # Сеть/таймаут — пробуем снова на следующем тике, бюджет
                # попыток не тратим: пост тут ни при чём.
                continue
            attempts = _send_failures.get(post_id, 0) + 1
            if attempts < _MAX_SEND_ATTEMPTS:
                _send_failures[post_id] = attempts
                continue
            _send_failures.pop(post_id, None)
            with session_scope() as session:
                post = session.get(Post, post_id)
                if post and post.status == PostStatus.REWRITTEN:
                    post.set_status(
                        PostStatus.FAILED, reason=f"Отправка на модерацию: {reason}",
                    )
            logger.error(
                "Пост %s помечен failed после %s неудачных отправок — очередь не блокируется",
                post_id, attempts,
            )
            continue

        _send_failures.pop(post_id, None)
        with session_scope() as session:
            post = session.get(Post, post_id)
            if post and post.status == PostStatus.REWRITTEN:
                post.moderation_message_id = msg.message_id
                post.set_status(PostStatus.PENDING_APPROVAL)
        logger.info("Пост %s отправлен на модерацию", post_id)


async def _on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик нажатий inline-кнопок."""
    query = update.callback_query
    if query is None or query.data is None:
        return

    # Defense-in-depth: callback-кнопки шлются только в личку владельцу, но на
    # всякий случай отвергаем нажатия от любого другого пользователя.
    settings = get_settings()
    if update.effective_user is None or update.effective_user.id != settings.tg_owner_user_id:
        await query.answer("Доступ запрещён", show_alert=True)
        return

    await query.answer()

    action, _, raw_id = query.data.partition(":")
    try:
        post_id = int(raw_id)
    except ValueError:
        return

    if action == "approve":
        await _approve(query, context, post_id)
    elif action == "reject":
        await _reject(query, post_id)
    elif action == "edit":
        await _start_edit(query, context, post_id)
    elif action == "noop":
        return
    elif action == "rwprev":
        await _cycle_rewrite(query, post_id, -1)
    elif action == "rwnext":
        await _cycle_rewrite(query, post_id, 1)
    elif action == "cvprev":
        await _cycle_cover(query, post_id, -1)
    elif action == "cvnext":
        await _cycle_cover(query, post_id, 1)
    elif action == "jrq_ok":
        await _decide_join_request(query, context, post_id, approved=True)
    elif action == "jrq_no":
        await _decide_join_request(query, context, post_id, approved=False)


async def _edit_result_message(query, text: str) -> None:
    """Показать финальный текст в сообщении модерации — как подпись, если
    это сообщение с фото обложки (F18-доп.), иначе как обычный текст.
    `query.message.photo` — это ФАКТ о текущем сообщении (не о БД), поэтому
    надёжнее, чем сверяться с `Post.media_path`, который мог с тех пор
    измениться (например, циклированием обложки)."""
    if query.message is not None and query.message.photo:
        await query.edit_message_caption(caption=text)
    else:
        await query.edit_message_text(text)


async def _approve(query, context: ContextTypes.DEFAULT_TYPE, post_id: int) -> None:
    """Одобрить пост через общую логику `tg_repost.moderation` (Фаза 5.3) —
    та же функция, что использует и веб-админка (`/moderation`)."""
    try:
        outcome = await approve_post(context.application.bot, post_id)
    except InvalidStatusTransition as exc:
        await _edit_result_message(query, f"Пост #{post_id}: {exc}")
        return
    await _edit_result_message(query, f"✅ Пост #{post_id}: {outcome}.")


async def _reject(query, post_id: int) -> None:
    try:
        found = reject_post(post_id)
    except InvalidStatusTransition as exc:
        await _edit_result_message(query, f"Пост #{post_id}: {exc}")
        return
    if not found:
        await _edit_result_message(query, f"Пост #{post_id} не найден.")
        return
    await _edit_result_message(query, f"❌ Пост #{post_id} отклонён.")


async def _decide_join_request(
    query, context: ContextTypes.DEFAULT_TYPE, request_id: int, *, approved: bool
) -> None:
    """F32: одобрить/отклонить заявку на вступление по кнопке из уведомления."""
    fn = approve_join_request if approved else decline_join_request
    ok = await fn(context.application.bot, request_id)
    if not ok:
        await _edit_result_message(query, "Заявка уже решена или не найдена.")
        return
    verdict = "✅ Одобрена" if approved else "❌ Отклонена"
    await _edit_result_message(query, f"Заявка #{request_id}: {verdict}.")


async def _start_edit(query, context: ContextTypes.DEFAULT_TYPE, post_id: int) -> None:
    """Войти в режим редактирования (F07) — показывает ТЕКУЩИЙ текст поста,
    чтобы было что скопировать и подправить, а не редактировать вслепую
    (раньше кнопка просто стирала превью словами "пришли новый текст",
    реальный текст поста нигде не оставался виден — жалоба пользователя)."""
    assert context.user_data is not None  # приватный чат с владельцем — всегда есть
    context.user_data[_EDIT_KEY] = post_id

    with session_scope() as session:
        post = session.get(Post, post_id)
        current_text = (post.rewritten_text if post else None) or ""

    limit = _CAPTION_LEN if (query.message is not None and query.message.photo) else _PREVIEW_LEN
    body = current_text[:limit]
    if len(current_text) > limit:
        body += "…"
    prompt = f"✏️ Текущий текст поста #{post_id} — пришли новую версию одним сообщением:\n\n{body}"
    await _edit_result_message(query, prompt)


async def _cycle_rewrite(query, post_id: int, direction: int) -> None:
    """Переключить активный вариант текста на предыдущий/следующий (F06-доп.,
    кнопки ◀▶). direction — +1 (▶) или -1 (◀), с зацикливанием."""
    variants = post_variants_repo.list_rewrite_variants(post_id)
    if len(variants) <= 1:
        return

    with session_scope() as session:
        post = session.get(Post, post_id)
        if post is None:
            return
        current = post.active_rewrite_variant_index or 0
    new_index = (current + direction) % len(variants)
    if not post_variants_repo.select_rewrite_variant(post_id, new_index):
        return

    target_labels = resolve_target_labels_for_post(post_id)
    with session_scope() as session:
        post = session.get(Post, post_id)
        if post is None:
            return
        cover_variants = post_variants_repo.list_cover_variants(post_id)
        keyboard = _keyboard(
            post_id,
            rewrite_count=len(variants), rewrite_index=new_index,
            cover_count=len(cover_variants) or 1, cover_index=post.active_cover_variant_index or 0,
        )
        preview = _format_preview(
            post, for_caption=bool(query.message and query.message.photo),
            target_labels=target_labels,
        )

    if query.message is not None and query.message.photo:
        await query.edit_message_caption(caption=preview, reply_markup=keyboard)
    else:
        await query.edit_message_text(preview, reply_markup=keyboard)


async def _cycle_cover(query, post_id: int, direction: int) -> None:
    """Переключить активный вариант обложки на предыдущий/следующий (F18-доп.,
    кнопки ◀▶) — меняет саму фотографию сообщения (`edit_message_media`),
    не только подпись."""
    cover_variants = post_variants_repo.list_cover_variants(post_id)
    if len(cover_variants) <= 1:
        return

    with session_scope() as session:
        post = session.get(Post, post_id)
        if post is None:
            return
        current = post.active_cover_variant_index or 0
    new_index = (current + direction) % len(cover_variants)

    # Файл читаем ДО записи в БД (не после) — иначе при битом/пропавшем
    # файле select_cover_variant() уже закоммитил бы Post.media_path на
    # несуществующий путь: publish_post/publisher.py делает
    # Path(media_path).read_bytes() без запасного варианта на текст, так что
    # такой "битый" пост при одобрении падал бы целиком, а не только без
    # обложки (найдено на code-ревью).
    new_path = cover_variants[new_index].media_path
    try:
        photo_bytes = await asyncio.to_thread(Path(new_path).read_bytes)
    except OSError as exc:
        logger.warning("Не удалось прочитать файл варианта обложки %s: %s", new_path, exc)
        return

    if not post_variants_repo.select_cover_variant(post_id, new_index):
        return

    target_labels = resolve_target_labels_for_post(post_id)
    with session_scope() as session:
        post = session.get(Post, post_id)
        if post is None:
            return
        rewrite_variants = post_variants_repo.list_rewrite_variants(post_id)
        keyboard = _keyboard(
            post_id,
            rewrite_count=len(rewrite_variants) or 1,
            rewrite_index=post.active_rewrite_variant_index or 0,
            cover_count=len(cover_variants), cover_index=new_index,
        )
        preview = _format_preview(post, for_caption=True, target_labels=target_labels)

    # edit_message_media перезаливает файл целиком (в отличие от
    # edit_message_text/caption) — заметно чаще ловит TimedOut на медленном
    # соединении/через BOT_API_PROXY_URL (найдено на реальном деплое: выбор
    # варианта в БД уже применился, а сама картинка в сообщении — нет, юзер
    # видел старое фото). retry_async — тот же helper, что и в publisher.py.
    #
    # ВАЖНО: InputMediaPhoto/BytesIO пересобираются НА КАЖДУЮ попытку внутри
    # лямбды, а не один раз снаружи — если первая попытка успела прочитать
    # часть/весь BytesIO до TimedOut, повторное использование ТОГО ЖЕ объекта
    # отправило бы retry с обрезанным или пустым файлом (курсор потока не
    # сбрасывается сам).
    async def _edit_media() -> None:
        media = InputMediaPhoto(media=BytesIO(photo_bytes), caption=preview)
        await query.edit_message_media(media=media, reply_markup=keyboard)

    try:
        await retry_async(_edit_media, attempts=3, description=f"переключение обложки поста {post_id}")
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Не удалось обновить фото обложки в сообщении поста %s: %s",
            post_id, sanitize_proxy_error(str(exc)),
        )


async def _on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Приём нового текста в режиме редактирования (F07)."""
    assert context.user_data is not None  # приватный чат с владельцем — всегда есть
    post_id = context.user_data.get(_EDIT_KEY)
    if post_id is None or update.message is None or not update.message.text:
        return

    if not edit_post_text(post_id, update.message.text):
        await update.message.reply_text(f"Пост #{post_id} не найден.")
        context.user_data.pop(_EDIT_KEY, None)
        return

    context.user_data.pop(_EDIT_KEY, None)

    # Ручная правка не трогает уже сгенерированные варианты (F06/F18-доп.) —
    # кнопки ◀▶ должны остаться доступны, если у поста их было больше одного
    # (например, чтобы вернуться к одному из авто-вариантов после правки).
    with session_scope() as session:
        post = session.get(Post, post_id)
        rewrite_index = post.active_rewrite_variant_index if post else None
        cover_index = post.active_cover_variant_index if post else None
    rewrite_count = len(post_variants_repo.list_rewrite_variants(post_id)) or 1
    cover_count = len(post_variants_repo.list_cover_variants(post_id)) or 1

    await update.message.reply_text(
        f"✏️ Текст поста #{post_id} обновлён.",
        reply_markup=_keyboard(
            post_id,
            rewrite_count=rewrite_count, rewrite_index=rewrite_index or 0,
            cover_count=cover_count, cover_index=cover_index or 0,
        ),
    )


async def _cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text(
            "Бот модерации запущен. Рерайченные посты будут приходить сюда "
            "с кнопками одобрения.\nКоманды: /stats, /best_times, /growth."
        )


def _discovered_can_post(chat_type: str, member) -> bool | None:
    """Может ли бот СЕЙЧАС слать сообщения в чат, судя по его статусу
    из `my_chat_member` (F08-доп., аудит ведения групп).

    Значимо только для каналов: Bot API отдаёт `can_post_messages` именно
    для них — обычный `member` в канале никогда не может постить от своего
    имени, только администратор с этим правом (или создатель). Для
    групп/супергрупп участник обычно и так может писать без специальных
    прав — возвращаем None ("не проверяем"), а не False, чтобы не рисовать
    ложное предупреждение там, где всё в порядке."""
    if chat_type != "channel":
        return None
    if member.status == "creator":
        return True
    if member.status == "administrator":
        return bool(getattr(member, "can_post_messages", False))
    return False


async def _on_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """F08-доп.: авто-обнаружение чатов для целевых групп публикации.

    Telegram шлёт `my_chat_member`-апдейт при ЛЮБОЙ смене статуса САМОГО
    бота в чате (добавили/удалили/повысили до админа) — не привязано к
    owner_filter, это системное событие про бота, не сообщение пользователя.
    Личка (chat.type == "private") пропускается — это не целевая группа,
    там `my_chat_member` тоже стреляет при /start или блокировке бота.
    """
    del context
    membership = update.my_chat_member
    if membership is None or membership.chat.type == "private":
        return
    chat = membership.chat
    member = membership.new_chat_member
    if member.status in _ACTIVE_MEMBER_STATUSES:
        can_post = _discovered_can_post(chat.type, member)
        discovered_chats_repo.record_discovered_chat(chat.id, chat.title, chat.type, can_post)
        logger.info(
            "Бот добавлен в чат '%s' (%s, id=%s, может постить=%s) — "
            "доступен для добавления в /targets",
            chat.title, chat.type, chat.id, can_post,
        )
    else:
        discovered_chats_repo.remove_discovered_chat(chat.id)
        can_post = False  # бот больше не в чате — точно не может постить
        logger.info("Бот удалён из чата id=%s (%s)", chat.id, membership.new_chat_member.status)

    # Если этот chat_id УЖЕ добавлен как цель публикации — актуализируем и
    # там (аудит ведения групп, раунд 3): раньше отзыв прав бота на уже
    # добавленную цель нигде не отражался, только тихий провал публикации
    # позже. Синхронизация вне if/else выше — покрывает оба случая (права
    # поменялись/бота выгнали) одним вызовом.
    targets_repo.sync_can_post(chat.id, can_post)


async def _on_chat_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """F32: заявка на вступление в группу с подтверждением админом —
    приходит ТОЛЬКО если у чата включена настройка "одобрять новых
    участников" (отдельная от обычного вступления, `chat_member`-апдейта
    здесь НЕТ). Записываем и уведомляем владельца кнопками
    Одобрить/Отклонить — то же место (личка боту), что и модерация постов."""
    request = update.chat_join_request
    if request is None:
        return
    invites_repo.record_join_request(
        request.chat.id, request.from_user.id, request.from_user.username, request.bio,
    )
    pending = invites_repo.list_pending_join_requests(request.chat.id)
    record = next((r for r in pending if r.user_id == request.from_user.id), None)
    if record is None:
        return
    settings = get_settings()
    who = f"@{request.from_user.username}" if request.from_user.username else request.from_user.full_name
    text = f"📥 Заявка на вступление в «{request.chat.title}» от {who} (id{request.from_user.id})."
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Одобрить", callback_data=f"jrq_ok:{record.id}"),
        InlineKeyboardButton("❌ Отклонить", callback_data=f"jrq_no:{record.id}"),
    ]])
    try:
        await context.bot.send_message(
            chat_id=settings.tg_owner_user_id, text=text, reply_markup=keyboard,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Не удалось уведомить о заявке на вступление: %s", sanitize_proxy_error(str(exc)))


async def _cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /stats — сводка просмотров за период (F14)."""
    from tg_repost.scheduler.stats import stats_summary

    if update.message is None:
        return
    settings = get_settings()
    summary = stats_summary(settings.stats_window_days)
    await update.message.reply_text(summary)


async def _cmd_best_times(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /best_times — рекомендация часов публикации (F19, каркас)."""
    from tg_repost.scheduler.smart_schedule import best_times_summary

    if update.message is None:
        return
    await update.message.reply_text(best_times_summary())


async def _cmd_growth(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /growth — отчёт о приросте подписчиков (F22, каркас)."""
    from tg_repost.scheduler.growth import growth_summary

    if update.message is None:
        return
    await update.message.reply_text(growth_summary())


def build_application() -> Application:
    """Собрать PTB Application с хендлерами модерации."""
    settings = get_settings()
    owner_filter = filters.User(user_id=settings.tg_owner_user_id)

    builder = Application.builder().token(settings.tg_bot_token)
    if settings.bot_api_proxy_url:
        # Bot API ходит по HTTPS, не по MTProto — тут нужен SOCKS5/HTTP-прокси,
        # не тот же самый, что для Telethon (см. config.py::mtproto_proxy_*).
        # `.get_updates_proxy()` — отдельно для долгоживущего long-polling
        # соединения (иначе оно продолжало бы идти напрямую).
        builder = builder.proxy(settings.bot_api_proxy_url).get_updates_proxy(
            settings.bot_api_proxy_url
        )
    try:
        # URL прокси парсится именно ЗДЕСЬ, в .build() (не лениво при первом
        # запросе, проверено эмпирически) — битый BOT_API_PROXY_URL иначе
        # ронял бы необработанным ValueError весь процесс main.py (веб-панель
        # ДОЛЖНА подниматься всегда, даже без рабочего Telegram-конфига —
        # см. main.py::run) (найдено security-ревью, тот же класс бага, что
        # и в guardian/bot.py::main).
        application = builder.build()
    except ValueError as exc:
        if not settings.bot_api_proxy_url:
            raise  # ValueError не про прокси — не глотать чужую ошибку
        logger.error(
            "BOT_API_PROXY_URL некорректен (%s) — бот модерации запускается "
            "БЕЗ прокси, напрямую. Проверь формат socks5://[user:pass@]host:port "
            "на /secrets.", exc,
        )
        application = Application.builder().token(settings.tg_bot_token).build()
    application.add_handler(CommandHandler("start", _cmd_start, filters=owner_filter))
    application.add_handler(CommandHandler("stats", _cmd_stats, filters=owner_filter))
    application.add_handler(CommandHandler("best_times", _cmd_best_times, filters=owner_filter))
    application.add_handler(CommandHandler("growth", _cmd_growth, filters=owner_filter))
    application.add_handler(CallbackQueryHandler(_on_callback))
    application.add_handler(
        MessageHandler(owner_filter & filters.TEXT & ~filters.COMMAND, _on_text)
    )
    application.add_handler(ChatMemberHandler(_on_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    application.add_handler(ChatJoinRequestHandler(_on_chat_join_request))
    return application
