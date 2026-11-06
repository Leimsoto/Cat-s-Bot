"""Copy deployment state using SQLite's backup API, including committed WAL data.

Stop the old bot first for a consistent cutover across all files. This does not
import or execute the bot and does not run checks or migrations on its databases.
"""

import shutil
import sqlite3
import sys
from pathlib import Path


def snapshot(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    database_count = 0
    for folder in ("data", "workspaces"):
        source_folder = source / folder
        if not source_folder.is_dir():
            continue
        for item in source_folder.rglob("*"):
            target = destination / item.relative_to(source)
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if item.name.endswith(("-wal", "-shm", "-journal")):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if item.suffix in {".db", ".sqlite", ".sqlite3"}:
                original = sqlite3.connect(item.resolve().as_uri() + "?mode=ro", uri=True)
                backup = sqlite3.connect(target)
                try:
                    original.backup(backup)
                finally:
                    backup.close()
                    original.close()
                database_count += 1
            else:
                shutil.copy2(item, target)
    print(f"State saved to {destination}; {database_count} SQLite databases copied.")


if __name__ == "__main__":
    snapshot(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
