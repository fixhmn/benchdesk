import json
import re
from dataclasses import asdict, dataclass, field
from urllib.parse import unquote, urlsplit
from uuid import uuid4


def new_id():
    return uuid4().hex


@dataclass
class Check:
    name: str
    path: str = "/health"
    method: str = "GET"
    expected_status: int = 200
    json_path: str = ""
    expected_value: object = None
    max_ms: int = 2000
    timeout_s: float = 5
    headers: dict = field(default_factory=dict)
    body: str = ""
    enabled: bool = True
    id: str = field(default_factory=new_id)

    def validate(self):
        if not isinstance(self.name, str) or not 1 <= len(self.name.strip()) <= 100:
            raise ValueError("Check names need 1–100 characters")
        if not isinstance(self.id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", self.id):
            raise ValueError("Invalid check ID")
        if not isinstance(self.path, str) or len(self.path) > 2000:
            raise ValueError("Invalid request path")
        parts = urlsplit(self.path)
        if (
            not self.path.startswith("/")
            or self.path.startswith("//")
            or parts.scheme
            or parts.netloc
            or parts.fragment
            or "\\" in self.path
            or any(ord(c) < 32 for c in self.path)
            or any(p in {".", ".."} for p in unquote(parts.path).split("/"))
        ):
            raise ValueError("Use an absolute path on the selected host, such as /health")
        if self.method not in {"GET", "POST"}:
            raise ValueError("Only GET and POST are supported")
        if type(self.expected_status) is not int or not 100 <= self.expected_status <= 599:
            raise ValueError("Expected status must be 100–599")
        if type(self.max_ms) is not int or not 1 <= self.max_ms <= 30000:
            raise ValueError("Response limit must be 1–30000 ms")
        if type(self.timeout_s) not in {float, int} or not 0.1 <= self.timeout_s <= 30:
            raise ValueError("Timeout must be 0.1–30 seconds")
        if not isinstance(self.json_path, str) or len(self.json_path) > 200:
            raise ValueError("JSON path is too long")
        if self.json_path and not re.fullmatch(
            r"[a-zA-Z0-9_-]+(?:\.[a-zA-Z0-9_-]+)*", self.json_path
        ):
            raise ValueError("JSON paths use dot-separated object keys or array indexes")
        if type(self.enabled) is not bool:
            raise ValueError("Enabled must be true or false")
        if not isinstance(self.body, str) or len(self.body.encode()) > 32768:
            raise ValueError("Request body is limited to 32 KiB")
        if not isinstance(self.headers, dict) or len(self.headers) > 20:
            raise ValueError("Use at most 20 headers")
        seen = set()
        for key, value in self.headers.items():
            if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,80}", key):
                raise ValueError("Invalid header name")
            if not isinstance(value, str) or len(value) > 2000 or "\n" in value or "\r" in value:
                raise ValueError("Invalid header value")
            if key.lower() in seen:
                raise ValueError("Duplicate header names")
            seen.add(key.lower())
            if key.lower() in {"host", "content-length", "transfer-encoding"}:
                raise ValueError("Host and transfer headers are managed by the HTTP client")
            if value.startswith("env:") and not re.fullmatch(r"env:[A-Za-z_][A-Za-z0-9_]*", value):
                raise ValueError("Environment references look like env:BENCHDESK_TOKEN")
            if any(
                word in key.lower()
                for word in ("authorization", "cookie", "token", "api-key", "apikey")
            ) and not value.startswith("env:"):
                raise ValueError("Credential headers must use an env:VARIABLE reference")
        json.dumps(self.expected_value, allow_nan=False)
        return self


@dataclass
class Suite:
    name: str
    checks: list[Check]
    id: str = field(default_factory=new_id)

    def validate(self):
        if not isinstance(self.name, str) or not 1 <= len(self.name.strip()) <= 100:
            raise ValueError("Suite names need 1–100 characters")
        if not isinstance(self.id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", self.id):
            raise ValueError("Invalid suite ID")
        if not 1 <= len(self.checks) <= 30:
            raise ValueError("A suite needs 1–30 checks")
        ids = set()
        for check in self.checks:
            check.validate()
            if check.id in ids:
                raise ValueError("Duplicate check IDs")
            ids.add(check.id)
        return self

    def to_json(self):
        return json.dumps({"version": 1, **asdict(self)}, indent=2, allow_nan=False)

    @classmethod
    def from_json(cls, text):
        if len(text.encode()) > 1_000_000:
            raise ValueError("Suite file exceeds 1 MB")
        try:
            value = json.loads(text)
            if value.pop("version") != 1:
                raise ValueError("Unsupported suite version")
            value["checks"] = [Check(**row) for row in value["checks"]]
            return cls(**value).validate()
        except (TypeError, KeyError, AttributeError, RecursionError, json.JSONDecodeError) as error:
            raise ValueError("Invalid suite file") from error


def validate_base_url(value):
    parts = urlsplit(value)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
        or parts.path not in {"", "/"}
        or any(ord(c) < 33 for c in value)
    ):
        raise ValueError("Base URL must be an HTTP(S) origin, e.g. http://127.0.0.1:8765")
    try:
        parts.port
    except ValueError as error:
        raise ValueError("Invalid port") from error
    return value.rstrip("/")


def demo_suite():
    return Suite(
        "Local demo · service smoke checks",
        [
            Check("Service health", "/health", json_path="status", expected_value="ok"),
            Check(
                "Catalog returns data",
                "/catalog",
                json_path="items.0.name",
                expected_value="Notebook",
            ),
            Check("Response budget", "/slow", max_ms=400),
            Check(
                "Create a test item",
                "/echo",
                method="POST",
                expected_status=201,
                body='{"item":"demo"}',
                headers={"Content-Type": "application/json"},
                json_path="accepted",
                expected_value=True,
            ),
        ],
        id="demo-suite",
    ).validate()
