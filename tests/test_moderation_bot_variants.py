"""Тесты бота модерации (F06/F18-доп.): клавиатура/превью с вариантами
текста и обложки + переключение (без реального Telegram — фейковый
`query` через AsyncMock, тот же приём, что в остальных тестах хендлеров)."""

from unittest.mock import AsyncMock

from tests.aiogram_fakes import fake_bot, fake_callback, sent_methods
from tg_repost.db.models import Post, PostCoverVariant, PostKind, PostRewriteVariant, PostStatus
from tg_repost.db.session import session_scope
from tg_repost.telegram.moderation_bot import (
    _CAPTION_LEN,
    _clip,
    _cycle_cover,
    _cycle_rewrite,
    _format_preview,
    _keyboard,
    _tg_len,
)


def _make_post(**kwargs) -> Post:
    with session_scope() as session:
        post = Post(
            kind=PostKind.SOURCE, original_text="orig",
            status=PostStatus.PENDING_APPROVAL, **kwargs,
        )
        session.add(post)
        session.flush()
        pid = post.id
    with session_scope() as session:
        return session.get(Post, pid)


def _clean(post_id: int) -> None:
    with session_scope() as session:
        session.query(PostRewriteVariant).filter(PostRewriteVariant.post_id == post_id).delete()
        session.query(PostCoverVariant).filter(PostCoverVariant.post_id == post_id).delete()
        session.query(Post).filter(Post.id == post_id).delete()


# --- _keyboard ---

def test_keyboard_no_cycle_rows_when_single_variant():
    markup = _keyboard(1)
    assert len(markup.inline_keyboard) == 2  # approve/reject + edit


def test_keyboard_adds_rewrite_cycle_row():
    markup = _keyboard(1, rewrite_count=2, rewrite_index=0)
    assert len(markup.inline_keyboard) == 3
    row = markup.inline_keyboard[2]
    assert row[0].callback_data == "rwprev:1"
    assert row[2].callback_data == "rwnext:1"
    assert "1/2" in row[1].text


def test_keyboard_adds_cover_cycle_row():
    markup = _keyboard(1, cover_count=3, cover_index=1)
    assert len(markup.inline_keyboard) == 3
    row = markup.inline_keyboard[2]
    assert row[0].callback_data == "cvprev:1"
    assert row[2].callback_data == "cvnext:1"
    assert "2/3" in row[1].text


def test_keyboard_adds_both_cycle_rows():
    markup = _keyboard(1, rewrite_count=2, cover_count=2)
    assert len(markup.inline_keyboard) == 4


# --- _format_preview ---

def test_format_preview_caption_mode_is_shorter():
    post = _make_post(rewritten_text="x" * 5000)
    text_mode = _format_preview(post, for_caption=False)
    caption_mode = _format_preview(post, for_caption=True)
    assert len(caption_mode) < len(text_mode)
    assert _tg_len(caption_mode) <= _CAPTION_LEN
    _clean(post.id)


def test_format_preview_counts_header_and_tail_against_the_limit():
    """Найдено вживую: тело резалось по лимиту, а шапка/источник/список целей
    добавлялись СВЕРХУ — подпись стабильно вылезала за 1024, Telegram отвечал
    «Message caption is too long», и пост навсегда застревал в `rewritten`."""
    post = _make_post(
        rewritten_text="я" * 5000,
        source_link="https://example.com/" + "s" * 200,
    )
    caption = _format_preview(
        post, for_caption=True, target_labels=[f"Группа номер {i}" for i in range(40)],
    )
    assert _tg_len(caption) <= _CAPTION_LEN
    assert "Пост #" in caption          # шапка на месте
    assert "я" in caption               # и текст поста тоже, а не одна обвязка
    _clean(post.id)


def test_format_preview_measures_emoji_the_way_telegram_does():
    """Telegram считает лимит в UTF-16, а эмодзи вне BMP — это ДВЕ единицы:
    подпись из 1000 «питоновских» символов эмодзи весит 2000 и не проходит."""
    post = _make_post(rewritten_text="🔥" * 2000)
    caption = _format_preview(post, for_caption=True)
    assert _tg_len(caption) <= _CAPTION_LEN
    assert len(caption) < _CAPTION_LEN  # питоновских символов заметно меньше
    _clean(post.id)


