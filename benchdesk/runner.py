import asyncio
import os
import threading
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx

from benchdesk.models import validate_base_url

MAX_RESPONSE = 128 * 1024


class CheckError(Exception):
    pass


@dataclass
class Result:
    check_id: str
    name: str
    method: str
    path: str
    iteration: int
    outcome: str
    status: int | None
    elapsed_ms: float
    reason: str


def json_lookup(value, path):
    for key in path.split("."):
        if isinstance(value, dict):
            value = value[key]
        elif isinstance(value, list) and key.isdigit():
            value = value[int(key)]
        else:
            raise KeyError(key)
    return value


def resolve_headers(headers):
    result = {}
    for key, value in headers.items():
        if value.startswith("env:"):
            value = os.environ.get(value[4:])
            if not value:
                raise CheckError("A required header environment variable is missing")
        result[key] = value
    return result


async def request_check(client, base_url, check):
    headers = resolve_headers(check.headers)
    async with client.stream(
        check.method,
        base_url + check.path,
        headers=headers,
        content=check.body.encode() if check.method == "POST" else None,
        timeout=check.timeout_s,
    ) as response:
        content = bytearray()
        async for chunk in response.aiter_bytes(chunk_size=8192):
            if len(content) + len(chunk) > MAX_RESPONSE:
                raise CheckError("Response exceeds the 128 KiB limit")
            content.extend(chunk)
        return response.status_code, bytes(content)


async def execute_check(client, base_url, check, iteration, cancel):
    started = time.perf_counter()
    status = None
    reason = "All assertions passed"
    outcome = "PASS"
    task = asyncio.create_task(request_check(client, base_url, check))
    try:
        # A wall-clock deadline complements HTTPX's per-operation timeouts.
        while not task.done():
            if cancel.is_set():
                raise asyncio.CancelledError
            if time.perf_counter() - started >= check.timeout_s:
                raise TimeoutError
            await asyncio.wait({task}, timeout=0.025)
        status, body = await task
        elapsed = (time.perf_counter() - started) * 1000
        if status != check.expected_status:
            outcome, reason = "FAIL", f"Expected HTTP {check.expected_status}; received {status}"
        elif check.json_path:
            import json

            try:
                actual = json_lookup(json.loads(body), check.json_path)
                if type(actual) is not type(check.expected_value) or actual != check.expected_value:
                    outcome, reason = "FAIL", "JSON assertion did not match"
            except (ValueError, KeyError, IndexError, UnicodeDecodeError, RecursionError):
                outcome, reason = "FAIL", "Invalid JSON or JSON path not found"
        if outcome == "PASS" and elapsed > check.max_ms:
            outcome, reason = "FAIL", f"Response exceeded {check.max_ms} ms budget"
    except asyncio.CancelledError:
        outcome, reason = "CANCELLED", "Run cancelled by user"
    except (TimeoutError, httpx.TimeoutException):
        outcome, reason = "ERROR", "Request timed out"
    except httpx.RequestError:
        outcome, reason = "ERROR", "Connection or TLS failure; check service address"
    except CheckError as error:
        outcome, reason = "ERROR", str(error)
    except (ValueError, httpx.InvalidURL):
        outcome, reason = "ERROR", "Request configuration is invalid"
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    return Result(
        check.id,
        check.name,
        check.method,
        urlsplit(check.path).path,
        iteration,
        outcome,
        status,
        round((time.perf_counter() - started) * 1000, 1),
        reason,
    )


async def run_suite(suite, base_url, repeats=1, cancel=None, on_result=None, transport=None):
    suite.validate()
    base_url = validate_base_url(base_url)
    if type(repeats) is not int or not 1 <= repeats <= 10:
        raise ValueError("Repeat count must be 1–10")
    cancel = cancel or threading.Event()
    started = datetime.now(UTC).isoformat()
    results = []
    async with httpx.AsyncClient(
        transport=transport,
        follow_redirects=False,
        trust_env=False,
        limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
    ) as client:
        for iteration in range(1, repeats + 1):
            for check in suite.checks:
                if cancel.is_set():
                    break
                if not check.enabled:
                    continue
                result = await execute_check(client, base_url, check, iteration, cancel)
                results.append(asdict(result))
                if on_result:
                    on_result(asdict(result))
            if cancel.is_set():
                break
    return {
        "suite_id": suite.id,
        "suite_name": suite.name,
        "started_at": started,
        "finished_at": datetime.now(UTC).isoformat(),
        "cancelled": cancel.is_set(),
        "base_url": base_url,
        "results": results,
        "planned": sum(c.enabled for c in suite.checks) * repeats,
    }
