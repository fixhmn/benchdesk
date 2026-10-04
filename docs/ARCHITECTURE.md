# How the app fits together

```text
GUI (main Qt thread)
  ├── suite editor / import / export
  ├── SQLite Store: configuration + finished/partial runs
  └── RunThread → asyncio runner → httpx → selected HTTP service
                      └── per-result signals → GUI table

Built-in DemoServer → localhost only → controlled GET faults
```

The runner has no Qt imports. Tests can run it with `httpx.MockTransport`, and headless mode uses the same assertions as the desktop window. Each run takes a validated copy of the suite; editing controls stay disabled until the worker finishes.

The worker never changes widgets directly. Results and completion cross the Qt thread boundary through signals and slots. A `threading.Event` requests cancellation; the asyncio runner cancels the in-flight HTTP task and closes the client. Window closing waits asynchronously for the thread instead of calling `terminate()`.

Only the main thread writes application SQLite state. Connections are short-lived, writes are committed/rolled back, values are parameterized, and reads are capped in the history UI. The demo service has its own daemon thread and a lock around fault-mode changes. It has no access to the application's database.

Run fingerprints hash the stored suite definition. History comparison looks up the fingerprint stored with the selected run, not the currently edited suite; changing an assertion doesn't make old runs incorrectly comparable. The target origin must also match. Secret environment values are intentionally not part of the fingerprint, so credential changes are not tracked.

There's no ORM, plugin framework, message queue, or dependency-injection container. `models.py` handles validation, `runner.py` does requests/assertions, `storage.py` handles SQL, and `report.py` generates escaped HTML. `gui.py` is the largest file and would be the first one to split if the UI grows.

Design references: [Qt thread/signals example](https://doc.qt.io/qtforpython-6/examples/example_widgets_thread_signals.html) and [HTTPX timeouts](https://www.python-httpx.org/advanced/timeouts/). BenchDesk adds a wall-clock request deadline because per-operation timeouts alone aren't a total-duration limit.
