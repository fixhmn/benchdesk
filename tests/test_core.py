import asyncio
import json
import threading
from dataclasses import replace

import httpx
import pytest

from benchdesk.demo import DemoServer
from benchdesk.models import Check, Suite, demo_suite, validate_base_url
from benchdesk.report import comparison, render_html
from benchdesk.runner import MAX_RESPONSE, run_suite
from benchdesk.storage import Store


def run(check, handler, **kwargs):
    return asyncio.run(
        run_suite(
            Suite("Test suite", [check]),
            "http://test",
            transport=httpx.MockTransport(handler),
            **kwargs,
        )
    )


@pytest.mark.parametrize(
    "change",
    [
        {"path": "https://evil.test/"},
        {"path": "//evil.test/"},
        {"path": "/../secret"},
        {"path": "/%2e%2e/secret"},
        {"path": "/x\\y"},
        {"path": "/x#fragment"},
        {"method": "DELETE"},
        {"timeout_s": 0},
        {"timeout_s": 31},
        {"max_ms": 0},
        {"expected_status": True},
        {"enabled": "yes"},
        {"name": ""},
        {"headers": {"Authorization": "Bearer secret"}},
        {"headers": {"Cookie": "secret"}},
        {"headers": {"Host": "evil.test"}},
        {"headers": {"X-Test": "x\ny"}},
        {"headers": {"X-Test": "env:"}},
        {"json_path": "items[0]"},
        {"body": "x" * 32769},
    ],
)
def test_invalid_checks(change):
    with pytest.raises(ValueError):
        replace(Check("Health"), **change).validate()


@pytest.mark.parametrize(
    "url",
    [
        "file:///a",
        "http://u:p@localhost",
        "http://localhost/a",
        "http://localhost?q=x",
        "http://localhost:wrong",
        "http://localhost#x",
    ],
)
def test_invalid_origins(url):
    with pytest.raises(ValueError):
        validate_base_url(url)


def test_suite_serialization_and_validation():
    suite = demo_suite()
    assert Suite.from_json(suite.to_json()).to_json() == suite.to_json()
    with pytest.raises(ValueError):
        Suite.from_json('{"version": 99}')
    with pytest.raises(ValueError):
        Suite.from_json("[]")
    with pytest.raises(ValueError):
        Suite("Empty", []).validate()
    with pytest.raises(ValueError):
        Suite("Dup", [suite.checks[0], suite.checks[0]]).validate()


def test_status_json_post_and_no_sensitive_results(monkeypatch):
    monkeypatch.setenv("BENCHDESK_TEST_TOKEN", "secret-value")
    check = Check(
        "Echo",
        "/echo?token=private",
        method="POST",
        expected_status=201,
        headers={"Authorization": "env:BENCHDESK_TEST_TOKEN"},
        body='{"secret":"body"}',
        json_path="nested.0.ok",
        expected_value=True,
    )

    def handler(request):
        assert request.headers["Authorization"] == "secret-value"
        assert request.content == b'{"secret":"body"}'
        return httpx.Response(201, json={"nested": [{"ok": True}], "secret": "response"})

    report = run(check, handler)
    assert report["results"][0]["outcome"] == "PASS"
    serialized = json.dumps(report)
    for secret in ("secret-value", "private", '"body"', '"response"'):
        assert secret not in serialized


@pytest.mark.parametrize(
    "response,check,reason",
    [
        (httpx.Response(500), Check("Health"), "Expected HTTP"),
        (
            httpx.Response(200, content=b"not-json"),
            Check("JSON", json_path="ok", expected_value=True),
            "Invalid JSON",
        ),
        (
            httpx.Response(200, json={"ok": 1}),
            Check("JSON", json_path="ok", expected_value=True),
            "did not match",
        ),
        (
            httpx.Response(200, json={}),
            Check("JSON", json_path="absent", expected_value=True),
            "not found",
        ),
        (
            httpx.Response(302, headers={"Location": "https://evil.test"}),
            Check("Redirect"),
            "Expected HTTP",
        ),
    ],
)
def test_assertion_failures(response, check, reason):
    result = run(check, lambda request: response)["results"][0]
    assert result["outcome"] == "FAIL" and reason in result["reason"]


