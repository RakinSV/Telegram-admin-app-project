"""Бот ручной модерации (F07) на python-telegram-bot.

Шлёт владельцу (`TG_OWNER_USER_ID`) рерайченные посты с inline-кнопками
✅ Одобрить / ❌ Отклонить / ✏️ Редактировать. Обрабатывает нажатия, меняет
статус поста в БД. При одобрении пост сразу публикуется (F08).
"""

from __future__ import annotations

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from tg_repost import discovered_chats_repo
from tg_repost.config import get_settings
from tg_repost.db.models import InvalidStatusTransition, Post, PostKind, PostStatus
from tg_repost.db.session import session_scope
from tg_repost.logging_conf import get_logger, sanitize_proxy_error
from tg_repost.moderation import approve_post, edit_post_text, reject_post

logger = get_logger(__name__)

# Ключ в user_data: id поста, для которого ждём новый текст (режим редактирования).
_EDIT_KEY = "editing_post_id"
_PREVIEW_LEN = 3500

# Статусы ChatMember, при которых бот реально состоит в чате (F08-доп.) —
# остальные ("left", "kicked", "restricted" без прав) значат, что бота
# из чата убрали/он вышел.
_ACTIVE_MEMBER_STATUSES = {"member", "administrator", "creator"}


def _keyboard(post_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Одобрить", callback_data=f"approve:{post_id}"),
                InlineKeyboardButton("❌ Отклонить", callback_data=f"reject:{post_id}"),
            ],
            [InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit:{post_id}")],
        ]
    )


_KIND_LABELS = {
    PostKind.AD: "🎯 РЕКЛАМА",
    PostKind.DIGEST: "📰 ДАЙДЖЕСТ",
}


def _format_preview(post: Post) -> str:
    text = post.rewritten_text or post.original_text or "(пусто)"
    src = f"\n\n🔗 Источник: {post.source_link}" if post.source_link else ""
    media = "\n🖼 Есть медиа" if post.media_path else ""
    kind_label = _KIND_LABELS.get(post.kind)
    kind_line = f"\n{kind_label}" if kind_label else ""
    body = text[:_PREVIEW_LEN]
    if len(text) > _PREVIEW_LEN:
        body += "…"
    return f"📝 Пост #{post.id} на модерацию:{kind_line}\n\n{body}{media}{src}"


async def send_pending_for_approval(application: Application) -> None:
    """Отправить владельцу все посты со статусом `rewritten` (F07).

    Вызывается периодически из планировщика. После отправки статус →
    `pending_approval`, чтобы не слать повторно.
    """
    settings = get_settings()
    bot = application.bot

    with session_scope() as session:
        posts = (
            session.query(Post)
            .filter(Post.status == PostStatus.REWRITTEN)
            .order_by(Post.created_at.asc())
            .limit(10)
            .all()
        )
        pending = [(p.id, _format_preview(p)) for p in posts]

    for post_id, preview in pending:
        try:
            msg = await bot.send_message(
                chat_id=settings.tg_owner_user_id,
                text=preview,
                reply_markup=_keyboard(post_id),
                parse_mode=None,  # превью — plain text, без риска парсинга
            )
        except Exception as exc:  # noqa: BLE001
            # sanitize_proxy_error — на случай сбоя подключения через
            # BOT_API_PROXY_URL (см. retry.py::retry_async про ту же находку).
            logger.error(
                "Не удалось отправить пост %s на модерацию: %s",
                post_id, sanitize_proxy_error(str(exc)),
            )
            continue

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
        assert context.user_data is not None  # приватный чат с владельцем — всегда есть
        context.user_data[_EDIT_KEY] = post_id
        await query.edit_message_text(
            f"✏️ Пришли новый текст для поста #{post_id} одним сообщением."
        )


async def _approve(query, context: ContextTypes.DEFAULT_TYPE, post_id: int) -> None:
    """Одобрить пост через общую логику `tg_repost.moderation` (Фаза 5.3) —
    та же функция, что использует и веб-админка (`/moderation`)."""
    try:
        outcome = await approve_post(context.application.bot, post_id)
    except InvalidStatusTransition as exc:
        await query.edit_message_text(f"Пост #{post_id}: {exc}")
        return
    await query.edit_message_text(f"✅ Пост #{post_id}: {outcome}.")


async def _reject(query, post_id: int) -> None:
    try:
        found = reject_post(post_id)
    except InvalidStatusTransition as exc:
        await query.edit_message_text(f"Пост #{post_id}: {exc}")
        return
    if not found:
        await query.edit_message_text(f"Пост #{post_id} не найден.")
        return
    await query.edit_message_text(f"❌ Пост #{post_id} отклонён.")


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
    await update.message.reply_text(
        f"✏️ Текст поста #{post_id} обновлён.",
        reply_markup=_keyboard(post_id),
    )


async def _cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text(
            "Бот модерации запущен. Рерайченные посты будут приходить сюда "
            "с кнопками одобрения.\nКоманды: /stats, /best_times, /growth."
        )


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
    if membership.new_chat_member.status in _ACTIVE_MEMBER_STATUSES:
        discovered_chats_repo.record_discovered_chat(chat.id, chat.title, chat.type)
        logger.info(
            "Бот добавлен в чат '%s' (%s, id=%s) — доступен для добавления в /targets",
            chat.title, chat.type, chat.id,
        )
    else:
        discovered_chats_repo.remove_discovered_chat(chat.id)
        logger.info("Бот удалён из чата id=%s (%s)", chat.id, membership.new_chat_member.status)


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
    return application
