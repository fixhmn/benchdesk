import asyncio
import json
import os
import sqlite3
import sys
import threading
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

from PySide6.QtCore import QThread, Signal, Slot
from PySide6.QtGui import QColor, QFontDatabase
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from benchdesk.demo import DemoServer
from benchdesk.models import Check, Suite, new_id, validate_base_url
from benchdesk.report import comparison, render_html, totals
from benchdesk.runner import run_suite

STYLE = """
QMainWindow, QDialog { background: #f4f6fa; }
QWidget { font-family: 'Segoe UI'; font-size: 10pt; color: #26364b; }
QLabel#title { font-size: 22pt; font-weight: 600; }
QLabel#muted { color: #65758b; }
QLabel#summary { background: white; border: 1px solid #dce3ec; padding: 14px; border-radius: 6px; }
QPushButton { padding: 7px 12px; background: white; border: 1px solid #cdd7e4; border-radius: 4px; }
QPushButton:hover { background: #e9eff8; }
QPushButton:disabled { color: #99a6b7; }
QPushButton#primary { background: #245fa4; color: white; border: none; }
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background: white; border: 1px solid #cdd7e4; padding: 5px; border-radius: 3px;
}
QTableWidget { background: white; gridline-color: #edf0f5; border: 1px solid #dce3ec; }
QHeaderView::section { background: #eaf0f7; padding: 8px; border: none; font-weight: 600; }
QTabBar::tab { padding: 9px 18px; } QProgressBar { border: 1px solid #dce3ec; text-align: center; }
QProgressBar::chunk { background: #245fa4; }
"""


class RunThread(QThread):
    result_ready = Signal(object)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, suite, url, repeats, parent=None):
        super().__init__(parent)
        self.suite, self.url, self.repeats = suite, url, repeats
        self.cancel = threading.Event()

    def run(self):
        try:
            report = asyncio.run(
                run_suite(
                    self.suite,
                    self.url,
                    self.repeats,
                    self.cancel,
                    self.result_ready.emit,
                )
            )
            self.completed.emit(report)
        except Exception:
            # Never display raw request exceptions that could contain credentials.
            self.failed.emit(
                "Run failed unexpectedly. Check the suite configuration and environment."
            )


class CheckDialog(QDialog):
    def __init__(self, check=None, parent=None):
        super().__init__(parent)
        self.original = check or Check("New check")
        self.value = None
        self.setWindowTitle("Edit check" if check else "Add check")
        self.resize(520, 600)
        form = QFormLayout(self)
        self.name = QLineEdit(self.original.name)
        self.path = QLineEdit(self.original.path)
        self.method = QComboBox()
        self.method.addItems(["GET", "POST"])
        self.method.setCurrentText(self.original.method)
        self.status = QSpinBox()
        self.status.setRange(100, 599)
        self.status.setValue(self.original.expected_status)
        self.budget = QSpinBox()
        self.budget.setRange(1, 30000)
        self.budget.setValue(self.original.max_ms)
        self.timeout = QDoubleSpinBox()
        self.timeout.setRange(0.1, 30)
        self.timeout.setValue(self.original.timeout_s)
        self.json_path = QLineEdit(self.original.json_path)
        self.json_path.setPlaceholderText("items.0.name (optional)")
        self.expected = QLineEdit(json.dumps(self.original.expected_value))
        self.expected.setPlaceholderText('JSON value, e.g. "ok" or true')
        self.headers = QPlainTextEdit(json.dumps(self.original.headers, indent=2))
        self.headers.setMaximumHeight(100)
        self.body = QPlainTextEdit(self.original.body)
        self.body.setMaximumHeight(100)
        self.enabled = QCheckBox("Include in runs")
        self.enabled.setChecked(self.original.enabled)
        for label, widget in [
            ("Name", self.name),
            ("Path", self.path),
            ("Method", self.method),
            ("Expected HTTP", self.status),
            ("Budget (ms)", self.budget),
            ("Deadline (seconds)", self.timeout),
            ("JSON path", self.json_path),
            ("Expected JSON value", self.expected),
            ("Headers (JSON object)", self.headers),
            ("POST body", self.body),
            ("", self.enabled),
        ]:
            form.addRow(label, widget)
        note = QLabel(
            "Credentials: use env:BENCHDESK_TOKEN in header values.\n"
            "Bodies and paths may contain private data; keep suites private."
        )
        note.setObjectName("muted")
        form.addRow(note)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def save(self):
        try:
            self.value = Check(
                self.name.text().strip(),
                self.path.text().strip(),
                self.method.currentText(),
                self.status.value(),
                self.json_path.text().strip(),
                json.loads(self.expected.text()),
                self.budget.value(),
                self.timeout.value(),
                json.loads(self.headers.toPlainText()),
                self.body.toPlainText(),
                self.enabled.isChecked(),
                self.original.id,
            ).validate()
        except (ValueError, TypeError):
            QMessageBox.warning(
                self, "Check not saved", "Check the fields, JSON values, and header references."
            )
            return
        self.accept()


