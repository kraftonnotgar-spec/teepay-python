"""Verify TeePay webhook signatures.

TeePay signs each delivery with HMAC-SHA256 over ``<timestamp>.<raw body>`` using
your webhook signing secret (``whsec_...``) and sends::

    X-TeePay-Event-ID:  <event id, stable across retries>
    X-TeePay-Timestamp: <unix seconds>
    X-TeePay-Signature: v1=<hex digest>
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple, Union

from ._errors import WebhookVerificationError
from ._object import TeePayObject, wrap

__all__ = [
    "DEFAULT_TOLERANCE",
    "verify_webhook",
    "compute_signature",
    "generate_test_headers",
    "Webhooks",
]

DEFAULT_TOLERANCE = 300

HeadersLike = Union[Mapping[str, Any], Iterable[Tuple[str, Any]]]


def _header(headers: HeadersLike, name: str) -> Optional[str]:
    wanted = name.lower()
    items: Iterable[Tuple[Any, Any]]
    if hasattr(headers, "items"):
        items = headers.items()
    else:
        items = headers
    for key, value in items:
        if isinstance(key, bytes):
            key = key.decode("latin-1")
        if str(key).lower() != wanted:
            continue
        if isinstance(value, (list, tuple)):
            value = value[0] if value else None
        if isinstance(value, bytes):
            value = value.decode("latin-1")
        return None if value is None else str(value)
    return None


def _raw(payload: Union[bytes, bytearray, memoryview, str]) -> bytes:
    if isinstance(payload, (bytes, bytearray, memoryview)):
        return bytes(payload)
    if isinstance(payload, str):
        return payload.encode("utf-8")
    raise TypeError(
        "Webhook payload must be the raw request body (bytes or str), not parsed JSON. "
        "Flask: request.get_data(); FastAPI/Starlette: await request.body(); Django: request.body."
    )


def compute_signature(payload: Union[bytes, str], secret: str, timestamp: Union[int, str]) -> str:
    """Return the ``v1=...`` signature TeePay sends for this payload."""
    digest = hmac.new(secret.encode("utf-8"), str(timestamp).encode("ascii") + b"." + _raw(payload), hashlib.sha256)
    return "v1=" + digest.hexdigest()


def generate_test_headers(
    payload: Union[bytes, str],
    secret: str,
    timestamp: Optional[int] = None,
    event_id: str = "evt_test",
) -> Dict[str, str]:
    """Headers for a correctly signed test delivery (for your own tests)."""
    ts = int(time.time()) if timestamp is None else int(timestamp)
    return {
        "X-TeePay-Event-ID": event_id,
        "X-TeePay-Timestamp": str(ts),
        "X-TeePay-Signature": compute_signature(payload, secret, ts),
    }


def verify_webhook(
    payload: Union[bytes, bytearray, memoryview, str],
    headers: HeadersLike,
    secret: str,
    tolerance: int = DEFAULT_TOLERANCE,
    *,
    now: Optional[float] = None,
) -> TeePayObject:
    """Verify a delivery and return the parsed event.

    Args:
        payload: The raw request body, exactly as received (before JSON parsing).
        headers: The request headers (any mapping or list of pairs; case-insensitive).
        secret: Your webhook signing secret (``whsec_...``).
        tolerance: Maximum age (and clock skew) in seconds. Default 300.

    Raises:
        WebhookVerificationError: missing headers, stale timestamp or bad signature.
        TypeError: the payload is not raw bytes/str.
    """
    raw = _raw(payload)
    if not isinstance(secret, str) or not secret:
        raise WebhookVerificationError("A webhook signing secret is required.")
    timestamp = _header(headers, "X-TeePay-Timestamp")
    signature = _header(headers, "X-TeePay-Signature")
    if not timestamp or not signature:
        raise WebhookVerificationError("Missing X-TeePay-Timestamp or X-TeePay-Signature header.")
    timestamp = timestamp.strip()
    if not timestamp.isdigit() or not timestamp.isascii():
        raise WebhookVerificationError("Invalid X-TeePay-Timestamp header.")
    current = time.time() if now is None else now
    if abs(current - int(timestamp)) > tolerance:
        raise WebhookVerificationError("Webhook timestamp is outside the allowed tolerance.")
    expected = compute_signature(raw, secret, timestamp)
    matched = False
    for candidate in signature.split(","):
        candidate = candidate.strip()
        # Compare every entry so timing does not depend on which one matched.
        if hmac.compare_digest(expected.encode("ascii"), candidate.encode("utf-8", errors="replace")):
            matched = True
    if not matched:
        raise WebhookVerificationError("Webhook signature does not match.")
    try:
        event = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise WebhookVerificationError("Webhook body is not valid JSON.") from None
    if not isinstance(event, dict):
        raise WebhookVerificationError("Webhook body is not a JSON object.")
    return wrap(event)  # type: ignore[no-any-return]


class Webhooks:
    """``client.webhooks``: the same helpers, bound to a client for convenience."""

    def verify(
        self,
        payload: Union[bytes, bytearray, memoryview, str],
        headers: HeadersLike,
        secret: str,
        tolerance: int = DEFAULT_TOLERANCE,
        *,
        now: Optional[float] = None,
    ) -> TeePayObject:
        return verify_webhook(payload, headers, secret, tolerance, now=now)

    def is_valid(
        self,
        payload: Union[bytes, bytearray, memoryview, str],
        headers: HeadersLike,
        secret: str,
        tolerance: int = DEFAULT_TOLERANCE,
    ) -> bool:
        try:
            verify_webhook(payload, headers, secret, tolerance)
            return True
        except (WebhookVerificationError, TypeError):
            return False

    compute_signature = staticmethod(compute_signature)
    generate_test_headers = staticmethod(generate_test_headers)
