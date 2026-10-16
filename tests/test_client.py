"""Public client behaviour, HTTP failures and preservation of API payloads."""

import json
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest.mock import Mock

import pytest
import requests
import responses
from responses.matchers import query_param_matcher

from bondbyisin import (
    APIError,
    AuthenticationError,
    Client,
    InvalidResponseError,
    NotFoundError,
    RateLimitError,
    RequestTimeoutError,
    TransportError,
    __version__,
)

BASE = "https://bondbyisin.com/v1"


@responses.activate
def test_exact_public_example_and_response_preservation():
    payload = {
        "results": [{"id": "68389XBU8", "coupon": "Floating", "price": None, "spread": 0}],
        "next_page": 2,
        "observation": {"date": "2026-10-14", "source": "issuer"},
    }
    responses.get(
        BASE + "/bonds/search", json=payload, match=[query_param_matcher({"q": "oracle"})]
    )
    with Client() as client:
        assert client.search("oracle") == payload
    request = responses.calls[0].request
    assert "X-API-Key" not in request.headers
    assert request.headers["User-Agent"] == f"bondbyisin/{__version__}"


@pytest.mark.parametrize(
    "method,args,kwargs",
    [
        ("search", ("oracle",), {}),
        ("bond", ("68389XBU8",), {}),
        ("history", ("68389XBU8",), {}),
        ("cashflows", ("68389XBU8",), {}),
        ("zspread", ("68389XBU8",), {}),
        ("swap_zspread", ("68389XBU8",), {}),
        ("sovereign_curve", ("India",), {}),
        ("swap_curves", ("USD",), {}),
    ],
)
@responses.activate
def test_key_is_forwarded_on_every_kind_of_request(method, args, kwargs):
    import re

    responses.get(re.compile(r"https://bondbyisin\.com/v1/.*"), json={"ok": True})
    with Client(api_key="test-key-for-unit-tests") as client:
        assert getattr(client, method)(*args, **kwargs) == {"ok": True}
        assert "test-key-for-unit-tests" not in repr(client)
    request = responses.calls[0].request
    assert request.headers["X-API-Key"] == "test-key-for-unit-tests"
    assert "test-key-for-unit-tests" not in request.url


@responses.activate
def test_environment_precedence_and_explicit_anonymous(monkeypatch):
    responses.get(BASE + "/etfs", json={})
    monkeypatch.setenv("BOND_API_KEY", "preferred-test-key")
    monkeypatch.setenv("BONDBYISIN_API_KEY", "fallback-test-key")
    for kwargs in ({}, {"api_key": "explicit-test-key"}, {"api_key": ""}):
        with Client(**kwargs) as client:
            client.etfs()
    assert [c.request.headers.get("X-API-Key") for c in responses.calls] == [
        "preferred-test-key",
        "explicit-test-key",
        None,
    ]


@responses.activate
def test_environment_alias(monkeypatch):
    responses.get(BASE + "/etfs", json={})
    monkeypatch.setenv("BONDBYISIN_API_KEY", "fallback-test-key")
    with Client() as client:
        client.etfs()
    assert responses.calls[0].request.headers["X-API-Key"] == "fallback-test-key"


@pytest.mark.parametrize(
    "status,error",
    [
        (401, AuthenticationError),
        (402, AuthenticationError),
        (403, AuthenticationError),
        (404, NotFoundError),
        (400, APIError),
    ],
)
@responses.activate
def test_non_retryable_http_errors(status, error):
    responses.get(
        BASE + "/bond/68389XBU8",
        status=status,
        json={"error": "test rejection"},
        headers={"X-Request-ID": "request-test"},
    )
    with Client() as client, pytest.raises(error) as caught:
        client.bond("68389XBU8")
    assert len(responses.calls) == 1
    assert caught.value.status_code == status
    assert caught.value.path == "/v1/bond/68389XBU8"
    assert caught.value.request_id == "request-test"


@responses.activate
def test_error_does_not_echo_a_key():
    responses.get(BASE + "/etfs", status=401, json={"error": "invalid sensitive-test-key"})
    with (
        Client(api_key="sensitive-test-key") as client,
        pytest.raises(AuthenticationError) as caught,
    ):
        client.etfs()
    assert "sensitive-test-key" not in str(caught.value)


@responses.activate
def test_retry_after_then_success(monkeypatch):
    sleep = Mock()
    monkeypatch.setattr("bondbyisin.client.time.sleep", sleep)
    responses.get(BASE + "/etfs", status=429, json={"error": "busy"}, headers={"Retry-After": "2"})
    responses.get(BASE + "/etfs", json={"etfs": []})
    with Client() as client:
        assert client.etfs() == {"etfs": []}
    sleep.assert_called_once_with(2.0)


@responses.activate
def test_long_retry_after_is_not_shortened(monkeypatch):
    sleep = Mock()
    monkeypatch.setattr("bondbyisin.client.time.sleep", sleep)
    responses.get(
        BASE + "/etfs", status=429, json={"error": "wait"}, headers={"Retry-After": "120"}
    )
    with Client() as client, pytest.raises(RateLimitError) as caught:
        client.etfs()
    assert caught.value.retry_after == 120
    assert len(responses.calls) == 1
    sleep.assert_not_called()


@responses.activate
def test_http_date_retry_after():
    later = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=120), usegmt=True)
    responses.get(BASE + "/etfs", status=429, headers={"Retry-After": later}, json={})
    with Client() as client, pytest.raises(RateLimitError) as caught:
        client.etfs()
    assert 115 <= caught.value.retry_after <= 120


