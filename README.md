# bondbyisin

Standalone Python client for [Bond by ISIN](https://bondbyisin.com).
Search bonds by ISIN, CUSIP or issuer, retrieve observations and cash flows,
and read government and swap curves through the site's API.

Python 3.10 or newer. The only runtime dependency is `requests`.

## Install

```bash
python -m pip install bondbyisin
```

For an unpublished source checkout, use `python -m pip install .` instead.

## Quick start

```python
from bondbyisin import Client

with Client() as client:  # Reads BOND_API_KEY from the environment, if set.
    results = client.search("oracle")
    bond = client.bond("68389XBU8")
    history = client.history("68389XBU8")

print(results["results"])
print(bond["bond"])
print(history["points"])
```

These exact requests are public examples listed in the
[API documentation](https://bondbyisin.com/api). Other securities, dates,
filters and subsequent search pages require an active API subscription.
Installing this Python package does not create an account or grant API access.

Get your key from [your account](https://bondbyisin.com/account). Set the
`BOND_API_KEY` environment variable, or supply the key explicitly:

```python
import os
from bondbyisin import Client

with Client(api_key=os.environ["BOND_API_KEY"]) as client:
    for bond in client.iter_search("oracle", limit=100):
        print(bond["id"], bond["name"])

    spread = client.zspread("68389XBU8")
    swap_spread = client.swap_zspread("68389XBU8")
    curve = client.sovereign_curve("India")
    swaps = client.swap_curves("USD")
```

`Client()` checks `BOND_API_KEY` first and `BONDBYISIN_API_KEY` second.
An explicit `api_key` overrides both. `Client(api_key="")` is anonymous even
when an environment key exists. Keys are sent in the `X-API-Key` header.

## Commands

Every method returns the complete API response as a Python dictionary.
The library preserves nested fields, provenance, pagination metadata and
unavailable values. It does not calculate financial metrics, fill gaps,
truncate history, change currencies or combine observations from different dates.

| Method | API path after `/v1` | Options |
| --- | --- | --- |
| `search(query)` | `/bonds/search` | `limit` (1–100), `page`, `sort`, `order`, `include_matured` |
| `iter_search(query)` | `/bonds/search` | Same options; `max_pages` bounds pagination; yields individual rows |
| `bond(identifier)` | `/bond/{id}` | ISIN or CUSIP |
| `history(identifier)` | `/bond/{id}/history` | Complete stored price/yield history |
| `cashflows(identifier)` | `/bond/{id}/cashflows` | Schedule and available valuation fields |
| `analytics(identifier)` | `/bond/{id}/analytics` | `date` |
| `zspread(identifier)` | `/bond/{id}/zspread` | `date` |
| `swap_zspread(identifier)` | `/bond/{id}/swap-zspread` | `date` |
| `spread_history(identifier)` | `/bond/{id}/spread-history` | `date`, or `start` / `end` |
| `spread_range(identifier)` | `/bond/{id}/spread-range` | `start`, `end` |
| `zspread_range(identifier)` | `/bond/{id}/zspread/range` | `start`, `end` |
| `zspread_history_summary(identifier)` | `/bond/{id}/zspread/history-summary` | Coverage metadata |
| `curves()` | `/curves` | `family` |
| `curve(curve_id)` | `/curves/{curve_id}` | `term` in years, `date` |
| `sovereign_curve(country)` | `/curves/sovereign/{country}` | Country name |
| `muni_curve(state)` | `/curves/muni/{state}` | Two-letter US state code |
| `swap_curves(currency)` | `/swap-curves` | `date`, `curve_type` (`yield`, `par`, `zero`, subject to market support); omit currency for catalogue |
| `sovereign_ratings()` | `/sovereign-ratings` | Ratings directory |
| `issuer(slug)` | `/issuer/{slug}` | Issuer slug, e.g. `microsoft` |
| `auctions(country)` | `/auctions/{country}` | API country code, e.g. `us` |
| `etfs()` | `/etfs` | Bond ETF directory |
| `get(path, params=...)` | Any relative JSON API path | Access other documented JSON endpoints |

Search supports the API's combinations `maturity/asc`, `maturity/desc`,
`ytm/asc`, `ytm/desc`, `coupon/desc` and `price/asc`.
Unspecified search options are omitted from the HTTP request. This matters
because only exact documentation examples are anonymous demonstrations.
`search` returns one page, including `next_page`; `iter_search` follows it.

Dates accept `YYYY-MM-DD` strings or `datetime.date` objects. Date arguments
are sent only to endpoints that support them. The price/yield `history`
endpoint returns all stored points and does not expose a date filter.

```python
from datetime import date

with Client() as client:
    dated = client.analytics("037833BX7", date=date(2026, 10, 7))
    period = client.spread_range("68389XCN3", start="2026-09-01", end="2026-10-07")
    treasury = client.get("curves/us")
```

## Values and units

Use each response's observation dates, units, source fields and availability
notes. `None` means the API returned JSON `null`; zero remains zero.
Yield and coupon fields ending in `_percent` or documented as percentages
remain in percent units; spreads ending in `_bp` remain in basis points.
DV01 retains the API's currency-per-100-face-per-basis-point convention.
Floating coupon descriptions remain strings. Government and swap Z-spreads
remain separate measures. A successful response can describe an unavailable
observation: this status and its reason are returned unchanged.

For an optional pandas table, install pandas separately and select the rows
you want. The client does not introduce a pandas dependency:

```python
import pandas as pd

with Client() as client:
    points = client.history("68389XBU8")["points"]
frame = pd.DataFrame(points)
```

## Errors and connections

```python
from bondbyisin import AuthenticationError, Client, RateLimitError

try:
    with Client(timeout=(10, 60), max_retries=2) as client:
        result = client.search("apple", limit=1)
except AuthenticationError:
    print("Set BOND_API_KEY to an active subscription key.")
except RateLimitError as error:
    print("Try again later; suggested wait in seconds:", error.retry_after)
```

All library errors inherit from `BondByISINError`. HTTP errors expose
`status_code`, `path`, `request_id` and `retry_after`. Other exceptions include
`NotFoundError`, `APIError`, `RequestTimeoutError`, `TransportError` and
`InvalidResponseError`. Invalid local arguments raise `ValueError`.

The default timeout is 10 seconds to connect and 60 seconds to read. GET
requests retry at most twice on connection errors, timeouts, HTTP 429 and
HTTP 500/502/503/504. The initial backoff is 0.5 seconds. `Retry-After` is
honoured; if it asks for more than `max_retry_delay` (30 seconds by default),
the client raises the HTTP error immediately so the caller can schedule a
later attempt. Authentication failures and missing records are not retried.
Set `max_retries=0` to disable retries. Redirects are not followed.

Use a context manager or call `close()`. Create one client per thread. For
custom connection configuration, pass a `requests.Session`; the caller
remains responsible for closing that session. HTTPS certificate verification
uses Requests' normal trust configuration. `base_url` defaults to
`https://bondbyisin.com/v1`; alternate origins must use HTTPS, except loopback
addresses used in local tests.

## Development and release

```bash
python -m venv .venv
# Activate the virtual environment for your operating system.
python -m pip install -e '.[dev]'
python -m pytest
python -m ruff check .
python -m build
python -m twine check --strict dist/*
python scripts/smoke.py
```

`scripts/smoke.py` makes a small set of live, read-only requests. Set
`BOND_API_KEY` and add `--require-key` to include authenticated requests.
It prints test outcomes, not keys or financial records.

See [the release instructions](docs/RELEASING.md) for TestPyPI and PyPI.
The repository includes CI and a GitHub Actions Trusted Publishing workflow.

## Licence

The Python client is MIT licensed. That software licence does not grant
redistribution rights to API data; use the data under the site's terms and
the source/attribution conditions returned by the API.
