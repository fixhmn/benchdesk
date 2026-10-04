import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from benchdesk.gui import CheckDialog, Window
from benchdesk.storage import Store


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def wait_for(qt_app, predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qt_app.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("GUI operation did not complete")


def test_window_runs_demo_saves_history_and_recovers_buttons(qt_app, tmp_path):
    window = Window(Store(tmp_path / "gui.db"), start_demo=True)
    try:
        assert window.checks.rowCount() == 4
        window.start_run()
        assert not window.run_button.isEnabled()
        wait_for(qt_app, lambda: window.worker is None)
        assert window.results.rowCount() == 4
        assert "PASS 4" in window.summary.text()
        assert window.history.rowCount() == 1
        assert window.report_button.isEnabled() and window.run_button.isEnabled()
        window.demo_mode.setCurrentText("Server error")
        window.start_run()
        wait_for(qt_app, lambda: window.worker is None)
        assert "regressions" in window.compare_label.text()
        assert window.history.rowCount() == 2
    finally:
        window.close()


def test_close_cancels_active_request_and_waits_for_thread(qt_app, tmp_path):
    window = Window(Store(tmp_path / "cancel.db"), start_demo=True)
    window.demo_mode.setCurrentText("Slow responses")
    window.start_run()
    window.close()
    wait_for(qt_app, lambda: window.worker is None)
    assert window.current_run["cancelled"]
    assert window.demo is None


def test_editor_builds_valid_check(qt_app):
    editor = CheckDialog()
    editor.name.setText("API health")
    editor.json_path.setText("status")
    editor.expected.setText('"ok"')
    editor.save()
    assert editor.value.json_path == "status"
    assert editor.value.expected_value == "ok"
