"""Exceptions raised by the TeePay SDK.

Messages never contain your API key or webhook secret.
"""

from __future__ import annotations

import builtins
from typing import Any, Mapping, Optional

__all__ = [
    "TeePayError",
    "ApiError",
    "AuthenticationError",
    "PermissionError",
    "PermissionDeniedError",
    "AccountRestrictedError",
    "NotFoundError",
    "ConflictError",
    "ValidationError",
    "RateLimitError",
    "ConnectionError",
    "APIConnectionError",
    "TimeoutError",
    "APITimeoutError",
    "WebhookVerificationError",
]


class TeePayError(Exception):
    """Base class for every error raised by the SDK."""


class ApiError(TeePayError):
    """The API answered with an error status.

    Attributes:
        status: HTTP status code.
        code: Stable TeePay error code, e.g. ``"idempotency_conflict"`` (may be ``None``).
        message: Human readable message from TeePay (or a generic one).
        request_id: Quote this when you contact support.
        headers: Response headers.
        body: Parsed JSON body (or raw text) of the error response.
        retry_after: Seconds from the ``Retry-After`` header, if present.
    """

    def __init__(
        self,
        message: str,
        *,
        status: int,
        code: Optional[str] = None,
        request_id: Optional[str] = None,
        headers: Optional[Mapping[str, str]] = None,
        body: Any = None,
        retry_after: Optional[float] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.request_id = request_id
        self.headers = dict(headers or {})
        self.body = body
        self.retry_after = retry_after

    def __str__(self) -> str:
        parts = [f"{self.status}"]
        if self.code:
            parts.append(self.code)
        text = " ".join(parts) + f": {self.message}"
        if self.request_id:
            text += f" (request_id {self.request_id})"
        return text


class AuthenticationError(ApiError):
    """401: missing, invalid, revoked, expired or wrong-environment key."""


class PermissionError(ApiError):  # noqa: A001 - mirrors the other TeePay SDKs
    """403: scope or account access denied."""


PermissionDeniedError = PermissionError


class AccountRestrictedError(PermissionError):
    """403 ``account_restricted``: the account is restricted; contact TeePay support."""


class NotFoundError(ApiError):
    """404: the resource does not exist for your account."""


class ConflictError(ApiError):
    """409: idempotency key reused with a different body, or payout quote expired/changed."""


class ValidationError(ApiError):
    """400/422: the request was rejected as invalid (see ``code``)."""


class RateLimitError(ApiError):
    """429: too many requests. Wait ``retry_after`` seconds."""


class ConnectionError(TeePayError):  # noqa: A001
    """The request could not reach TeePay or no response arrived.

    For a create request this does NOT mean it failed: retry with the same
    idempotency key or read the resource.
    """


APIConnectionError = ConnectionError


class TimeoutError(ConnectionError):  # noqa: A001
    """The request timed out."""


APITimeoutError = TimeoutError


class WebhookVerificationError(TeePayError):
    """A webhook request failed signature or timestamp verification."""


_GENERIC = {
    400: "The request is invalid.",
    401: "A valid API credential is required.",
    403: "You do not have access to this resource.",
    404: "The requested resource could not be found.",
    409: "The request conflicts with an earlier request.",
    422: "The request is invalid.",
    429: "Too many requests.",
}


def generic_message(status: int) -> str:
    if status in _GENERIC:
        return _GENERIC[status]
    if status >= 500:
        return "TeePay is temporarily unavailable. Retry with the same idempotency key."
    return f"Unexpected HTTP status {status}."


def error_class(status: int, code: Optional[str]) -> "builtins.type[ApiError]":
    if status == 401:
        return AuthenticationError
    if status == 403:
        return AccountRestrictedError if code == "account_restricted" else PermissionError
    if status == 404:
        return NotFoundError
    if status == 409:
        return ConflictError
    if status in (400, 422):
        return ValidationError
    if status == 429:
        return RateLimitError
    return ApiError
