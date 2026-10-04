import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class DemoServer:
    def __init__(self, port=0):
        self.lock = threading.Lock()
        self.mode = "Healthy"
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, status, value):
                body = value if isinstance(value, bytes) else json.dumps(value).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass

            def do_GET(self):
                with owner.lock:
                    mode = owner.mode
                if mode == "Server error":
                    self.reply(500, {"error": "Injected demo failure"})
                elif mode == "Bad JSON":
                    self.reply(200, b"{not-json")
                else:
                    if mode == "Slow responses" or self.path == "/slow":
                        time.sleep(1.2 if mode == "Slow responses" else 0.05)
                    if self.path == "/health":
                        self.reply(200, {"status": "ok"})
                    elif self.path == "/catalog":
                        self.reply(200, {"items": [{"name": "Notebook", "price": 12}]})
                    elif self.path == "/slow":
                        self.reply(200, {"status": "ok"})
                    else:
                        self.reply(404, {"error": "Not found"})

            def do_POST(self):
                if self.path != "/echo":
                    self.reply(404, {"error": "Not found"})
                    return
                length = int(self.headers.get("Content-Length", "0"))
                if length > 32768:
                    self.reply(413, {"error": "Too large"})
                    return
                self.rfile.read(length)
                self.reply(201, {"accepted": True})

        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server.server_port}"

    def start(self):
        self.thread.start()
        return self

    def set_mode(self, mode):
        if mode not in {"Healthy", "Server error", "Bad JSON", "Slow responses"}:
            raise ValueError("Unknown demo mode")
        with self.lock:
            self.mode = mode

    def stop(self):
        if self.thread.is_alive():
            self.server.shutdown()
            self.thread.join(timeout=2)
        self.server.server_close()
