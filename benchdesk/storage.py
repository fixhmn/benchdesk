import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from benchdesk.models import Suite, demo_suite


def default_database():
    # Packaged apps need a writable location, not their installation directory.
    root = Path(os.getenv("LOCALAPPDATA", str(Path.home() / ".local" / "share")))
    return root / "BenchDesk" / "benchdesk.db"


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > 1:
                raise ValueError("Database belongs to a newer BenchDesk version")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS suites (id TEXT PRIMARY KEY, name TEXT, document TEXT);
                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY, suite_id TEXT, fingerprint TEXT,
                    started_at TEXT, document TEXT
                );
                CREATE INDEX IF NOT EXISTS runs_suite ON runs(suite_id, id);
                PRAGMA user_version=1;
            """)
            if not db.execute("SELECT count(*) FROM suites").fetchone()[0]:
                suite = demo_suite()
                db.execute(
                    "INSERT INTO suites VALUES (?,?,?)", (suite.id, suite.name, suite.to_json())
                )

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        try:
            with db:
                yield db
        finally:
            db.close()

    def suites(self):
        with self.connect() as db:
            return [
                Suite.from_json(row[0])
                for row in db.execute("SELECT document FROM suites ORDER BY name")
            ]

    def save_suite(self, suite):
        suite.validate()
        with self.connect() as db:
            db.execute(
                "INSERT INTO suites VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET "
                "name=excluded.name, document=excluded.document",
                (suite.id, suite.name, suite.to_json()),
            )

    def save_run(self, suite, run):
        fingerprint = hashlib.sha256(suite.to_json().encode()).hexdigest()
        with self.connect() as db:
            cursor = db.execute(
                "INSERT INTO runs(suite_id,fingerprint,started_at,document) VALUES (?,?,?,?)",
                (suite.id, fingerprint, run["started_at"], json.dumps(run)),
            )
            return cursor.lastrowid

    def history(self, suite_id):
        with self.connect() as db:
            return [
                {"id": row[0], **json.loads(row[1])}
                for row in db.execute(
                    "SELECT id,document FROM runs WHERE suite_id=? ORDER BY id DESC LIMIT 100",
                    (suite_id,),
                )
            ]

    def previous(self, suite, run_id, base_url):
        with self.connect() as db:
            current = db.execute(
                "SELECT fingerprint FROM runs WHERE id=? AND suite_id=?", (run_id, suite.id)
            ).fetchone()
            if current is None:
                return None
            fingerprint = current[0]
            rows = db.execute(
                "SELECT document FROM runs WHERE suite_id=? AND fingerprint=? AND id<? "
                "ORDER BY id DESC",
                (suite.id, fingerprint, run_id),
            )
            for row in rows:
                run = json.loads(row[0])
                if not run["cancelled"] and run["base_url"] == base_url:
                    return run
        return None
