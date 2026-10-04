import argparse
import asyncio
import json
from pathlib import Path

from benchdesk.demo import DemoServer
from benchdesk.models import Suite, demo_suite
from benchdesk.report import render_html, totals
from benchdesk.runner import run_suite


def main():
    parser = argparse.ArgumentParser(description="BenchDesk desktop service checks")
    parser.add_argument("--demo", action="store_true", help="Start the built-in local demo service")
    parser.add_argument(
        "--smoke-test", action="store_true", help="Run the Qt demo then exit (packaging check)"
    )
    parser.add_argument("--database", type=Path, help="Override local history database location")
    parser.add_argument("--headless", action="store_true", help="Run without a desktop window")
    parser.add_argument("--suite", type=Path, help="Suite JSON file (headless mode)")
    parser.add_argument("--url", default="http://127.0.0.1:8765", help="Target HTTP(S) origin")
    parser.add_argument("--output", type=Path, help="New HTML report file (headless mode)")
    parser.add_argument("--repeat", type=int, default=1, help="Rounds, 1–10")
    args = parser.parse_args()
    if args.headless:
        server = None
        try:
            suite = demo_suite()
            if args.suite:
                if args.suite.stat().st_size > 1_000_000:
                    raise ValueError("Suite exceeds 1 MB")
                suite = Suite.from_json(args.suite.read_text(encoding="utf-8"))
            if args.demo:
                server = DemoServer().start()
            run = asyncio.run(run_suite(suite, server.url if server else args.url, args.repeat))
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                with args.output.open("x", encoding="utf-8") as file:
                    file.write(render_html(run))
            print(json.dumps({"outcomes": totals(run), "attempted": len(run["results"])}))
            return (
                0
                if len(run["results"]) and all(r["outcome"] == "PASS" for r in run["results"])
                else 1
            )
        except (ValueError, OSError):
            parser.exit(
                2,
                "Could not run checks. Verify suite, URL, and output path; "
                "existing files are not overwritten.\n",
            )
        finally:
            if server:
                server.stop()
    else:
        import sqlite3

        from PySide6.QtWidgets import QApplication, QMessageBox

        from benchdesk.gui import Window
        from benchdesk.storage import Store, default_database

        app = QApplication([])
        app.setApplicationName("BenchDesk")
        try:
            window = Window(
                Store(args.database or default_database()), args.demo or args.smoke_test
            )
        except (ValueError, OSError, sqlite3.Error):
            QMessageBox.critical(
                None,
                "BenchDesk could not start",
                "Local database could not be opened. Try --database with a writable path.",
            )
            return 2
        window.show()
        if args.smoke_test:
            from PySide6.QtCore import QTimer

            smoke_expired = False
            app.setQuitOnLastWindowClosed(False)
            window.start_run()

            def finish_smoke():
                if window.worker is not None:
                    return
                smoke_timer.stop()
                success = window.current_run and all(
                    r["outcome"] == "PASS" for r in window.current_run["results"]
                )
                window.close()
                app.exit(2 if smoke_expired else 0 if success else 1)

            smoke_timer = QTimer()
            smoke_timer.timeout.connect(finish_smoke)
            smoke_timer.start(100)

            def smoke_timeout():
                nonlocal smoke_expired
                smoke_expired = True
                window.cancel_run()

            QTimer.singleShot(30000, smoke_timeout)
        return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
