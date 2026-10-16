"""Exceptions that do not include request headers or API keys."""


class BondByISINError(Exception):
    """Base exception for client and API failures."""


class TransportError(BondByISINError):
    """The server could not be reached or the secure connection failed."""


class RequestTimeoutError(TransportError):
    """The connection or response timed out."""


class InvalidResponseError(BondByISINError):
    """The server returned an unexpected response or invalid pagination."""


class APIError(BondByISINError):
    """An API rejection, with HTTP status and safe request context."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        path: str,
        request_id: str | None = None,
        retry_after: float | None = None,
    ) -> None:
        self.status_code = status_code
        self.path = path
        self.request_id = request_id
        self.retry_after = retry_after
        super().__init__(f"HTTP {status_code} for {path}: {message}")


class AuthenticationError(APIError):
    """The API requires a valid key with the appropriate subscription."""


class NotFoundError(APIError):
    """The requested bond or API resource was not found."""


class RateLimitError(APIError):
    """The API returned HTTP 429; retry_after is seconds when provided."""
