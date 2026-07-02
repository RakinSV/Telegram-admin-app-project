"""Бэкап `.env` + обеих SQLite БД (tg_repost + guardian) + `logs/` в один zip.

`.env` бэкапится ВМЕСТЕ с БД намеренно: секреты в БД зашифрованы через
`WEBUI_MASTER_KEY` из `.env` — без него зашифрованные значения невосстановимы
(см. README про `/secrets`). Бэкап БД без `.env` бесполезен.

Только SQLite-пути (`sqlite:///...`) бэкапятся файловой копией — если
`DATABASE_URL`/`GUARDIAN_DATABASE_URL` указывает на другую СУБД (см. CLAUDE.md
про возможный переход на Postgres), путь пропускается с предупреждением, а не
падением: остальной бэкап (`.env`, вторая БД, логи) всё равно ценен.

Запуск:  python -m tg_repost.tools.backup [--keep N]
Cron-пример (ежедневно в 03:00, хранить 14):
  0 3 * * * cd /path/to/repo && python -m tg_repost.tools.backup --keep 14

⚠️ Итоговый zip не шифруется и по чувствительности равен `.env` — не
синхронизировать `backups/` в облако/на другие машины без отдельного
шифрования архива (например, `age`/GPG).
"""

from __future__ import annotations

import argparse
import contextlib
import os
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from dotenv import load_dotenv

from tg_repost.logging_conf import get_logger, setup_logging

logger = get_logger(__name__)

_BACKUP_DIR = Path("backups")


def _sqlite_path(url: str) -> Path | None:
    if not url.startswith("sqlite:///"):
        logger.warning("Не SQLite URL (%s) — файловый бэкап пропущен, нужен снапшот СУБД отдельно", url)
        return None
    return Path(url.removeprefix("sqlite:///"))


def _collect_files() -> list[Path]:
    load_dotenv()  # тот же idempotent-паттерн, что db/session.py
    files: list[Path] = []

    env_path = Path(".env")
    if env_path.is_file():
        files.append(env_path)
    else:
        logger.warning(".env не найден — бэкап без него оставит зашифрованные секреты в БД нечитаемыми")

    for env_var, default in (
        ("DATABASE_URL", "sqlite:///tg_repost.db"),
        ("GUARDIAN_DATABASE_URL", "sqlite:///guardian.db"),
    ):
        db_path = _sqlite_path(os.environ.get(env_var, default))
        if db_path is not None and db_path.is_file():
            files.append(db_path)
        elif db_path is not None:
            logger.warning("БД не найдена: %s (%s)", db_path, env_var)

    logs_dir = Path("logs")
    if logs_dir.is_dir():
        files.extend(p for p in logs_dir.rglob("*") if p.is_file())

    return files


def _prune_old_backups(keep: int) -> None:
    archives = sorted(_BACKUP_DIR.glob("backup_*.zip"), key=lambda p: p.name)
    for stale in archives[:-keep] if keep > 0 else archives:
        stale.unlink()
        logger.info("Удалён старый бэкап: %s", stale.name)


def run_backup(keep: int) -> Path:
    files = _collect_files()
    if not files:
        raise RuntimeError("Нечего бэкапить — не найдены ни .env, ни одна из БД")

    _BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    archive_path = _BACKUP_DIR / f"backup_{stamp}.zip"

    with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as zf:
        for file_path in files:
            zf.write(file_path, arcname=str(file_path))
    # Тот же паттерн, что `crypto.py::append_env_var` — на Windows не даёт
    # POSIX-семантики (только снимает read-only), но не вредит.
    with contextlib.suppress(OSError):
        os.chmod(archive_path, 0o600)

    logger.info("Бэкап создан: %s (%d файлов, %.1f КБ)", archive_path, len(files), archive_path.stat().st_size / 1024)
    _prune_old_backups(keep)
    return archive_path


def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep", type=int, default=14, help="сколько последних бэкапов хранить (0 = все)")
    args = parser.parse_args()

    setup_logging("INFO")
    run_backup(args.keep)


if __name__ == "__main__":
    _main()
