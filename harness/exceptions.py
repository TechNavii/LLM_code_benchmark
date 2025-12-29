"""Common exceptions for the harness."""


class HarnessError(RuntimeError):
    """Custom harness error for clearer exception handling."""


class APIError(HarnessError):
    """Base class for API-related errors (transient, not LLM failures)."""

    def __init__(self, message: str, *, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class RateLimitError(APIError):
    """Error raised when API returns 429 rate limit."""

    pass


class EmptyResponseError(APIError):
    """Error raised when API returns empty content."""

    pass


class ProviderError(APIError):
    """Error raised when upstream provider fails (5xx, network issues)."""

    pass