def test_clip_never_splits_a_surrogate_pair():
    """Обрыв ровно посередине эмодзи дал бы битую строку (UnicodeDecodeError
    или «мусорный» символ в подписи)."""
    clipped = _clip("🔥🔥🔥", 3)  # 3 единицы = полтора эмодзи
    assert clipped == "🔥"
    assert _tg_len(clipped) <= 3



def _method_names(bot) -> list[str]:
    """Какие методы Telegram бот вызвал: у aiogram правка сообщения — это
    вызов бота объектом `EditMessageText`/`EditMessageCaption`/
    `EditMessageMedia`, а не одноимённый метод."""
    return [type(method).__name__ for method in sent_methods(bot)]


# --- _cycle_rewrite ---

async def test_cycle_rewrite_updates_db_and_edits_text_message():
    post = _make_post(rewritten_text="v0", active_rewrite_variant_index=0)
    with session_scope() as session:
        session.add(PostRewriteVariant(post_id=post.id, variant_index=0, text="v0", tokens=1))
        session.add(PostRewriteVariant(post_id=post.id, variant_index=1, text="v1", tokens=1))

    bot = fake_bot()
    query = fake_callback(bot, "rwnext:1")

    await _cycle_rewrite(query, post.id, 1)

    with session_scope() as session:
        updated = session.get(Post, post.id)
        assert updated.rewritten_text == "v1"
        assert updated.active_rewrite_variant_index == 1
    assert _method_names(bot).count("EditMessageText") == 1
    assert "EditMessageCaption" not in _method_names(bot)
    _clean(post.id)


async def test_cycle_rewrite_uses_caption_when_message_has_photo():
    post = _make_post(rewritten_text="v0", active_rewrite_variant_index=0, media_path="x.jpg")
    with session_scope() as session:
        session.add(PostRewriteVariant(post_id=post.id, variant_index=0, text="v0", tokens=1))
        session.add(PostRewriteVariant(post_id=post.id, variant_index=1, text="v1", tokens=1))

    bot = fake_bot()
    query = fake_callback(bot, "rwnext:1", with_photo=True)

    await _cycle_rewrite(query, post.id, 1)

    assert _method_names(bot).count("EditMessageCaption") == 1
    assert "EditMessageText" not in _method_names(bot)
    _clean(post.id)


async def test_cycle_rewrite_noop_with_single_variant():
    post = _make_post(rewritten_text="v0")
    with session_scope() as session:
        session.add(PostRewriteVariant(post_id=post.id, variant_index=0, text="v0", tokens=1))

    bot = fake_bot()
    query = fake_callback(bot, "rwnext:1")

    await _cycle_rewrite(query, post.id, 1)

    assert "EditMessageText" not in _method_names(bot)
    _clean(post.id)


async def test_cycle_rewrite_wraps_around():
    post = _make_post(rewritten_text="v1", active_rewrite_variant_index=1)
    with session_scope() as session:
        session.add(PostRewriteVariant(post_id=post.id, variant_index=0, text="v0", tokens=1))
        session.add(PostRewriteVariant(post_id=post.id, variant_index=1, text="v1", tokens=1))

    bot = fake_bot()
    query = fake_callback(bot, "rwnext:1")

    await _cycle_rewrite(query, post.id, 1)  # (1 + 1) % 2 == 0

    with session_scope() as session:
        updated = session.get(Post, post.id)
        assert updated.active_rewrite_variant_index == 0
        assert updated.rewritten_text == "v0"
    _clean(post.id)


# --- _cycle_cover ---

