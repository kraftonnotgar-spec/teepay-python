"""Official Python SDK for the TeePay API (https://api.teepay.me)."""

from ._base import API_VERSION, DEFAULT_BASE_URL, generate_idempotency_key
from ._client import AsyncTeePay, TeePay
from ._errors import (
    AccountRestrictedError,
    APIConnectionError,
    ApiError,
    APITimeoutError,
    AuthenticationError,
    ConflictError,
    ConnectionError,
    NotFoundError,
    PermissionDeniedError,
    PermissionError,
    RateLimitError,
    TeePayError,
    TimeoutError,
    ValidationError,
    WebhookVerificationError,
)
from ._object import RateLimit, ResponseInfo, TeePayObject
from ._version import __version__
from .webhooks import compute_signature, generate_test_headers, verify_webhook

__all__ = [
    "__version__",
    "API_VERSION",
    "DEFAULT_BASE_URL",
    "TeePay",
    "AsyncTeePay",
    "TeePayObject",
    "ResponseInfo",
    "RateLimit",
    "generate_idempotency_key",
    "verify_webhook",
    "compute_signature",
    "generate_test_headers",
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
