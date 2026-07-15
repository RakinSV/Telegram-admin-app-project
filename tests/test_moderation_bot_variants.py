"""Тесты бота модерации (F06/F18-доп.): клавиатура/превью с вариантами
текста и обложки + переключение (без реального Telegram — фейковый
`query` через AsyncMock, тот же приём, что в остальных тестах хендлеров)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from tg_repost.db.models import Post, PostCoverVariant, PostKind, PostRewriteVariant, PostStatus
from tg_repost.db.session import session_scope
from tg_repost.telegram.moderation_bot import (
    _CAPTION_LEN,
    _cycle_cover,
    _cycle_rewrite,
    _format_preview,
    _keyboard,
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
    assert len(caption_mode) <= _CAPTION_LEN + 100  # с запасом на обвязку (заголовок/многоточие)
    _clean(post.id)


# --- _cycle_rewrite ---

async def test_cycle_rewrite_updates_db_and_edits_text_message():
    post = _make_post(rewritten_text="v0", active_rewrite_variant_index=0)
    with session_scope() as session:
        session.add(PostRewriteVariant(post_id=post.id, variant_index=0, text="v0", tokens=1))
        session.add(PostRewriteVariant(post_id=post.id, variant_index=1, text="v1", tokens=1))

    query = AsyncMock()
    query.message = SimpleNamespace(photo=None)

    await _cycle_rewrite(query, post.id, 1)

    with session_scope() as session:
        updated = session.get(Post, post.id)
        assert updated.rewritten_text == "v1"
        assert updated.active_rewrite_variant_index == 1
    query.edit_message_text.assert_called_once()
    query.edit_message_caption.assert_not_called()
    _clean(post.id)


async def test_cycle_rewrite_uses_caption_when_message_has_photo():
    post = _make_post(rewritten_text="v0", active_rewrite_variant_index=0, media_path="x.jpg")
    with session_scope() as session:
        session.add(PostRewriteVariant(post_id=post.id, variant_index=0, text="v0", tokens=1))
        session.add(PostRewriteVariant(post_id=post.id, variant_index=1, text="v1", tokens=1))

    query = AsyncMock()
    query.message = SimpleNamespace(photo=[object()])

    await _cycle_rewrite(query, post.id, 1)

    query.edit_message_caption.assert_called_once()
    query.edit_message_text.assert_not_called()
    _clean(post.id)


async def test_cycle_rewrite_noop_with_single_variant():
    post = _make_post(rewritten_text="v0")
    with session_scope() as session:
        session.add(PostRewriteVariant(post_id=post.id, variant_index=0, text="v0", tokens=1))

    query = AsyncMock()
    query.message = SimpleNamespace(photo=None)

    await _cycle_rewrite(query, post.id, 1)

    query.edit_message_text.assert_not_called()
    _clean(post.id)


async def test_cycle_rewrite_wraps_around():
    post = _make_post(rewritten_text="v1", active_rewrite_variant_index=1)
    with session_scope() as session:
        session.add(PostRewriteVariant(post_id=post.id, variant_index=0, text="v0", tokens=1))
        session.add(PostRewriteVariant(post_id=post.id, variant_index=1, text="v1", tokens=1))

    query = AsyncMock()
    query.message = SimpleNamespace(photo=None)

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

    query = AsyncMock()

    await _cycle_cover(query, post.id, 1)

    with session_scope() as session:
        updated = session.get(Post, post.id)
        assert updated.media_path == str(img1)
        assert updated.active_cover_variant_index == 1
    query.edit_message_media.assert_called_once()
    _clean(post.id)


async def test_cycle_cover_noop_with_single_variant():
    post = _make_post(rewritten_text="text", media_path="x.jpg")
    with session_scope() as session:
        session.add(PostCoverVariant(post_id=post.id, variant_index=0, media_path="x.jpg"))

    query = AsyncMock()
    await _cycle_cover(query, post.id, 1)
    query.edit_message_media.assert_not_called()
    _clean(post.id)


async def test_cycle_cover_missing_file_logs_and_does_not_edit(tmp_path):
    # Файл варианта пропал с диска — не должно падать, просто не редактируем.
    missing = tmp_path / "gone.jpg"
    post = _make_post(rewritten_text="text", media_path="v0.jpg", active_cover_variant_index=0)
    with session_scope() as session:
        session.add(PostCoverVariant(post_id=post.id, variant_index=0, media_path="v0.jpg"))
        session.add(PostCoverVariant(post_id=post.id, variant_index=1, media_path=str(missing)))

    query = AsyncMock()
    await _cycle_cover(query, post.id, 1)

    query.edit_message_media.assert_not_called()
    _clean(post.id)
