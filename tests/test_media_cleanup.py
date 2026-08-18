"""Уборка медиа отработанных постов (найдено на стенде 2026-08-18).

ЦИФРЫ, С КОТОРЫХ ЭТО НАЧАЛОСЬ: 1663 файла на 2,8 ГБ при базе в 8 МБ. Из них
2,3 ГБ — обложки ОТКЛОНЁННЫХ постов: владелец сказал «нет», а картинки
остались навсегда. Диск при таком росте кончается тихо, а встаёт после этого
всё сразу.

Проверяется в первую очередь то, что уборка НЕ должна трогать: посты в работе
и обложки упавших постов, которые ещё можно повторить.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tg_repost.db.models import Post, PostCoverVariant, PostKind, PostStatus
from tg_repost.db.session import session_scope
from tg_repost.tools.media_cleanup import cleanup_media

RETENTION = 14


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    """Каждый тест — в своём каталоге: уборка ходит по диску."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "media").mkdir()
    with session_scope() as session:
        session.query(PostCoverVariant).delete()
        session.query(Post).delete()
    yield
    with session_scope() as session:
        session.query(PostCoverVariant).delete()
        session.query(Post).delete()


def _age_file(path, *, days: float = 0, hours: float = 0) -> None:
    """Состарить файл вместе с постом.

    ЭТО НЕ УКРАШЕНИЕ ТЕСТА: пока файлы были свежими, их защищала суточная
    отсрочка для ничьих, а не сверка со списком из базы. Диверсия (убрана
    сверка) не роняла ни одного теста — то есть главную защиту очереди никто
    не проверял.
    """
    import os

    stamp = (
        datetime.now(timezone.utc) - timedelta(days=days, hours=hours)
    ).timestamp()
    os.utime(path, (stamp, stamp))


def _make_post(status: PostStatus, *, age_days: int, with_file: bool = True,
               variants: int = 0) -> tuple[int, list[str]]:
    """Пост нужного возраста с файлом обложки того же возраста на диске."""
    from pathlib import Path

    created = datetime.now(timezone.utc) - timedelta(days=age_days)
    paths: list[str] = []
    with session_scope() as session:
        post = Post(
            kind=PostKind.SOURCE, original_text="текст", status=status,
            created_at=created,
        )
        session.add(post)
        session.flush()
        post_id = post.id

        if with_file:
            main = Path("media") / f"post_{post_id}.jpg"
            main.write_bytes(b"x" * 1024)
            _age_file(main, days=age_days)
            post.media_path = str(main)
            paths.append(str(main))

        for index in range(variants):
            extra = Path("media") / f"post_{post_id}_v{index}.jpg"
            extra.write_bytes(b"y" * 2048)
            _age_file(extra, days=age_days)
            session.add(PostCoverVariant(
                post_id=post_id, variant_index=index, media_path=str(extra),
            ))
            paths.append(str(extra))
    return post_id, paths


def _exists(path: str) -> bool:
    from pathlib import Path

    return Path(path).exists()


# --- что убирается ---


def test_rejected_post_media_is_removed():
    """ГЛАВНЫЙ СЛУЧАЙ: 2,3 ГБ на стенде — это именно отклонённые."""
    _post_id, paths = _make_post(PostStatus.REJECTED, age_days=30, variants=2)

    result = cleanup_media(RETENTION)

    assert all(not _exists(p) for p in paths)
    assert result.files_deleted == 3
    assert result.bytes_freed > 0


def test_posted_media_is_removed_too():
    """Картинка уже в Telegram — локальная копия ничего не даёт."""
    _post_id, paths = _make_post(PostStatus.POSTED, age_days=30)

    cleanup_media(RETENTION)

    assert not _exists(paths[0])


def test_database_reference_is_cleared_with_the_file():
    """Оставить путь на удалённый файл — значит сломать страницу модерации
    битой картинкой и уронить публикацию на чтении несуществующего файла."""
    post_id, _paths = _make_post(PostStatus.REJECTED, age_days=30, variants=1)

    cleanup_media(RETENTION)

    with session_scope() as session:
        post = session.get(Post, post_id)
        assert post.media_path is None
        assert post.active_cover_variant_index is None
        assert session.query(PostCoverVariant).filter(
            PostCoverVariant.post_id == post_id
        ).count() == 0


# --- чего уборка трогать НЕ должна ---


def test_fresh_rejected_post_is_kept():
    """Срок хранения на то и срок: вчерашнее решение могло быть ошибкой."""
    _post_id, paths = _make_post(PostStatus.REJECTED, age_days=1)

    cleanup_media(RETENTION)

    assert _exists(paths[0])


@pytest.mark.parametrize(
    "status",
    [PostStatus.NEW, PostStatus.REWRITTEN, PostStatus.PENDING_APPROVAL,
     PostStatus.APPROVED],
)
def test_posts_still_in_work_are_never_touched(status):
    """Пост в работе не трогаем НИКОГДА, каким бы старым он ни был: это не
    мусор, а очередь, до которой у владельца не дошли руки."""
    _post_id, paths = _make_post(status, age_days=365)

    cleanup_media(RETENTION)

    assert _exists(paths[0])


def test_failed_post_keeps_media_for_a_double_term():
    """У упавшего поста есть кнопка «повторить». Повтор без обложки — это
    молчаливая потеря, а не уборка, поэтому срок вдвое длиннее."""
    _post_id, paths = _make_post(PostStatus.FAILED, age_days=RETENTION + 1)

    cleanup_media(RETENTION)

    assert _exists(paths[0]), "упавший пост ещё можно повторить с картинкой"


