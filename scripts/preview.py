"""Capture a real demo run for the README without opening a visible window."""

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from benchdesk.gui import Window
from benchdesk.storage import Store

parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, default=Path("docs/screenshots/demo.png"))
args = parser.parse_args()
app = QApplication([])
window = Window(Store(Path("data/preview.db")), start_demo=True)
window.show()
window.start_run()


def finish():
    if window.worker is not None:
        return
    timer.stop()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not window.grab().save(str(args.output)):
        raise RuntimeError("Could not save screenshot")
    window.close()
    app.quit()


timer = QTimer()
timer.timeout.connect(finish)
timer.start(100)
QTimer.singleShot(10000, window.close)
app.exec()
