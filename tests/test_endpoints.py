"""Verify every wrapper's path/parameters, dates, identifiers and pagination."""

from datetime import date, datetime

import pytest
import responses
from responses.matchers import query_param_matcher

from bondbyisin import Client, InvalidResponseError

BASE = "https://bondbyisin.com/v1"
ID = "68389XBU8"


@pytest.mark.parametrize(
    "method,args,kwargs,path,params",
    [
        ("bond", (" 68389xbu8 ",), {}, f"bond/{ID}", {}),
        ("bond", ("US037833BX70",), {}, "bond/US037833BX70", {}),
        ("history", (ID,), {}, f"bond/{ID}/history", {}),
        ("cashflows", (ID,), {}, f"bond/{ID}/cashflows", {}),
        (
            "analytics",
            (ID,),
            {"date": date(2026, 10, 7)},
            f"bond/{ID}/analytics",
            {"date": "2026-10-07"},
        ),
        ("zspread", (ID,), {"date": "2026-10-07"}, f"bond/{ID}/zspread", {"date": "2026-10-07"}),
        ("swap_zspread", (ID,), {}, f"bond/{ID}/swap-zspread", {}),
        (
            "spread_history",
            (ID,),
            {"date": "2026-10-07"},
            f"bond/{ID}/spread-history",
            {"date": "2026-10-07"},
        ),
        (
            "spread_history",
            (ID,),
            {"start": "2026-09-01", "end": "2026-10-07"},
            f"bond/{ID}/spread-history",
            {"start": "2026-09-01", "end": "2026-10-07"},
        ),
        (
            "spread_range",
            (ID,),
            {"start": "2026-09-01"},
            f"bond/{ID}/spread-range",
            {"start": "2026-09-01"},
        ),
        (
            "zspread_range",
            (ID,),
            {"end": "2026-10-07"},
            f"bond/{ID}/zspread/range",
            {"end": "2026-10-07"},
        ),
        ("zspread_history_summary", (ID,), {}, f"bond/{ID}/zspread/history-summary", {}),
        ("curves", (), {"family": "us"}, "curves", {"family": "us"}),
        (
            "curve",
            ("US-CORP-BBB",),
            {"term": 10, "date": "2026-10-07"},
            "curves/US-CORP-BBB",
            {"term": "10", "date": "2026-10-07"},
        ),
        ("sovereign_curve", ("United States",), {}, "curves/sovereign/United%20States", {}),
        ("muni_curve", ("ca",), {}, "curves/muni/CA", {}),
        ("swap_curves", (), {}, "swap-curves", {}),
        (
            "swap_curves",
            ("usd",),
            {"date": "2026-10-07", "curve_type": "zero"},
            "swap-curves",
            {"currency": "USD", "date": "2026-10-07", "type": "zero"},
        ),
        ("sovereign_ratings", (), {}, "sovereign-ratings", {}),
        ("issuer", ("microsoft",), {}, "issuer/microsoft", {}),
        ("auctions", ("US",), {}, "auctions/us", {}),
        ("etfs", (), {}, "etfs", {}),
    ],
)
@responses.activate
def test_endpoint_contracts(method, args, kwargs, path, params):
    responses.get(f"{BASE}/{path}", json={"checked": True}, match=[query_param_matcher(params)])
    with Client(api_key="unit-test-key") as client:
        assert getattr(client, method)(*args, **kwargs) == {"checked": True}
    assert responses.calls[0].request.headers["X-API-Key"] == "unit-test-key"


@responses.activate
def test_search_options_are_explicit():
    params = {
        "q": "oracle",
        "page": "2",
        "limit": "100",
        "sort": "ytm",
        "order": "desc",
        "include_matured": "1",
    }
    responses.get(BASE + "/bonds/search", json={"results": []}, match=[query_param_matcher(params)])
    with Client() as client:
        assert client.search(
            "oracle", page=2, limit=100, sort="ytm", order="desc", include_matured=True
        ) == {"results": []}


