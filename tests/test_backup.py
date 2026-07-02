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
