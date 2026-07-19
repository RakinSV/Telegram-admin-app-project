"""Тесты `tg_repost.tools.backup` — сбор файлов, архивация, ротация (Улучшение: автобэкап)."""

from __future__ import annotations

from zipfile import ZipFile

import pytest

from tg_repost.tools import backup


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("GUARDIAN_DATABASE_URL", raising=False)
    yield tmp_path


def test_run_backup_archives_env_and_both_databases(tmp_path):
    (tmp_path / ".env").write_text("SECRET=x")
    (tmp_path / "tg_repost.db").write_bytes(b"sqlite-data")
    (tmp_path / "guardian.db").write_bytes(b"sqlite-data-2")

    archive_path = backup.run_backup(keep=14)

    with ZipFile(archive_path) as zf:
        names = set(zf.namelist())
    assert names == {".env", "tg_repost.db", "guardian.db"}


def test_run_backup_includes_log_files(tmp_path):
    (tmp_path / ".env").write_text("SECRET=x")
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    (logs_dir / "tg_repost.log").write_text("log line")

    archive_path = backup.run_backup(keep=14)

    with ZipFile(archive_path) as zf:
        names = set(zf.namelist())
    assert "logs/tg_repost.log" in names or "logs\\tg_repost.log" in names


def test_run_backup_respects_custom_database_urls(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("SECRET=x")
    custom_dir = tmp_path / "db"
    custom_dir.mkdir()
    (custom_dir / "tg_repost.db").write_bytes(b"data")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///db/tg_repost.db")

    archive_path = backup.run_backup(keep=14)

    with ZipFile(archive_path) as zf:
        names = zf.namelist()
    assert any("tg_repost.db" in n for n in names)


def test_run_backup_skips_non_sqlite_url_without_crashing(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("SECRET=x")
    (tmp_path / "tg_repost.db").write_bytes(b"data")  # не должен попасть — DATABASE_URL не sqlite
    (tmp_path / "guardian.db").write_bytes(b"data-2")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@host/db")

    archive_path = backup.run_backup(keep=14)

    with ZipFile(archive_path) as zf:
        names = zf.namelist()
    assert "tg_repost.db" not in names
    assert ".env" in names
    assert "guardian.db" in names  # вторая БД всё ещё sqlite — бэкапится нормально


def test_run_backup_raises_when_nothing_to_back_up(tmp_path):
    with pytest.raises(RuntimeError):
        backup.run_backup(keep=14)


def test_run_backup_falls_back_to_docker_data_db_layout(tmp_path):
    # Регрессия (security-ревью): задокументированный cron-рецепт запускает
    # backup.py С ХОСТА, где .env читает "sqlite:///tg_repost.db" (без db/ —
    # тот префикс только внутри контейнера, через docker-compose environment:
    # override, который никогда не попадает в сам файл .env на хосте). Реальный
    # файл в Docker-деплое лежит в ./data/db/ (bind mount) — без фолбэка
    # бэкап "успешен", но БЕЗ БД внутри.
    (tmp_path / ".env").write_text("SECRET=x")
    data_db = tmp_path / "data" / "db"
    data_db.mkdir(parents=True)
    (data_db / "tg_repost.db").write_bytes(b"real-docker-db")
    # DATABASE_URL НЕ переопределён — дефолт "sqlite:///tg_repost.db", как
    # реально лежит в .env на хосте при Docker-деплое.

    archive_path = backup.run_backup(keep=14)

    with ZipFile(archive_path) as zf:
        names = zf.namelist()
    assert any(n.endswith("tg_repost.db") for n in names)


def test_run_backup_falls_back_to_docker_data_logs_layout(tmp_path):
    (tmp_path / ".env").write_text("SECRET=x")
    data_logs = tmp_path / "data" / "logs"
    data_logs.mkdir(parents=True)
    (data_logs / "tg_repost.log").write_text("docker log line")

    archive_path = backup.run_backup(keep=14)

    with ZipFile(archive_path) as zf:
        names = zf.namelist()
    assert any("tg_repost.log" in n for n in names)


def test_run_backup_prefers_direct_path_over_docker_fallback(tmp_path):
    # Если файл есть по прямому пути — фолбэк в data/db не должен даже
    # проверяться (уж тем более не должен подменить реальный путь).
    (tmp_path / ".env").write_text("SECRET=x")
    (tmp_path / "tg_repost.db").write_bytes(b"direct-db")
    data_db = tmp_path / "data" / "db"
    data_db.mkdir(parents=True)
    (data_db / "tg_repost.db").write_bytes(b"should-not-be-used")

    archive_path = backup.run_backup(keep=14)

    with ZipFile(archive_path) as zf:
        content = zf.read("tg_repost.db")
    assert content == b"direct-db"


def test_prune_keeps_only_newest_n_archives(tmp_path):
    (tmp_path / ".env").write_text("SECRET=x")
    backups_dir = tmp_path / "backups"
    backups_dir.mkdir()
    for name in ("backup_20200101_000000.zip", "backup_20210101_000000.zip", "backup_20220101_000000.zip"):
        (backups_dir / name).write_bytes(b"x")

    backup._prune_old_backups(keep=2)

    remaining = {p.name for p in backups_dir.glob("backup_*.zip")}
    assert remaining == {"backup_20210101_000000.zip", "backup_20220101_000000.zip"}


def test_prune_with_keep_zero_removes_all(tmp_path):
    backups_dir = tmp_path / "backups"
    backups_dir.mkdir()
    (backups_dir / "backup_20200101_000000.zip").write_bytes(b"x")

    backup._prune_old_backups(keep=0)

    assert list(backups_dir.glob("backup_*.zip")) == []


# --- restore_backup (аудит: полный бэкап/восстановление из веб-админки) ---


def test_restore_backup_round_trips_env_and_both_databases(tmp_path):
    (tmp_path / ".env").write_text("SECRET=x")
    (tmp_path / "tg_repost.db").write_bytes(b"original-tg-repost")
    (tmp_path / "guardian.db").write_bytes(b"original-guardian")
    archive_path = backup.run_backup(keep=14)

    # Симулируем повреждение/потерю текущего состояния.
    (tmp_path / ".env").write_text("CORRUPTED")
    (tmp_path / "tg_repost.db").write_bytes(b"corrupted")
    (tmp_path / "guardian.db").write_bytes(b"corrupted")

    restored = backup.restore_backup(archive_path)

    assert (tmp_path / ".env").read_text() == "SECRET=x"
    assert (tmp_path / "tg_repost.db").read_bytes() == b"original-tg-repost"
    assert (tmp_path / "guardian.db").read_bytes() == b"original-guardian"
    assert len(restored) == 3


def test_restore_backup_rejects_zip_slip_path_traversal(tmp_path):
    """Аудит: архив загружается пользователем через веб-форму — запись с
    "../" в имени не должна писать файл ЗА ПРЕДЕЛЫ текущей рабочей
    директории. ВЕСЬ архив отклоняется (ничего не пишется), не только
    опасная запись — частичное восстановление хуже явного отказа."""
    from zipfile import ZipFile as _ZipFile

    outside_marker = tmp_path.parent / "should-not-exist-zip-slip.txt"
    outside_marker.unlink(missing_ok=True)

    malicious = tmp_path / "evil.zip"
    with _ZipFile(malicious, "w") as zf:
        zf.writestr(".env", "SECRET=x")  # безопасная запись — тоже не должна примениться
        zf.writestr("../should-not-exist-zip-slip.txt", "pwned")

    try:
        with pytest.raises(ValueError):
            backup.restore_backup(malicious)
        assert not outside_marker.exists()
        assert not (tmp_path / ".env").exists()  # безопасная запись из ТОГО ЖЕ архива тоже не применилась
    finally:
        outside_marker.unlink(missing_ok=True)


def test_restore_backup_creates_missing_parent_directories(tmp_path):
    (tmp_path / ".env").write_text("SECRET=x")
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    (logs_dir / "tg_repost.log").write_text("log line")
    archive_path = backup.run_backup(keep=14)

    import shutil
    shutil.rmtree(logs_dir)

    backup.restore_backup(archive_path)

    assert (tmp_path / "logs" / "tg_repost.log").read_text() == "log line"
