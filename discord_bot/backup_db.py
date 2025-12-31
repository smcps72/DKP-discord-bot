import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from discord_bot.database import DB_FILE

DEFAULT_BACKUP_DIR = os.getenv("DKP_DB_BACKUP_DIR", "db_backups")
DEFAULT_RETENTION = int(os.getenv("DKP_DB_BACKUP_RETENTION", "288"))


def get_db_path() -> Path:
    return Path(DB_FILE).resolve()


def ensure_backup_dir() -> Path:
    path = Path(DEFAULT_BACKUP_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def create_backup(db_path: Path, backup_dir: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / f"{db_path.stem}_{timestamp}.db"

    src = sqlite3.connect(db_path.as_posix(), timeout=30)
    dst = sqlite3.connect(backup_path.as_posix())

    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    return backup_path


def prune_backups(backup_dir: Path, retention: int) -> None:
    files = sorted(backup_dir.glob("*.db"))
    if len(files) <= retention:
        return

    for old in files[:-retention]:
        try:
            old.unlink()
        except FileNotFoundError:
            pass


def main() -> None:
    db_path = get_db_path()
    if not db_path.exists():
        raise SystemExit(f"Database file not found at {db_path}")

    backup_dir = ensure_backup_dir()
    backup_path = create_backup(db_path, backup_dir)
    prune_backups(backup_dir, DEFAULT_RETENTION)

    print(f"Created backup: {backup_path}")


if __name__ == "__main__":
    main()
