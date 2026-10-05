"""Create a consistent local SQLite backup without opening the desktop app."""

import argparse
import sqlite3
import time
from pathlib import Path

from benchdesk.storage import default_database


def backup(source, destination):
    source, destination = Path(source), Path(destination)
    if not source.is_file():
        raise ValueError("Source database does not exist")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Reserve the name exclusively: an exists() check alone has a race window.
    with destination.open("xb"):
        pass
    started = time.monotonic()

    def progress(status, remaining, total):
        if time.monotonic() - started > 15:
            raise TimeoutError("Database stayed busy; retry the backup later")

    try:
        original = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
        copy = None
        try:
            copy = sqlite3.connect(destination, timeout=5)
            original.backup(copy, pages=100, progress=progress, sleep=0.05)
            if copy.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Backup integrity check failed")
        finally:
            if copy is not None:
                copy.close()
            original.close()
    except Exception:
        # Only this operation's newly reserved destination is removed on failure.
        destination.unlink(missing_ok=True)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=default_database())
    parser.add_argument("--output", type=Path, required=True, help="New backup file; no overwrites")
    args = parser.parse_args(argv)
    try:
        backup(args.source, args.output)
    except (OSError, ValueError, sqlite3.Error):
        parser.exit(
            2, "Could not back up database. Check source, permissions, and a new output path.\n"
        )
    print(f"Backup created: {args.output}. Keep it private; SQLite backups are not encrypted.")


if __name__ == "__main__":
    main()
