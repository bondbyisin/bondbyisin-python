"""A small synchronous HTTP client; financial observations are never calculated here."""

from __future__ import annotations

import math
import os
import re
import time
from collections.abc import Iterator, Mapping
from datetime import date as Date
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote, unquote, urlsplit

import requests

from ._version import __version__
from .exceptions import (
    APIError,
    AuthenticationError,
    InvalidResponseError,
    NotFoundError,
    RateLimitError,
    RequestTimeoutError,
    TransportError,
)

BASE_URL = "https://bondbyisin.com/v1"
_RETRY_STATUSES = {429, 500, 502, 503, 504}
_SECRET_PARAMS = {"key", "api_key", "apikey", "token", "authorization", "x-api-key"}


def _integer(value: int, label: str, minimum: int, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{label} must be <= {maximum}")
    return value


def _positive(value: float, label: str, *, zero: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number")
    if not math.isfinite(value) or (value < 0 if zero else value <= 0):
        raise ValueError(f"{label} must be {'non-negative' if zero else 'positive'} and finite")
    return float(value)


def _identifier(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("identifier must be a CUSIP or ISIN string")
    value = value.strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{9}|[A-Z0-9]{12}", value):
        raise ValueError("identifier must contain 9 (CUSIP) or 12 (ISIN) letters/digits")
    return value


def _date(value: str | Date | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        raise ValueError("Use a reporting date, not a datetime")
    if isinstance(value, Date):
        return value.isoformat()
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Dates must use YYYY-MM-DD")
    Date.fromisoformat(value)
    return value


def _range(start: str | Date | None, end: str | Date | None) -> dict[str, Any]:
    first, last = _date(start), _date(end)
    if first is not None and last is not None and first > last:
        raise ValueError("start must not be after end")
    return {"start": first, "end": last}


def _segment(value: str, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _.-]*", value):
        raise ValueError(f"{label} contains unsupported characters")
    return quote(value.strip(), safe="")


def _retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        delay = float(value)
    except ValueError:
        try:
            target = parsedate_to_datetime(value)
            if target.tzinfo is None:
                target = target.replace(tzinfo=timezone.utc)
            delay = (target - datetime.now(timezone.utc)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return None
    return max(0.0, delay) if math.isfinite(delay) else None


class Client:
    """Read the Bond by ISIN API.

    ``api_key=None`` reads BOND_API_KEY, then BONDBYISIN_API_KEY. Pass an empty
    string to make an explicitly anonymous client. Exact documented examples
    are public; other requests require an active API subscription.

    Responses are ordinary dictionaries containing the unmodified API JSON.
    Instances reuse a requests.Session and should not be shared across threads.
    A caller-supplied session remains owned by the caller.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        timeout: float | tuple[float, float] = (10.0, 60.0),
        max_retries: int = 2,
        backoff_factor: float = 0.5,
        max_retry_delay: float = 30.0,
        base_url: str = BASE_URL,
        session: requests.Session | None = None,
    ) -> None:
        parsed = urlsplit(base_url)
        local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if (
            not parsed.hostname
            or (parsed.scheme != "https" and not (parsed.scheme == "http" and local))
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path.rstrip("/") != "/v1"
        ):
            raise ValueError(
                "base_url must be an HTTPS API origin ending in /v1 (HTTP loopback is allowed)"
            )
        if isinstance(timeout, tuple):
            if len(timeout) != 2:
                raise ValueError("timeout must be a number or (connect, read) pair")
            self.timeout = tuple(_positive(v, "timeout") for v in timeout)
        else:
            self.timeout = _positive(timeout, "timeout")
        self.max_retries = _integer(max_retries, "max_retries", 0, 10)
        self.backoff_factor = _positive(backoff_factor, "backoff_factor", zero=True)
        self.max_retry_delay = _positive(max_retry_delay, "max_retry_delay", zero=True)
        if api_key is None:
            api_key = os.environ.get("BOND_API_KEY") or os.environ.get("BONDBYISIN_API_KEY") or ""
        if not isinstance(api_key, str) or any(ord(c) < 32 or ord(c) > 126 for c in api_key):
            raise ValueError("api_key must be a single-line ASCII string")
        self._api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self._session = session if session is not None else requests.Session()
        self._owns_session = session is None
        self._closed = False

    def __repr__(self) -> str:
        return f"Client(base_url={self.base_url!r}, authenticated={bool(self._api_key)})"

    def __enter__(self) -> Client:
        if self._closed:
            raise RuntimeError("Client is closed")
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def close(self) -> None:
        """Release this client's connection pool, if it owns it."""
        if not self._closed and self._owns_session:
            self._session.close()
        self._closed = True

    def _redact(self, value: str) -> str:
        return value.replace(self._api_key, "[redacted]") if self._api_key else value

    def get(self, path: str, *, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """GET a relative /v1 JSON path and preserve all response fields.

        Absolute URLs, embedded query strings, traversal and credentials in
        query parameters are rejected. Redirects are not followed, so an API
        key cannot be forwarded to a different host by a redirect.
        """
        if self._closed:
            raise RuntimeError("Client is closed")
        if not isinstance(path, str):
            raise ValueError("path must be a relative API path")
        parsed = urlsplit(path)
        decoded = unquote(parsed.path)
        if (
            parsed.scheme
            or parsed.netloc
            or parsed.query
            or parsed.fragment
            or "\\" in decoded
            or "%" in decoded
            or any(part in {".", ".."} for part in decoded.split("/"))
            or any(ord(c) < 32 for c in decoded)
        ):
            raise ValueError("Use a relative API path and pass query arguments through params")
        path = parsed.path.lstrip("/")
        if path == "v1":
            path = ""
        elif path.startswith("v1/"):
            path = path[3:]
        clean_params = {k: v for k, v in (params or {}).items() if v is not None}
        if any(str(k).lower() in _SECRET_PARAMS for k in clean_params):
            raise ValueError("Pass API credentials to Client(api_key=...), not in query parameters")
        safe_path = "/v1" + ("/" + path if path else "")
        headers = {"Accept": "application/json", "User-Agent": f"bondbyisin/{__version__}"}
        if self._api_key:
            headers["X-API-Key"] = self._api_key
        for attempt in range(self.max_retries + 1):
            try:
                response = self._session.get(
                    self.base_url + ("/" + path if path else ""),
                    params=clean_params,
                    headers=headers,
                    timeout=self.timeout,
                    allow_redirects=False,
                )
            except requests.exceptions.SSLError:
                raise TransportError(f"TLS verification failed for {safe_path}") from None
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
                if attempt < self.max_retries:
                    time.sleep(min(self.backoff_factor * 2**attempt, self.max_retry_delay))
                    continue
                error = (
                    RequestTimeoutError
                    if isinstance(exc, requests.exceptions.Timeout)
                    else TransportError
                )
                raise error(f"Unable to complete request to {safe_path}") from None
            except requests.exceptions.RequestException:
                raise TransportError(f"Unable to complete request to {safe_path}") from None
            with response:
                status = response.status_code
                retry_after = _retry_after(response.headers.get("Retry-After"))
                if status in _RETRY_STATUSES and attempt < self.max_retries:
                    delay = (
                        retry_after
                        if retry_after is not None
                        else min(self.backoff_factor * 2**attempt, self.max_retry_delay)
                    )
                    if delay <= self.max_retry_delay:
                        response.close()
                        time.sleep(delay)
                        continue
                try:
                    payload = response.json()
                except ValueError:
                    payload = None
                if not 200 <= status < 300 or isinstance(payload, dict) and payload.get("error"):
                    default_message = (
                        "An active API subscription key is required; see https://bondbyisin.com/account"
                        if status in {401, 402, 403}
                        else "API request failed"
                    )
                    message = (
                        payload.get("error", default_message)
                        if isinstance(payload, dict)
                        else default_message
                    )
                    error_class = {
                        401: AuthenticationError,
                        402: AuthenticationError,
                        403: AuthenticationError,
                        404: NotFoundError,
                        429: RateLimitError,
                    }.get(status, APIError)
                    raise error_class(
                        self._redact(str(message))[:500],
                        status_code=status,
                        path=self._redact(safe_path),
                        request_id=self._redact(response.headers.get("X-Request-ID", "")) or None,
                        retry_after=retry_after,
                    )
                if not isinstance(payload, dict):
                    raise InvalidResponseError(f"Expected a JSON object from {safe_path}")
                return payload
        raise AssertionError("Unreachable retry state")

    def search(
        self,
        query: str,
        *,
        limit: int | None = None,
        page: int | None = None,
        sort: str | None = None,
        order: str | None = None,
        include_matured: bool | None = None,
    ) -> dict[str, Any]:
        """Search one page; omitted options retain the API's defaults (25 rows)."""
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 120:
            raise ValueError("query must contain 1 to 120 characters")
        if limit is not None:
            _integer(limit, "limit", 1, 100)
        if page is not None:
            _integer(page, "page", 1)
        if order not in {None, "asc", "desc"}:
            raise ValueError("order must be asc or desc")
        if (sort or "maturity", order or "asc") not in {
            ("maturity", "asc"),
            ("maturity", "desc"),
            ("ytm", "asc"),
            ("ytm", "desc"),
            ("coupon", "desc"),
            ("price", "asc"),
        }:
            raise ValueError("Unsupported search sort/order combination; see the API documentation")
        if include_matured is not None and not isinstance(include_matured, bool):
            raise ValueError("include_matured must be a boolean")
        return self.get(
            "bonds/search",
            params={
                "q": query.strip(),
                "limit": limit,
                "page": page,
                "sort": sort,
                "order": order,
                "include_matured": int(include_matured) if include_matured is not None else None,
            },
        )

    def iter_search(
        self,
        query: str,
        *,
        limit: int | None = None,
        page: int | None = None,
        sort: str | None = None,
        order: str | None = None,
        include_matured: bool | None = None,
        max_pages: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield search rows across explicit next_page links; subscription normally required."""
        if max_pages is not None:
            _integer(max_pages, "max_pages", 1)
        seen: set[int] = set()
        while True:
            current = page if page is not None else 1
            seen.add(current)
            payload = self.search(
                query,
                limit=limit,
                page=page,
                sort=sort,
                order=order,
                include_matured=include_matured,
            )
            rows = payload.get("results")
            if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
                raise InvalidResponseError("Search response must contain a results list of objects")
            if "next_page" not in payload:
                raise InvalidResponseError(
                    "Search response is missing next_page pagination metadata"
                )
            yield from rows
            next_page = payload.get("next_page")
            if next_page is None or max_pages is not None and len(seen) >= max_pages:
                return
            if (
                isinstance(next_page, bool)
                or not isinstance(next_page, int)
                or next_page != current + 1
                or next_page in seen
                or not rows
            ):
                raise InvalidResponseError("Search returned invalid or non-advancing pagination")
            page = next_page

    def bond(self, identifier: str) -> dict[str, Any]:
        """Bond terms, identifiers, observations, DV01 and distinct spread fields."""
        return self.get(f"bond/{_identifier(identifier)}")

    def history(self, identifier: str) -> dict[str, Any]:
        """All stored price/yield points. This endpoint has no date-filter contract."""
        return self.get(f"bond/{_identifier(identifier)}/history")

    def cashflows(self, identifier: str) -> dict[str, Any]:
        """Cash-flow schedule and valuation fields, where available from the API."""
        return self.get(f"bond/{_identifier(identifier)}/cashflows")

    def analytics(self, identifier: str, *, date: str | Date | None = None) -> dict[str, Any]:
        """Yield, duration and spreads for the requested observation date."""
        return self.get(f"bond/{_identifier(identifier)}/analytics", params={"date": _date(date)})

    def zspread(self, identifier: str, *, date: str | Date | None = None) -> dict[str, Any]:
        """Government-curve Z-spread and its supporting API data."""
        return self.get(f"bond/{_identifier(identifier)}/zspread", params={"date": _date(date)})

    def swap_zspread(self, identifier: str, *, date: str | Date | None = None) -> dict[str, Any]:
        """Swap-curve Z-spread and its supporting API data."""
        return self.get(
            f"bond/{_identifier(identifier)}/swap-zspread", params={"date": _date(date)}
        )

    def spread_history(
        self,
        identifier: str,
        *,
        date: str | Date | None = None,
        start: str | Date | None = None,
        end: str | Date | None = None,
    ) -> dict[str, Any]:
        """Spread observations for one date or a date range."""
        if date is not None and (start is not None or end is not None):
            raise ValueError("Use date or start/end, not both")
        return self.get(
            f"bond/{_identifier(identifier)}/spread-history",
            params={"date": _date(date), **_range(start, end)},
        )

    def spread_range(
        self,
        identifier: str,
        *,
        start: str | Date | None = None,
        end: str | Date | None = None,
    ) -> dict[str, Any]:
        """Server-reported minimum, maximum and average spread for a date range."""
        return self.get(f"bond/{_identifier(identifier)}/spread-range", params=_range(start, end))

    def zspread_range(
        self,
        identifier: str,
        *,
        start: str | Date | None = None,
        end: str | Date | None = None,
    ) -> dict[str, Any]:
        """Server-reported government Z-spread range."""
        return self.get(f"bond/{_identifier(identifier)}/zspread/range", params=_range(start, end))

    def zspread_history_summary(self, identifier: str) -> dict[str, Any]:
        """Available dates and coverage of government Z-spread history."""
        return self.get(f"bond/{_identifier(identifier)}/zspread/history-summary")

    def curves(self, *, family: str | None = None) -> dict[str, Any]:
        """Curve catalogue, optionally restricted to a family."""
        return self.get("curves", params={"family": family})

    def curve(
        self,
        curve_id: str,
        *,
        term: float | None = None,
        date: str | Date | None = None,
    ) -> dict[str, Any]:
        """One curve, or an API-reported tenor in years, on an optional date."""
        if term is not None:
            _positive(term, "term")
        return self.get(
            f"curves/{_segment(curve_id, 'curve_id')}", params={"term": term, "date": _date(date)}
        )

    def sovereign_curve(self, country: str) -> dict[str, Any]:
        """The latest government curve for a country, e.g. India or United States."""
        return self.get(f"curves/sovereign/{_segment(country, 'country')}")

    def muni_curve(self, state: str) -> dict[str, Any]:
        """The latest US municipal curve for a two-letter state code."""
        if not isinstance(state, str) or not re.fullmatch(r"[A-Za-z]{2}", state):
            raise ValueError("state must be a two-letter US state code")
        return self.get(f"curves/muni/{state.upper()}")

    def swap_curves(
        self,
        currency: str | None = None,
        *,
        date: str | Date | None = None,
        curve_type: str | None = None,
    ) -> dict[str, Any]:
        """Swap catalogue, or one currency's rates; curve_type is the API's type option."""
        if currency is not None:
            if not isinstance(currency, str) or not re.fullmatch(r"[A-Za-z]{3}", currency):
                raise ValueError("currency must be a three-letter currency code")
            currency = currency.upper()
        elif date is not None or curve_type is not None:
            raise ValueError("currency is required when selecting a date or curve_type")
        return self.get(
            "swap-curves", params={"currency": currency, "date": _date(date), "type": curve_type}
        )

    def sovereign_ratings(self) -> dict[str, Any]:
        """The API's sovereign ratings directory."""
        return self.get("sovereign-ratings")

    def issuer(self, slug: str) -> dict[str, Any]:
        """Bonds for an issuer slug such as microsoft."""
        if not isinstance(slug, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
            raise ValueError("slug must use lowercase letters, digits and single hyphens")
        return self.get(f"issuer/{slug}")

    def auctions(self, country: str) -> dict[str, Any]:
        """Government auctions for an API country code such as us."""
        if not isinstance(country, str) or not re.fullmatch(r"[A-Za-z]{2,4}", country):
            raise ValueError("country must be a two-to-four-letter API country code")
        return self.get(f"auctions/{country.lower()}")

    def etfs(self) -> dict[str, Any]:
        """Bond ETF yield and duration directory."""
        return self.get("etfs")
