"""SQLite-consistent local safety copies. Never uploads or restores a live DB."""
from __future__ import annotations

import os
import re
import sqlite3
import tempfile
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

BACKUP_NAME = re.compile(r"relay-\d{8}T\d{12}Z-[a-zA-Z0-9_-]+\.sqlite3\Z")


def backup_database(source: Path, directory: Path, namespace: str, keep: int = 3) -> Path:
    source, directory = Path(source), Path(directory)
    if not source.is_file() or source.is_symlink() or not 1 <= keep <= 7:
        raise ValueError("invalid_backup_source")
    if directory.is_symlink():
        raise ValueError("invalid_backup_directory")
    directory.mkdir(mode=0o700, parents=False, exist_ok=True)
    if directory.resolve() != directory.absolute():
        raise ValueError("symlink_in_backup_path")
    os.chmod(directory, 0o700)
    fd, temp_name = tempfile.mkstemp(prefix=".relay-copy-", dir=directory)
    os.close(fd)
    temporary = Path(temp_name)
    deadline = time.monotonic() + 15

    def progress(status, remaining, total):
        if time.monotonic() > deadline:
            raise TimeoutError("backup_timeout")

    try:
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=1.5)) as src:
            metadata = dict(src.execute("SELECT key,value FROM metadata"))
            if metadata.get("schema") != "1" or metadata.get("namespace") != namespace:
                raise ValueError("incompatible_backup_source")
            with closing(sqlite3.connect(temporary)) as dest:
                src.backup(dest, pages=128, progress=progress, sleep=0.02)
                if dest.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise ValueError("invalid_backup")
        with temporary.open("rb") as fh:
            os.fsync(fh.fileno())
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        target = directory / ("relay-" + stamp + "-" + temporary.name.rsplit("-", 1)[-1] + ".sqlite3")
        os.replace(temporary, target)
        dfd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
        copies = sorted((p for p in directory.iterdir() if BACKUP_NAME.fullmatch(p.name)
                         and p.is_file() and not p.is_symlink()), key=lambda p: p.name, reverse=True)
        for old in copies[keep:]:
            old.unlink()
        return target
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    from relay_render import storage_paths, NAMESPACE
    try:
        db = storage_paths(os.environ)
        backup_database(db, db.parent / "backups", NAMESPACE)
    except Exception:
        raise SystemExit("Relay backup failed; no live database was replaced.") from None
    print("Relay backup complete on the private disk; this is not an offsite backup.")
