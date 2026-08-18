"""Уборка медиафайлов отработанных постов (найдено на стенде 2026-08-18).

ЦИФРЫ, С КОТОРЫХ ЭТО НАЧАЛОСЬ. На стенде лежало 1663 файла на 2,8 ГБ при базе
в 8 МБ. Из них 2,3 ГБ — обложки ОТКЛОНЁННЫХ постов: владелец сказал «нет», а
картинки остались навсегда. Ещё 401 МБ — упавших. Ничто в системе их не
удаляло, и диск рос до упора: рерайт и публикация встали бы разом, а причина
выглядела бы как «всё сломалось».

ЧТО УДАЛЯЕТСЯ. Только файлы постов в КОНЕЧНЫХ состояниях и только после срока
хранения:

* `rejected` — решение принято, к посту не вернутся;
* `posted` — картинка уже в Telegram, локальная копия ничего не даёт;
* `failed` — сюда же, но срок ДВОЙНОЙ: упавший пост можно повторить из
  админки, и повтор без обложки — это молчаливая потеря, а не уборка.

Всё остальное — новое, в рерайте, на модерации, одобренное — не трогается
вовсе, независимо от возраста.

ОДИН ФАЙЛ МОГУТ ДЕЛИТЬ ДВА ПОСТА. Повтор выстрелившего поста (F55) копирует
`media_path` оригинала, а не саму картинку: `scheduler/recycle.py` создаёт
новый пост с тем же путём. Оригинал при этом `posted` и старый, а повтор ждёт
модерации — то есть удаление «по статусу оригинала» вынуло бы обложку
из-под поста, который прямо сейчас в очереди у владельца. Замер на стенде:
712 путей из 1661 делят по две записи. Поэтому файл удаляется, только если
ВСЕ ссылающиеся на него записи сами идут под уборку.

ССЫЛКИ В БАЗЕ ЧИСТЯТСЯ ВМЕСТЕ С ФАЙЛАМИ. Оставить путь на удалённый файл
значило бы сломать страницу модерации битой картинкой и заставить публикацию
падать на чтении несуществующего файла.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tg_repost.db.models import Post, PostCoverVariant, PostStatus
from tg_repost.db.session import session_scope
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)

# Состояния, из которых пост уже не вернётся к публикации.
_FINAL_STATUSES = (PostStatus.REJECTED, PostStatus.POSTED)
# У упавшего поста есть кнопка «повторить», поэтому его обложка живёт дольше.
_RETRY_MULTIPLIER = 2

# Ничьи файлы младше суток не трогаем: файл мог быть только что скачан и ещё
# не привязан к посту — гонка между загрузкой и уборкой.
_ORPHAN_GRACE_HOURS = 24

_MEDIA_DIR = Path("media")


@dataclass(frozen=True)
class CleanupResult:
    files_deleted: int
    bytes_freed: int
    orphans_deleted: int

    @property
    def megabytes_freed(self) -> float:
        return round(self.bytes_freed / 1024 / 1024, 1)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _drop_file(path_text: str | None) -> int:
    """Удалить файл, вернуть освобождённые байты. Нет файла — не беда."""
    if not path_text:
        return 0
    path = Path(path_text)
    try:
        size = path.stat().st_size
        path.unlink()
        return size
    except OSError:
        # Файла уже нет или он занят — уборка не должна из-за этого падать.
        return 0


def _normalized(path_text: str) -> str:
    """Один и тот же файл в базе может быть записан по-разному: со слэшем и с
    обратным слэшем, относительно и абсолютно. Сравнивать надо приведённое."""
    return os.path.normcase(os.path.abspath(str(path_text)))


def _paths_held_by_others(session, doomed_ids: set[int]) -> set[str]:
    """Пути, которые держат записи, НЕ идущие под уборку в этот проход.

    Сюда попадают и посты в работе, и отработанные, но ещё не выслужившие
    срок. Такой файл трогать нельзя, даже если на него ссылается уборяемый
    пост: файл один, а хозяев у него два.
    """
    held: set[str] = set()
    for (post_id, path) in session.query(Post.id, Post.media_path).filter(
        Post.media_path.isnot(None)
    ):
        if post_id not in doomed_ids:
            held.add(_normalized(path))
    for (post_id, path) in session.query(
        PostCoverVariant.post_id, PostCoverVariant.media_path
    ).filter(PostCoverVariant.media_path.isnot(None)):
        if post_id not in doomed_ids:
            held.add(_normalized(path))
    return held


def _drop_shared_aware(path_text: str | None, protected: set[str]) -> int:
    """Удалить файл, если его не держит кто-то ещё."""
    if not path_text:
        return 0
    if _normalized(path_text) in protected:
        logger.info("Уборка медиа: %s оставлен — на него ссылается живой пост",
                    path_text)
        return 0
    return _drop_file(path_text)


def cleanup_media(retention_days: int) -> CleanupResult:
    """Убрать медиа отработанных постов старше срока хранения."""
    if retention_days <= 0:
        return CleanupResult(0, 0, 0)

    now = _utcnow()
    plain_cutoff = now - timedelta(days=retention_days)
    retry_cutoff = now - timedelta(days=retention_days * _RETRY_MULTIPLIER)

    files_deleted = 0
    bytes_freed = 0

    with session_scope() as session:
        candidates = (
            session.query(Post)
            .filter(
                Post.media_path.isnot(None),
                (
                    (Post.status.in_(_FINAL_STATUSES) & (Post.created_at < plain_cutoff))
                    | ((Post.status == PostStatus.FAILED) & (Post.created_at < retry_cutoff))
                ),
            )
            .all()
        )
        doomed_ids = {post.id for post in candidates}
        protected = _paths_held_by_others(session, doomed_ids)

        for post in candidates:
            # Ссылку чистим всегда, файл — только если его больше никто не
            # держит. Иначе повтор в очереди модерации остался бы с битой
            # картинкой, а публикация упала бы на чтении удалённого файла.
            freed = _drop_shared_aware(post.media_path, protected)
            if freed:
                files_deleted += 1
                bytes_freed += freed
            post.media_path = None

            variants = (
                session.query(PostCoverVariant)
                .filter(PostCoverVariant.post_id == post.id)
                .all()
            )
            for variant in variants:
                freed = _drop_shared_aware(variant.media_path, protected)
                if freed:
                    files_deleted += 1
                    bytes_freed += freed
                session.delete(variant)
            post.active_cover_variant_index = None

    orphans, orphan_bytes = _drop_orphans(now)
    bytes_freed += orphan_bytes

    result = CleanupResult(files_deleted, bytes_freed, orphans)
    if result.files_deleted or result.orphans_deleted:
        logger.info(
            "Уборка медиа: удалено %d файлов отработанных постов и %d ничьих, "
            "освобождено %.1f МБ",
            result.files_deleted, result.orphans_deleted, result.megabytes_freed,
        )
    return result


def _drop_orphans(now: datetime) -> tuple[int, int]:
    """Файлы, на которые не ссылается ни один пост и ни один вариант.

    Такие остаются после ручного удаления поста и после сбоя посреди
    скачивания. По одному они незаметны, но накапливаются молча.
    """
    if not _MEDIA_DIR.exists():
        return 0, 0

    with session_scope() as session:
        referenced = {
            _normalized(path)
            for (path,) in session.query(Post.media_path).filter(
                Post.media_path.isnot(None)
            )
        }
        referenced |= {
            _normalized(path)
            for (path,) in session.query(PostCoverVariant.media_path).filter(
                PostCoverVariant.media_path.isnot(None)
            )
        }

    grace = now - timedelta(hours=_ORPHAN_GRACE_HOURS)
    deleted = 0
    freed = 0
    for path in _MEDIA_DIR.rglob("*"):
        if not path.is_file():
            continue
        if _normalized(str(path)) in referenced:
            continue
        try:
            changed = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        except OSError:
            continue
        if changed > grace:
            continue
        size = _drop_file(str(path))
        if size:
            deleted += 1
            freed += size
    return deleted, freed