@responses.activate
def test_iterator_follows_next_page_and_preserves_rows():
    rows = [{"id": "first", "coupon": "Floating"}, {"id": "second", "yield": None}]
    responses.get(
        BASE + "/bonds/search",
        json={"results": rows[:1], "next_page": 2},
        match=[query_param_matcher({"q": "oracle", "limit": "1"})],
    )
    responses.get(
        BASE + "/bonds/search",
        json={"results": rows[1:], "next_page": None},
        match=[query_param_matcher({"q": "oracle", "limit": "1", "page": "2"})],
    )
    with Client() as client:
        assert list(client.iter_search("oracle", limit=1)) == rows
    assert len(responses.calls) == 2


@responses.activate
def test_iterator_page_cap_and_starting_page():
    responses.get(
        BASE + "/bonds/search",
        json={"results": [{"id": "one"}], "next_page": 4},
        match=[query_param_matcher({"q": "oracle", "page": "3"})],
    )
    with Client() as client:
        assert list(client.iter_search("oracle", page=3, max_pages=1)) == [{"id": "one"}]
    assert len(responses.calls) == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"results": [{"id": "one"}], "next_page": 1},
        {"results": [{"id": "one"}], "next_page": 3},
        {"results": [{"id": "one"}], "next_page": True},
        {"results": [{"id": "one"}], "next_page": "2"},
        {"results": [], "next_page": 2},
        {"results": [{"id": "one"}]},
        {"results": None},
        {"results": ["malformed"]},
        {},
    ],
)
@responses.activate
def test_invalid_pagination_fails_instead_of_looping_or_losing_data(payload):
    responses.get(BASE + "/bonds/search", json=payload)
    with Client() as client, pytest.raises(InvalidResponseError):
        list(client.iter_search("oracle"))


@pytest.mark.parametrize(
    "identifier",
    ["", "123", "../../key", 68389, "68389XBU8?key=x", "68389XBU8/", "ISIN-WITH-SPACES"],
)
def test_invalid_identifiers(identifier):
    with Client() as client, pytest.raises(ValueError):
        client.bond(identifier)


@pytest.mark.parametrize(
    "bad_date", ["20261007", "2026-2-01", "2026-02-30", datetime(2026, 10, 7), 20261007]
)
def test_invalid_dates(bad_date):
    with Client() as client, pytest.raises(ValueError):
        client.zspread(ID, date=bad_date)


@pytest.mark.parametrize(
    "method,args,kwargs",
    [
        ("search", ("",), {}),
        ("search", ("x" * 121,), {}),
        ("search", ("oracle",), {"limit": 101}),
        ("search", ("oracle",), {"limit": 0}),
        ("search", ("oracle",), {"page": 0}),
        ("search", ("oracle",), {"order": "sideways"}),
        ("search", ("oracle",), {"sort": "price", "order": "desc"}),
        ("search", ("oracle",), {"include_matured": "false"}),
        ("spread_history", (ID,), {"date": "2026-10-07", "start": "2026-10-01"}),
        ("spread_range", (ID,), {"start": "2026-10-07", "end": "2026-10-01"}),
        ("curve", ("US-TREASURY",), {"term": -1}),
        ("sovereign_curve", ("../account",), {}),
        ("muni_curve", ("California",), {}),
        ("swap_curves", (), {"date": "2026-10-07"}),
        ("swap_curves", ("dollar",), {}),
        ("issuer", ("Microsoft/extra",), {}),
        ("auctions", ("United States",), {}),
    ],
)
def test_invalid_options(method, args, kwargs):
    with Client() as client, pytest.raises(ValueError):
        getattr(client, method)(*args, **kwargs)


def test_invalid_iterator_options():
    with Client() as client, pytest.raises(ValueError):
        list(client.iter_search("oracle", max_pages=0))
