"""Тесты CRUD/выбора вариантов рерайта и обложки поста (F06/F18-доп.)."""

from tg_repost import post_variants_repo
from tg_repost.db.models import Post, PostCoverVariant, PostKind, PostRewriteVariant, PostStatus
from tg_repost.db.session import session_scope


def _make_post(**kwargs) -> int:
    with session_scope() as session:
        post = Post(
            kind=PostKind.SOURCE, original_text="orig", status=PostStatus.NEW, **kwargs,
        )
        session.add(post)
        session.flush()
        return post.id


def _clean(post_id: int) -> None:
    with session_scope() as session:
        session.query(PostRewriteVariant).filter(PostRewriteVariant.post_id == post_id).delete()
        session.query(PostCoverVariant).filter(PostCoverVariant.post_id == post_id).delete()
        session.query(Post).filter(Post.id == post_id).delete()


def test_list_rewrite_variants_ordered_by_index():
    post_id = _make_post()
    with session_scope() as session:
        session.add(PostRewriteVariant(post_id=post_id, variant_index=1, text="b", tokens=5))
        session.add(PostRewriteVariant(post_id=post_id, variant_index=0, text="a", tokens=3))
    variants = post_variants_repo.list_rewrite_variants(post_id)
    assert [v.text for v in variants] == ["a", "b"]
    _clean(post_id)


def test_list_cover_variants_ordered_by_index():
    post_id = _make_post()
    with session_scope() as session:
        session.add(PostCoverVariant(post_id=post_id, variant_index=1, media_path="b.jpg"))
        session.add(PostCoverVariant(post_id=post_id, variant_index=0, media_path="a.jpg"))
    variants = post_variants_repo.list_cover_variants(post_id)
    assert [v.media_path for v in variants] == ["a.jpg", "b.jpg"]
    _clean(post_id)


def test_select_rewrite_variant_updates_post():
    post_id = _make_post(rewritten_text="old", active_rewrite_variant_index=0)
    with session_scope() as session:
        session.add(PostRewriteVariant(post_id=post_id, variant_index=0, text="v0", tokens=1))
        session.add(PostRewriteVariant(post_id=post_id, variant_index=1, text="v1", tokens=1))

    assert post_variants_repo.select_rewrite_variant(post_id, 1) is True

    with session_scope() as session:
        post = session.get(Post, post_id)
        assert post.rewritten_text == "v1"
        assert post.active_rewrite_variant_index == 1
    _clean(post_id)


def test_select_rewrite_variant_missing_post_returns_false():
    assert post_variants_repo.select_rewrite_variant(999999, 0) is False


def test_select_rewrite_variant_missing_index_returns_false():
    post_id = _make_post()
    with session_scope() as session:
        session.add(PostRewriteVariant(post_id=post_id, variant_index=0, text="v0", tokens=1))
    assert post_variants_repo.select_rewrite_variant(post_id, 5) is False
    _clean(post_id)


def test_select_cover_variant_updates_post():
    post_id = _make_post(media_path="old.jpg", active_cover_variant_index=0)
    with session_scope() as session:
        session.add(PostCoverVariant(post_id=post_id, variant_index=0, media_path="v0.jpg"))
        session.add(PostCoverVariant(post_id=post_id, variant_index=1, media_path="v1.jpg"))

    assert post_variants_repo.select_cover_variant(post_id, 1) is True

    with session_scope() as session:
        post = session.get(Post, post_id)
        assert post.media_path == "v1.jpg"
        assert post.active_cover_variant_index == 1
    _clean(post_id)


def test_select_cover_variant_missing_post_returns_false():
    assert post_variants_repo.select_cover_variant(999999, 0) is False


def test_select_cover_variant_missing_index_returns_false():
    post_id = _make_post()
    with session_scope() as session:
        session.add(PostCoverVariant(post_id=post_id, variant_index=0, media_path="v0.jpg"))
    assert post_variants_repo.select_cover_variant(post_id, 3) is False
    _clean(post_id)