def test_very_old_failed_post_is_finally_cleaned():
    """Но не вечно: через двойной срок повтор — уже теория."""
    _post_id, paths = _make_post(PostStatus.FAILED, age_days=RETENTION * 2 + 1)

    cleanup_media(RETENTION)

    assert not _exists(paths[0])


def test_zero_retention_disables_cleanup_entirely():
    """Ноль — это «не убирать», а не «убрать всё сейчас»."""
    _post_id, paths = _make_post(PostStatus.REJECTED, age_days=365)

    result = cleanup_media(0)

    assert _exists(paths[0])
    assert result.files_deleted == 0


# --- ничьи файлы ---


def test_orphan_files_are_removed():
    """Остаются после ручного удаления поста и после сбоя посреди скачивания.
    По одному незаметны, накапливаются молча."""
    from pathlib import Path

    orphan = Path("media") / "nobody.jpg"
    orphan.write_bytes(b"z" * 4096)
    _age_file(orphan, days=3)

    result = cleanup_media(RETENTION)

    assert not orphan.exists()
    assert result.orphans_deleted == 1


def test_fresh_orphan_is_kept():
    """Файл мог быть скачан секунду назад и ещё не привязан к посту — это
    гонка между загрузкой и уборкой, а не мусор."""
    from pathlib import Path

    fresh = Path("media") / "just_downloaded.jpg"
    fresh.write_bytes(b"z" * 4096)
    _age_file(fresh, hours=1)

    cleanup_media(RETENTION)

    assert fresh.exists()


def test_referenced_file_is_never_treated_as_orphan():
    """Обратная проверка: файл поста в работе не должен попасть под уборку
    ничьих — иначе она сожрала бы очередь целиком.

    Файл здесь СТАРЫЙ (год), поэтому отсрочка для ничьих его не спасает:
    единственное, что стоит между очередью и удалением, — сверка со списком
    путей из базы. Ровно это и проверяется.
    """
    _post_id, paths = _make_post(PostStatus.PENDING_APPROVAL, age_days=365)

    cleanup_media(RETENTION)

    assert _exists(paths[0])


def test_missing_file_does_not_break_cleanup():
    """Файла может уже не быть — удалили руками, потерялся том. Уборка не
    должна из-за этого падать и бросать остальную работу."""
    from pathlib import Path

    post_id, paths = _make_post(PostStatus.REJECTED, age_days=30, variants=1)
    Path(paths[0]).unlink()

    result = cleanup_media(RETENTION)

    assert result.files_deleted == 1  # остался только вариант
    with session_scope() as session:
        assert session.get(Post, post_id).media_path is None


# --- один файл на два поста (F55) ---


def test_shared_file_survives_while_a_live_post_needs_it():
    """НАЙДЕНО НА ЖИВЫХ ДАННЫХ СТЕНДА: 712 путей из 1661 делят по две записи.

    Повтор выстрелившего поста (F55) копирует `media_path` оригинала, а не
    саму картинку. Оригинал к моменту уборки уже `posted` и старый, а повтор
    ждёт модерации — удаление «по статусу оригинала» вынуло бы обложку
    из-под поста, который прямо сейчас в очереди у владельца.
    """
    original_id, paths = _make_post(PostStatus.POSTED, age_days=60)
    shared = paths[0]

    with session_scope() as session:
        repeat = Post(
            kind=PostKind.RECYCLE, original_text="повтор",
            status=PostStatus.REWRITTEN, media_path=shared,
            recycled_from_id=original_id,
        )
        session.add(repeat)
        session.flush()
        repeat_id = repeat.id

    cleanup_media(RETENTION)

    assert _exists(shared), "обложку вынули из-под поста в очереди модерации"
    with session_scope() as session:
        assert session.get(Post, repeat_id).media_path == shared
        # У самого оригинала ссылку всё равно чистим: он отработан, и держать
        # её незачем — файл живёт по ссылке повтора.
        assert session.get(Post, original_id).media_path is None


def test_shared_file_goes_when_both_owners_are_done():
    """Когда и оригинал, и повтор отработаны и выслужили срок — файл уходит.

    Обратная проверка к предыдущей: защита общих файлов не должна превратиться
    в «общие файлы не удаляются никогда», иначе 2,3 ГБ так и останутся.
    """
    _original_id, paths = _make_post(PostStatus.POSTED, age_days=60)
    shared = paths[0]

    with session_scope() as session:
        session.add(Post(
            kind=PostKind.RECYCLE, original_text="повтор",
            status=PostStatus.REJECTED, media_path=shared,
            created_at=datetime.now(timezone.utc) - timedelta(days=60),
        ))

    result = cleanup_media(RETENTION)

    assert not _exists(shared)
    assert result.files_deleted == 1, "один файл — один раз, а не дважды"


def test_shared_path_is_matched_regardless_of_slashes():
    """Один и тот же файл в базе записан по-разному: у одного поста со слэшем,
    у другого — с обратным. Сравнение «как есть» не увидело бы, что это один
    файл, и защита общих файлов молча не сработала бы."""
    _original_id, paths = _make_post(PostStatus.REJECTED, age_days=60)
    shared = paths[0]
    other_form = shared.replace("\\", "/") if "\\" in shared else shared.replace("/", "\\")

    with session_scope() as session:
        session.add(Post(
            kind=PostKind.SOURCE, original_text="в работе",
            status=PostStatus.PENDING_APPROVAL, media_path=other_form,
        ))

    cleanup_media(RETENTION)

    assert _exists(shared), "разная запись пути обошла защиту общих файлов"
