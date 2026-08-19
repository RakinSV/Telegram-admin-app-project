"""Выход за каталог медиа (найдено 2026-08-19).

ЧТО БЫЛО. Роут `/media/{filename}` отвергал «/», «\\» и «..» — список
запрещённых символов. На Linux этого хватало, на Windows нет: строка
`C:.env` не содержит НИ ОДНОГО из трёх, а `Path("media") / "C:.env"` даёт
`C:.env` — файл в текущем каталоге диска C, мимо каталога медиа.

ЧЕМ ЭТО ГРОЗИЛО. Страница доступна роли `editor` (см. `webui/access.py`),
которая по замыслу только модерирует посты. Через неё читался бы `.env`, а
в нём `WEBUI_MASTER_KEY` — ключ, которым расшифровываются ВСЕ секреты
системы: токены всех ботов, ключ AI-провайдера, session string Telethon.
То есть роль «редактор» превращалась в полный доступ.

ПОЧЕМУ ПРОВЕРКА ТЕПЕРЬ ДРУГАЯ. Список запрещённых символов всегда неполон —
это видно по самой находке. Проверяется фактический путь: привести к
абсолютному и убедиться, что он внутри разрешённого каталога. Ровно так уже
сделано при восстановлении из архива (`tools/backup.py`).
"""

from __future__ import annotations

import pathlib

import pytest

from tg_repost.webui.crud_routes import _safe_media_path


@pytest.fixture
def media_dir(tmp_path, monkeypatch):
    """Каталог медиа с одним настоящим файлом и «секретом» снаружи."""
    from tg_repost.config import get_settings, invalidate_settings_cache

    inside = tmp_path / "media"
    inside.mkdir()
    (inside / "cover.jpg").write_bytes(b"picture-bytes")

    # Файл ЗА пределами каталога — то, до чего дотянуться нельзя.
    (tmp_path / "secret.env").write_text("WEBUI_MASTER_KEY=очень-секретно")

    # Настройка `media_dir` по умолчанию относительная («media»), поэтому
    # достаточно перейти в каталог теста — подмена переменной среды тут
    # только запутала бы.
    monkeypatch.chdir(tmp_path)
    invalidate_settings_cache()
    assert (
        pathlib.Path(get_settings().media_dir).resolve() == inside.resolve()
    ), "тест смотрит не в тот каталог, что и код"
    yield inside
    invalidate_settings_cache()


def test_normal_file_is_served(media_dir):
    """Обратная проверка: защита не должна закрыть саму фичу."""
    assert _safe_media_path("cover.jpg") is not None


def test_drive_relative_path_is_refused(media_dir):
    """ТОТ САМЫЙ СЛУЧАЙ: ни слэша, ни «..», а из каталога выходит.

    Проверка по списку символов это пропускала.
    """
    assert _safe_media_path("C:secret.env") is None, (
        "относительный путь диска снова выводит за каталог медиа"
    )


@pytest.mark.parametrize("attempt", [
    "..",
    "../secret.env",
    "..\\secret.env",
    "/etc/passwd",
    "C:/Windows/win.ini",
    "\\\\server\\share\\file",
    "subdir/../../secret.env",
])
def test_known_escapes_are_refused(media_dir, attempt):
    assert _safe_media_path(attempt) is None, f"«{attempt}» выводит за каталог"


def test_missing_file_is_refused(media_dir):
    assert _safe_media_path("нет-такого.jpg") is None


def test_absurd_name_does_not_crash(media_dir):
    """Слишком длинное имя роняло бы 500 вместо 404 — а 500 на страже это
    ещё и подсказка снаружи, что защита есть и где она."""
    assert _safe_media_path("ф" * 5000) is None


def test_symlink_out_of_media_is_refused(media_dir, tmp_path):
    """Ссылка внутри каталога, ведущая наружу, — тот же выход, только через
    файловую систему. Проверка по символам не увидела бы его вовсе."""
    link = media_dir / "innocent.jpg"
    try:
        link.symlink_to(tmp_path / "secret.env")
    except (OSError, NotImplementedError):
        pytest.skip("создание ссылок недоступно (на Windows нужны права)")

    assert _safe_media_path("innocent.jpg") is None, "ссылка вывела за каталог"