async def test_cycle_cover_updates_db_and_edits_media(tmp_path):
    img0 = tmp_path / "v0.jpg"
    img1 = tmp_path / "v1.jpg"
    img0.write_bytes(b"a")
    img1.write_bytes(b"b")

    post = _make_post(rewritten_text="text", media_path=str(img0), active_cover_variant_index=0)
    with session_scope() as session:
        session.add(PostCoverVariant(post_id=post.id, variant_index=0, media_path=str(img0)))
        session.add(PostCoverVariant(post_id=post.id, variant_index=1, media_path=str(img1)))

    bot = fake_bot()
    query = fake_callback(bot, "cvnext:1", with_photo=True)

    await _cycle_cover(query, post.id, 1)

    with session_scope() as session:
        updated = session.get(Post, post.id)
        assert updated.media_path == str(img1)
        assert updated.active_cover_variant_index == 1
    assert _method_names(bot).count("EditMessageMedia") == 1
    _clean(post.id)


async def test_cycle_cover_noop_with_single_variant():
    post = _make_post(rewritten_text="text", media_path="x.jpg")
    with session_scope() as session:
        session.add(PostCoverVariant(post_id=post.id, variant_index=0, media_path="x.jpg"))

    bot = fake_bot()
    query = fake_callback(bot, "cvnext:1", with_photo=True)
    await _cycle_cover(query, post.id, 1)
    assert "EditMessageMedia" not in _method_names(bot)
    _clean(post.id)


async def test_cycle_cover_missing_file_logs_and_does_not_edit(tmp_path):
    # Файл варианта пропал с диска — не должно падать, просто не редактируем.
    missing = tmp_path / "gone.jpg"
    post = _make_post(rewritten_text="text", media_path="v0.jpg", active_cover_variant_index=0)
    with session_scope() as session:
        session.add(PostCoverVariant(post_id=post.id, variant_index=0, media_path="v0.jpg"))
        session.add(PostCoverVariant(post_id=post.id, variant_index=1, media_path=str(missing)))

    bot = fake_bot()
    query = fake_callback(bot, "cvnext:1", with_photo=True)
    await _cycle_cover(query, post.id, 1)

    assert "EditMessageMedia" not in _method_names(bot)
    _clean(post.id)


# --- устойчивость обработчика нажатий ---


async def test_stale_query_ack_does_not_cancel_the_action():
    """Найдено в логах стенда: Telegram даёт ~15 секунд на подтверждение
    нажатия, и если бот был занят, `answer()` падал с «Query is too old».
    Исключение выносило ВЕСЬ обработчик — кнопка выглядела нерабочей, хотя
    нажатие дошло. Подтверждение — косметика (гасит «часики»), действие
    обязано выполниться в любом случае."""

    from aiogram.exceptions import TelegramBadRequest

    from tg_repost.telegram import moderation_bot

    post = _make_post(rewritten_text="текст")
    bot = fake_bot()
    query = fake_callback(bot, f"reject:{post.id}")

    def _only_ack_fails(method, *args, **kwargs):
        """Падает ТОЛЬКО подтверждение нажатия.

        У aiogram и подтверждение, и правка сообщения идут через один и тот же
        вызов бота, поэтому глухая заглушка сломала бы заодно и показ
        результата — то есть проверяла бы не то, ради чего тест написан.
        """
        del args, kwargs
        if type(method).__name__ == "AnswerCallbackQuery":
            raise TelegramBadRequest(method=method, message="Query is too old")
        return None

    bot.side_effect = _only_ack_fails

    await moderation_bot._on_callback(query, bot, AsyncMock())

    with session_scope() as session:
        assert session.get(Post, post.id).status == PostStatus.REJECTED, (
            "действие должно выполниться, несмотря на протухшее подтверждение"
        )
    _clean(post.id)


async def test_unparseable_callback_data_is_logged_not_swallowed(caplog):
    """Кнопка с битым callback_data раньше уходила в тишину — жалобу «не
    работает» было нечем проверить."""

    from tg_repost.telegram import moderation_bot

    bot = fake_bot()
    query = fake_callback(bot, "approve:мусор")

    with caplog.at_level("WARNING"):
        await moderation_bot._on_callback(query, bot, AsyncMock())
    assert any("нечитаемым callback_data" in r.message for r in caplog.records)
