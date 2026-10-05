import sqlite3

import pytest

from benchdesk.backup import backup, main
from benchdesk.storage import Store


def test_backup_contains_committed_wal_and_does_not_change_source(tmp_path):
    source = tmp_path / "original.db"
    Store(source)
    with sqlite3.connect(source) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE sample (value TEXT)")
        db.execute("INSERT INTO sample VALUES ('committed')")
        db.commit()
        output = tmp_path / "copies" / "backup.db"
        backup(source, output)
        with sqlite3.connect(output) as restored:
            assert restored.execute("SELECT value FROM sample").fetchone()[0] == "committed"
            assert restored.execute("SELECT count(*) FROM suites").fetchone()[0] == 1
        assert db.execute("SELECT value FROM sample").fetchone()[0] == "committed"


def test_existing_destination_is_never_modified(tmp_path):
    source = tmp_path / "source.db"
    Store(source)
    output = tmp_path / "existing.db"
    output.write_bytes(b"keep me")
    with pytest.raises(FileExistsError):
        backup(source, output)
    assert output.read_bytes() == b"keep me"


def test_source_cannot_be_destination(tmp_path):
    source = tmp_path / "source.db"
    Store(source)
    original = source.read_bytes()
    with pytest.raises(FileExistsError):
        backup(source, source)
    assert source.read_bytes() == original


def test_missing_source_does_not_create_database(tmp_path):
    source = tmp_path / "missing.db"
    output = tmp_path / "copy.db"
    with pytest.raises(ValueError):
        backup(source, output)
    assert not source.exists() and not output.exists()


def test_invalid_source_removes_only_new_destination(tmp_path):
    source = tmp_path / "broken.db"
    source.write_bytes(b"not sqlite")
    output = tmp_path / "copy.db"
    with pytest.raises(sqlite3.Error):
        backup(source, output)
    assert not output.exists() and source.read_bytes() == b"not sqlite"


def test_backup_cli(tmp_path, capsys):
    source = tmp_path / "source.db"
    Store(source)
    output = tmp_path / "copy.db"
    args = ["--source", str(source), "--output", str(output)]
    main(args)
    assert output.is_file() and "not encrypted" in capsys.readouterr().out
    with pytest.raises(SystemExit) as error:
        main(args)
    assert error.value.code == 2