def test_network_failure_and_missing_environment(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("raw-secret", request=request)

    result = run(Check("Health"), handler)["results"][0]
    assert result["outcome"] == "ERROR" and "raw-secret" not in result["reason"]
    monkeypatch.delenv("BENCHDESK_UNSET", raising=False)
    check = Check("Health", headers={"Authorization": "env:BENCHDESK_UNSET"})
    result = run(check, lambda request: httpx.Response(200))["results"][0]
    assert result["outcome"] == "ERROR" and "missing" in result["reason"]


def test_size_limit():
    result = run(
        Check("Large"), lambda request: httpx.Response(200, content=b"x" * (MAX_RESPONSE + 1))
    )["results"][0]
    assert result["outcome"] == "ERROR" and "128 KiB" in result["reason"]


def test_deadline_and_latency_budget():
    async def handler(request):
        await asyncio.sleep(0.2)
        return httpx.Response(200)

    assert (
        run(Check("Timeout", timeout_s=0.1), handler)["results"][0]["reason"] == "Request timed out"
    )
    result = run(Check("Budget", max_ms=1), handler)["results"][0]
    assert result["outcome"] == "FAIL" and "budget" in result["reason"]


def test_cancel_in_flight():
    async def scenario():
        cancel = threading.Event()

        async def handler(request):
            cancel.set()
            await asyncio.sleep(10)

        return await run_suite(
            Suite("Cancel", [Check("Health"), Check("Next")]),
            "http://test",
            cancel=cancel,
            transport=httpx.MockTransport(handler),
        )

    report = asyncio.run(scenario())
    assert report["cancelled"] and len(report["results"]) == 1
    assert report["results"][0]["outcome"] == "CANCELLED"


def test_repeats_disabled_and_precancelled():
    suite = Suite("Repeat", [Check("Yes"), Check("No", enabled=False)])
    report = asyncio.run(
        run_suite(
            suite,
            "http://test",
            repeats=3,
            transport=httpx.MockTransport(lambda r: httpx.Response(200)),
        )
    )
    assert [r["iteration"] for r in report["results"]] == [1, 2, 3]
    assert report["planned"] == 3
    cancel = threading.Event()
    cancel.set()
    report = asyncio.run(run_suite(suite, "http://test", cancel=cancel))
    assert report["cancelled"] and not report["results"]
    with pytest.raises(ValueError):
        asyncio.run(run_suite(suite, "http://test", repeats=11))


def test_history_comparison_is_host_and_configuration_specific(tmp_path):
    store = Store(tmp_path / "history.db")
    suite = store.suites()[0]
    report = asyncio.run(
        run_suite(
            suite,
            "http://test",
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"status": "ok"})),
        )
    )
    first = store.save_run(suite, report)
    second = store.save_run(suite, report)
    assert store.previous(suite, second, "http://test") is not None
    assert store.previous(suite, first, "http://test") is None
    assert store.previous(suite, second, "http://other") is None
    suite.checks[0].name = "Changed"
    third = store.save_run(suite, report)
    assert store.previous(suite, third, "http://test") is None
    # Viewing older history after editing still compares its original configuration.
    assert store.previous(suite, second, "http://test") is not None
    assert len(store.history(suite.id)) == 3
    store.save_suite(suite)
    assert store.suites()[0].checks[0].name == "Changed"


def test_report_escaping_and_comparison():
    check = Check("<script>bad</script>")
    previous = run(check, lambda r: httpx.Response(200))
    current = run(check, lambda r: httpx.Response(500))
    assert "1 regressions" in comparison(current, previous)
    html = render_html(current, previous)
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "default-src 'none'" in html


def test_real_local_demo():
    server = DemoServer().start()
    try:
        healthy = asyncio.run(run_suite(demo_suite(), server.url))
        assert all(r["outcome"] == "PASS" for r in healthy["results"])
        server.set_mode("Server error")
        failed = asyncio.run(run_suite(demo_suite(), server.url))
        assert failed["results"][0]["outcome"] == "FAIL"
        server.set_mode("Bad JSON")
        failed = asyncio.run(run_suite(demo_suite(), server.url))
        assert "Invalid JSON" in failed["results"][0]["reason"]
    finally:
        server.stop()
