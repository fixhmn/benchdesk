import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_headless_cli_creates_report_and_refuses_overwrite(tmp_path):
    report = tmp_path / "report.html"
    command = [sys.executable, "-m", "benchdesk", "--headless", "--demo", "--output", str(report)]
    first = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=20)
    assert first.returncode == 0
    original = report.read_bytes()
    assert b"PASS 4" in original
    second = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=20)
    assert second.returncode == 2 and report.read_bytes() == original


def test_gui_smoke_process(tmp_path):
    command = [
        sys.executable,
        "-m",
        "benchdesk",
        "--smoke-test",
        "--database",
        str(tmp_path / "smoke.db"),
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        timeout=20,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
    )
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")


def test_invalid_suite_does_not_contact_network(tmp_path):
    suite = tmp_path / "bad.json"
    suite.write_text("{}", encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, "-m", "benchdesk", "--headless", "--suite", str(suite)],
        cwd=ROOT,
        capture_output=True,
        timeout=10,
    )
    assert completed.returncode == 2