def make_table(headers):
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    table.horizontalHeader().setStretchLastSection(True)
    table.verticalHeader().setVisible(False)
    return table


def put_row(table, row, values):
    for column, value in enumerate(values):
        item = QTableWidgetItem(str(value))
        if value in {"PASS", "FAIL", "ERROR", "CANCELLED"}:
            item.setForeground(
                QColor(
                    {
                        "PASS": "#207747",
                        "FAIL": "#b34a23",
                        "ERROR": "#a32d3b",
                        "CANCELLED": "#65758b",
                    }[value]
                )
            )
        table.setItem(row, column, item)


class Window(QMainWindow):
    def __init__(self, store, start_demo=False):
        super().__init__()
        # Isolated Windows sessions can lack Qt's system-font registry lookup.
        if sys.platform == "win32" and "Segoe UI" not in QFontDatabase.families():
            fonts = Path(os.getenv("SystemRoot", "C:/Windows")) / "Fonts"
            for name in ("segoeui.ttf", "segoeuib.ttf"):
                if (fonts / name).is_file():
                    QFontDatabase.addApplicationFont(str(fonts / name))
        self.store = store
        self.worker = None
        self.demo = None
        self.current_run = None
        self.current_run_id = None
        self.closing = False
        self.setWindowTitle("BenchDesk · Service checks")
        self.resize(1180, 800)
        self.setMinimumSize(900, 650)
        self.setStyleSheet(STYLE)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 20, 24, 20)
        title = QLabel("BenchDesk")
        title.setObjectName("title")
        layout.addWidget(title)
        subtitle = QLabel("Repeatable service checks. Clear results. No mystery failures.")
        subtitle.setObjectName("muted")
        layout.addWidget(subtitle)

        toolbar = QHBoxLayout()
        self.suite_choice = QComboBox()
        self.suite_choice.setMinimumWidth(250)
        self.suite_choice.currentIndexChanged.connect(self.select_suite)
        toolbar.addWidget(self.suite_choice, 1)
        self.edit_controls = [self.suite_choice]
        for text, action in [
            ("New suite", self.new_suite),
            ("Import", self.import_suite),
            ("Export suite", self.export_suite),
        ]:
            button = QPushButton(text)
            button.clicked.connect(action)
            toolbar.addWidget(button)
            self.edit_controls.append(button)
        layout.addLayout(toolbar)

        target = QHBoxLayout()
        target.addWidget(QLabel("Service URL"))
        self.url = QLineEdit("http://127.0.0.1:8765")
        target.addWidget(self.url, 1)
        target.addWidget(QLabel("Rounds"))
        self.repeats = QSpinBox()
        self.repeats.setRange(1, 10)
        target.addWidget(self.repeats)
        self.run_button = QPushButton("Run checks")
        self.run_button.setObjectName("primary")
        self.run_button.clicked.connect(self.start_run)
        target.addWidget(self.run_button)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_run)
        target.addWidget(self.cancel_button)
        self.edit_controls.extend([self.url, self.repeats, self.run_button])
        layout.addLayout(target)

        demo_row = QHBoxLayout()
        self.demo_button = QPushButton("Start local demo")
        self.demo_button.clicked.connect(self.toggle_demo)
        demo_row.addWidget(self.demo_button)
        self.demo_mode = QComboBox()
        self.demo_mode.addItems(["Healthy", "Server error", "Bad JSON", "Slow responses"])
        self.demo_mode.currentTextChanged.connect(self.change_demo_mode)
        self.demo_mode.setEnabled(False)
        demo_row.addWidget(self.demo_mode)
        demo_note = QLabel("Fault injection affects only the built-in localhost demo.")
        demo_note.setObjectName("muted")
        demo_row.addWidget(demo_note, 1)
        layout.addLayout(demo_row)
        self.edit_controls.extend([self.demo_button, self.demo_mode])

        self.summary = QLabel("Ready · choose a suite or start the local demo")
        self.summary.setObjectName("summary")
        layout.addWidget(self.summary)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        self.tabs = QTabWidget()
        checks_page = QWidget()
        checks_layout = QVBoxLayout(checks_page)
        self.checks = make_table(
            ["Enabled", "Check", "Method", "Path", "HTTP", "Budget", "JSON path"]
        )
        self.checks.cellDoubleClicked.connect(self.edit_check)
        checks_layout.addWidget(self.checks)
        check_buttons = QHBoxLayout()
        for text, action in [
            ("Add check", self.add_check),
            ("Edit selected", self.edit_check),
            ("Remove selected", self.remove_check),
        ]:
            button = QPushButton(text)
            button.clicked.connect(action)
            check_buttons.addWidget(button)
            self.edit_controls.append(button)
        check_buttons.addStretch()
        checks_layout.addLayout(check_buttons)
        self.tabs.addTab(checks_page, "Checks")
        self.results = make_table(["Round", "Check", "Outcome", "HTTP", "ms", "Reason"])
        self.tabs.addTab(self.results, "Results")
        self.history = make_table(["Run", "Started (UTC)", "Host", "PASS", "Other", "Cancelled"])
        self.history.cellDoubleClicked.connect(self.open_history)
        self.tabs.addTab(self.history, "History · double-click to open")
        layout.addWidget(self.tabs, 1)
        bottom = QHBoxLayout()
        self.compare_label = QLabel(
            "Run twice to compare results against a matching configuration."
        )
        self.compare_label.setWordWrap(True)
        bottom.addWidget(self.compare_label, 1)
        self.report_button = QPushButton("Save HTML report")
        self.report_button.setEnabled(False)
        self.report_button.clicked.connect(self.export_report)
        bottom.addWidget(self.report_button)
        layout.addLayout(bottom)
        self.statusBar().showMessage("Local data: " + str(store.path))
        self.reload_suites()
        if start_demo:
            self.toggle_demo()

    def reload_suites(self, selected=None):
        self.suites = self.store.suites()
        self.suite_choice.blockSignals(True)
        self.suite_choice.clear()
        for suite in self.suites:
            self.suite_choice.addItem(suite.name, suite.id)
        if selected:
            index = self.suite_choice.findData(selected)
            self.suite_choice.setCurrentIndex(max(index, 0))
        self.suite_choice.blockSignals(False)
        self.select_suite()

    @property
    def suite(self):
        return self.suites[self.suite_choice.currentIndex()]

    def select_suite(self, *_):
        if not self.suites:
            return
        self.checks.setRowCount(len(self.suite.checks))
        for index, check in enumerate(self.suite.checks):
            put_row(
                self.checks,
                index,
                [
                    "Yes" if check.enabled else "No",
                    check.name,
                    check.method,
                    urlsplit(check.path).path,
                    check.expected_status,
                    f"{check.max_ms} ms",
                    check.json_path or "—",
                ],
            )
        self.current_run = self.current_run_id = None
        self.results.setRowCount(0)
        self.report_button.setEnabled(False)
        self.summary.setText("Ready · " + self.suite.name)
        self.compare_label.setText("Run twice to compare results against a matching configuration.")
        self.load_history()

    def save_suite(self):
        try:
            self.store.save_suite(self.suite)
        except (ValueError, sqlite3.Error):
            QMessageBox.warning(self, "Not saved", "Could not save suite. Check local data access.")
            self.reload_suites(self.suite.id)
            return False
        self.select_suite()
        return True

    def new_suite(self):
        name, accepted = QInputDialog.getText(self, "New suite", "Suite name")
        if accepted and name.strip():
            suite = Suite(name.strip(), [Check("Health check")])
            try:
                self.store.save_suite(suite)
                self.reload_suites(suite.id)
            except (ValueError, sqlite3.Error):
                QMessageBox.warning(self, "Not saved", "Could not create suite.")

    def add_check(self):
        if len(self.suite.checks) >= 30:
            QMessageBox.information(self, "Suite limit", "Use at most 30 checks per suite.")
            return
        dialog = CheckDialog(parent=self)
        if dialog.exec():
            self.suite.checks.append(dialog.value)
            self.save_suite()

    def edit_check(self, *_):
        if self.worker:
            return
        index = self.checks.currentRow()
        if index < 0:
            return
        dialog = CheckDialog(self.suite.checks[index], self)
        if dialog.exec():
            self.suite.checks[index] = dialog.value
            self.save_suite()

    def remove_check(self):
        index = self.checks.currentRow()
        if index < 0 or len(self.suite.checks) <= 1:
            return
        if (
            QMessageBox.question(self, "Remove check", "Remove the selected check from this suite?")
            == QMessageBox.Yes
        ):
            self.suite.checks.pop(index)
            self.save_suite()

    def import_suite(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Import suite", "", "JSON (*.json)")
        if not filename:
            return
        try:
            path = Path(filename)
            if path.stat().st_size > 1_000_000:
                raise ValueError("Too large")
            suite = Suite.from_json(path.read_text(encoding="utf-8"))
            suite.id = new_id()  # Imports never overwrite a saved suite, even with the same ID.
            self.store.save_suite(suite)
            self.reload_suites(suite.id)
        except (ValueError, OSError, sqlite3.Error):
            QMessageBox.warning(
                self, "Import failed", "Invalid suite or local storage unavailable."
            )

    def export_suite(self):
        filename, _ = QFileDialog.getSaveFileName(
            self, "Export suite (may contain private data)", "suite.json", "JSON (*.json)"
        )
        if filename:
            self.write_file(filename, self.suite.to_json())

    def write_file(self, filename, text):
        try:
            with Path(filename).open("x", encoding="utf-8") as file:
                file.write(text)
            self.statusBar().showMessage("Saved: " + filename)
        except FileExistsError:
            QMessageBox.warning(
                self, "Not overwritten", "Choose a new filename. Existing files are not replaced."
            )
        except OSError:
            QMessageBox.warning(self, "Save failed", "Could not write the selected file.")

    def toggle_demo(self):
        if self.demo:
            self.demo.stop()
            self.demo = None
            self.demo_button.setText("Start local demo")
            self.demo_mode.setEnabled(False)
        else:
            try:
                self.demo = DemoServer().start()
            except OSError:
                QMessageBox.warning(self, "Demo unavailable", "Could not bind a localhost port.")
                return
            self.url.setText(self.demo.url)
            self.demo.set_mode(self.demo_mode.currentText())
            self.demo_button.setText("Stop local demo")
            self.demo_mode.setEnabled(True)

    def change_demo_mode(self, mode):
        if self.demo:
            self.demo.set_mode(mode)

    def start_run(self):
        if self.worker:
            return
        try:
            url = validate_base_url(self.url.text().strip())
            snapshot = Suite.from_json(self.suite.to_json())
        except ValueError:
            QMessageBox.warning(self, "Invalid run", "Check the base URL and suite configuration.")
            return
        if not any(c.enabled for c in snapshot.checks):
            QMessageBox.information(self, "Nothing to run", "Enable at least one check.")
            return
        if not self.demo or url != self.demo.url:
            message = (
                "Requests will be sent to this service. "
                "Only test systems you own or have permission to test."
            )
            if any(c.enabled and c.method == "POST" for c in snapshot.checks):
                message += "\nThis suite includes POST requests that may change server data."
            if QMessageBox.question(self, "Confirm target", message) != QMessageBox.Yes:
                return
        self.results.setRowCount(0)
        self.current_run = self.current_run_id = None
        self.report_button.setEnabled(False)
        self.progress.setRange(0, sum(c.enabled for c in snapshot.checks) * self.repeats.value())
        self.progress.setValue(0)
        self.summary.setText("Running · " + snapshot.name)
        self.tabs.setCurrentIndex(1)
        for control in self.edit_controls:
            control.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.history.setEnabled(False)
        self.worker = RunThread(snapshot, url, self.repeats.value(), self)
        self.worker.result_ready.connect(self.on_result)
        self.worker.completed.connect(self.on_completed)
        self.worker.failed.connect(self.on_failed)
        self.worker.finished.connect(self.thread_done)
        self.worker.start()

    def cancel_run(self):
        if self.worker:
            self.worker.cancel.set()
            self.cancel_button.setEnabled(False)
            self.summary.setText("Cancelling · waiting for current request cleanup")

    @Slot(object)
    def on_result(self, result):
        row = self.results.rowCount()
        self.results.insertRow(row)
        put_row(
            self.results,
            row,
            [
                result["iteration"],
                result["name"],
                result["outcome"],
                result["status"] or "—",
                result["elapsed_ms"],
                result["reason"],
            ],
        )
        self.progress.setValue(row + 1)

    @Slot(object)
    def on_completed(self, run):
        try:
            self.current_run_id = self.store.save_run(self.worker.suite, run)
        except sqlite3.Error:
            self.statusBar().showMessage(
                "Run finished but history could not be saved. Export the report."
            )
            self.current_run_id = None
        self.display_run(run, self.current_run_id)
        self.load_history()

    @Slot(str)
    def on_failed(self, message):
        self.summary.setText(message)

    @Slot()
    def thread_done(self):
        worker = self.worker
        self.worker = None
        worker.deleteLater()
        for control in self.edit_controls:
            control.setEnabled(True)
        self.demo_mode.setEnabled(self.demo is not None)
        self.cancel_button.setEnabled(False)
        self.history.setEnabled(True)
        if self.closing:
            self.close()

    def load_history(self):
        self.history_runs = self.store.history(self.suite.id)
        self.history.setRowCount(len(self.history_runs))
        for index, run in enumerate(self.history_runs):
            counts = totals(run)
            put_row(
                self.history,
                index,
                [
                    run["id"],
                    run["started_at"][:19],
                    run["base_url"],
                    counts["PASS"],
                    len(run["results"]) - counts["PASS"],
                    "Yes" if run["cancelled"] else "No",
                ],
            )

    def display_run(self, run, run_id):
        self.current_run, self.current_run_id = run, run_id
        counts = Counter(r["outcome"] for r in run["results"])
        self.summary.setText(
            f"PASS {counts['PASS']}   FAIL {counts['FAIL']}   ERROR {counts['ERROR']}   "
            f"CANCELLED {counts['CANCELLED']}   · {len(run['results'])}/{run['planned']} attempted"
            + (" · Run cancelled" if run["cancelled"] else "")
        )
        previous = self.store.previous(self.suite, run_id, run["base_url"]) if run_id else None
        self.compare_label.setText(comparison(run, previous))
        self.report_button.setEnabled(True)

    def open_history(self, *_):
        index = self.history.currentRow()
        if index < 0 or self.worker:
            return
        run = self.history_runs[index]
        self.results.setRowCount(0)
        self.progress.setRange(0, max(run["planned"], 1))
        for result in run["results"]:
            self.on_result(result)
        self.display_run(run, run["id"])
        self.tabs.setCurrentIndex(1)

    def export_report(self):
        if not self.current_run:
            return
        filename, _ = QFileDialog.getSaveFileName(
            self, "Save private HTML report", "benchdesk-report.html", "HTML (*.html)"
        )
        if filename:
            previous = (
                self.store.previous(self.suite, self.current_run_id, self.current_run["base_url"])
                if self.current_run_id
                else None
            )
            self.write_file(filename, render_html(self.current_run, previous))

    def closeEvent(self, event):
        if self.worker:
            self.closing = True
            self.cancel_run()
            event.ignore()
            return
        if self.demo:
            self.demo.stop()
            self.demo = None
        event.accept()