@pytest.mark.parametrize("header", [None, "invalid", "nan", "inf"])
@responses.activate
def test_retries_are_bounded_and_backoff_is_applied(monkeypatch, header):
    sleep = Mock()
    monkeypatch.setattr("bondbyisin.client.time.sleep", sleep)
    responses.get(
        BASE + "/etfs",
        status=503,
        json={"error": "unavailable"},
        headers={"Retry-After": header} if header else {},
    )
    with Client() as client, pytest.raises(APIError):
        client.etfs()
    assert len(responses.calls) == 3
    assert [call.args[0] for call in sleep.call_args_list] == [0.5, 1.0]


@responses.activate
def test_retries_can_be_disabled():
    responses.get(BASE + "/etfs", status=503, json={})
    with Client(max_retries=0) as client, pytest.raises(APIError):
        client.etfs()
    assert len(responses.calls) == 1


@pytest.mark.parametrize(
    "problem,error,attempts",
    [
        (requests.exceptions.Timeout("private-context"), RequestTimeoutError, 3),
        (requests.exceptions.ConnectionError("private-context"), TransportError, 3),
        (requests.exceptions.SSLError("private-context"), TransportError, 1),
    ],
)
@responses.activate
def test_transport_failures_are_clear_and_do_not_expose_requests(problem, error, attempts):
    responses.get(BASE + "/etfs", body=problem)
    with Client() as client, pytest.raises(error) as caught:
        client.etfs()
    assert "private-context" not in str(caught.value)
    assert len(responses.calls) == attempts


@pytest.mark.parametrize("body", ["<html>maintenance</html>", "null", "[]", "123"])
@responses.activate
def test_invalid_success_response_is_not_an_empty_dataset(body):
    responses.get(BASE + "/etfs", body=body, status=200)
    with Client() as client, pytest.raises(InvalidResponseError):
        client.etfs()


@responses.activate
def test_api_error_returned_with_200_is_surfaced():
    responses.get(BASE + "/etfs", json={"error": "unavailable"})
    with Client() as client, pytest.raises(APIError):
        client.etfs()


@responses.activate
def test_unavailable_observation_remains_a_successful_response():
    payload = {"swap_zspread": {"status": "unavailable", "value_bp": None, "reason": "unsupported"}}
    responses.get(BASE + "/bond/68389XBU8/swap-zspread", json=payload)
    with Client() as client:
        assert client.swap_zspread("68389XBU8") == payload


@responses.activate
def test_no_credentials_forwarded_on_redirect():
    responses.get(BASE + "/etfs", status=302, headers={"Location": "https://example.com/collect"})
    with Client(api_key="test-key") as client, pytest.raises(APIError):
        client.etfs()
    assert len(responses.calls) == 1


@pytest.mark.parametrize(
    "path",
    [
        "https://example.com/v1",
        "//example.com/v1",
        "../account",
        "/v1/%2e%2e/account",
        "%252e%252e/account",
        "etfs?key=secret",
        "etfs#fragment",
        "a\\b",
    ],
)
def test_get_rejects_unsafe_paths(path):
    with Client() as client, pytest.raises(ValueError):
        client.get(path)


@pytest.mark.parametrize("name", ["key", "api_key", "Authorization", "X-API-Key", "token"])
def test_get_rejects_credentials_in_query(name):
    with Client() as client, pytest.raises(ValueError):
        client.get("etfs", params={name: "secret"})


@pytest.mark.parametrize("path", ["etfs", "/etfs", "/v1/etfs", "v1/etfs"])
@responses.activate
def test_relative_path_variants(path):
    responses.get(BASE + "/etfs", json={"etfs": []})
    with Client() as client:
        assert client.get(path) == {"etfs": []}


@pytest.mark.parametrize(
    "base",
    [
        "http://example.com/v1",
        "https://user:pass@example.com/v1",
        "https://example.com/v1?token=x",
        "https://example.com/api",
        "//example.com/v1",
    ],
)
def test_invalid_api_origins(base):
    with pytest.raises(ValueError):
        Client(base_url=base)


@pytest.mark.parametrize(
    "options",
    [
        {"timeout": 0},
        {"timeout": (1,)},
        {"timeout": float("nan")},
        {"max_retries": -1},
        {"max_retries": True},
        {"max_retries": 11},
        {"backoff_factor": -1},
        {"max_retry_delay": -1},
        {"api_key": "line\nbreak"},
    ],
)
def test_invalid_client_options(options):
    with pytest.raises(ValueError):
        Client(**options)


def test_session_ownership_and_closed_client(monkeypatch):
    owned = Mock(spec=requests.Session)
    caller_session = Mock(spec=requests.Session)
    monkeypatch.setattr("bondbyisin.client.requests.Session", lambda: owned)
    with Client() as client:
        pass
    client.close()
    owned.close.assert_called_once()
    with pytest.raises(RuntimeError):
        client.etfs()
    with Client(session=caller_session):
        pass
    caller_session.close.assert_not_called()


@responses.activate
def test_timeout_is_forwarded():
    session = requests.Session()
    original = session.get
    session.get = Mock(wraps=original)
    responses.get(BASE + "/etfs", json={})
    with Client(timeout=(3, 45), session=session) as client:
        client.etfs()
    assert session.get.call_args.kwargs["timeout"] == (3.0, 45.0)
    session.close()


@responses.activate
def test_history_is_never_truncated():
    payload = {"points": [{"date": "2026-10-14", "price": None} for _ in range(1000)]}
    responses.get(
        BASE + "/bond/68389XBU8/history", body=json.dumps(payload), content_type="application/json"
    )
    with Client() as client:
        assert client.history("68389XBU8") == payload
