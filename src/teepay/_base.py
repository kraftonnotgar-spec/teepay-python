"""Transport-independent logic shared by the sync and async clients."""

from __future__ import annotations

import json
import os
import platform
import random
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import quote

from ._errors import TeePayError, error_class, generic_message
from ._object import RateLimit, ResponseInfo, TeePayObject, wrap
from ._version import __version__

DEFAULT_BASE_URL = "https://api.teepay.me"
DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_RETRIES = 2
API_VERSION = "2026-10-18"
MAX_RETRY_AFTER = 60.0
RETRY_STATUSES = frozenset({408, 429, 500, 502, 503, 504})

_NOT_GIVEN: Any = object()


@dataclass
class RequestSpec:
    method: str
    path: str
    query: Optional[Dict[str, Any]] = None
    body: Optional[Dict[str, Any]] = None
    # Value of the Idempotency-Key header, when the operation takes one there.
    idempotency_header: Optional[str] = None
    # True when the request carries an idempotency key (header or body).
    idempotent: bool = False
    timeout: Optional[float] = None
    max_retries: Optional[int] = None
    extra: Dict[str, Any] = field(default_factory=dict)


def generate_idempotency_key() -> str:
    """A fresh key such as ``sdk-3f2b...``; 40 characters of ``[A-Za-z0-9-]``."""
    return "sdk-" + str(uuid.uuid4())


def environment_for_key(api_key: str) -> str:
    if api_key.startswith("tp_live_"):
        return "live"
    if api_key.startswith("tp_test_"):
        return "sandbox"
    raise TeePayError(
        "TeePay API keys start with tp_test_ (sandbox) or tp_live_ (live). "
        "Check the key you passed or the TEEPAY_API_KEY environment variable."
    )


def resolve_api_key(api_key: Optional[str]) -> str:
    key = api_key if api_key is not None else os.environ.get("TEEPAY_API_KEY")
    if not key:
        raise TeePayError("No API key: pass api_key=... or set the TEEPAY_API_KEY environment variable.")
    if not isinstance(key, str) or key != key.strip() or any(c in key for c in "\r\n\t "):
        raise TeePayError("The API key is malformed (it contains whitespace).")
    environment_for_key(key)
    return key


def user_agent() -> str:
    return f"teepay-python/{__version__} python/{platform.python_version()}"


def encode_path(value: Any, name: str) -> str:
    if not isinstance(value, str) or value == "":
        raise ValueError(f"{name} must be a non-empty string")
    return quote(value, safe="")


def minor(value: Any, name: str) -> Any:
    """Convert integer minor units to the decimal string the API expects."""
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer number of minor units or a string of digits")
    if isinstance(value, int):
        return str(value)
    return value


def clean_body(value: Any, path: str = "") -> Any:
    """Drop ``None`` fields and enforce the API's lowercase-key JSON rule."""
    if isinstance(value, Mapping):
        out: Dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"TeePay request keys must be strings (got {key!r} at {path or 'body'})")
            if key != key.lower():
                where = f"{path}.{key}" if path else key
                raise ValueError(
                    f"TeePay rejects JSON object keys that are not all lowercase: {where!r}. "
                    "Use lowercase keys (this includes metadata keys)."
                )
            if item is None:
                continue
            out[key] = clean_body(item, f"{path}.{key}" if path else key)
        return out
    if isinstance(value, (list, tuple)):
        return [clean_body(item, f"{path}[{i}]") for i, item in enumerate(value)]
    return value


def clean_query(query: Optional[Mapping[str, Any]]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for key, value in (query or {}).items():
        if value is None:
            continue
        out[key] = str(value).lower() if isinstance(value, bool) else str(value)
    return out


def build_headers(api_key: str, api_version: Optional[str], spec: RequestSpec) -> Dict[str, str]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "User-Agent": user_agent(),
    }
    if spec.body is not None:
        headers["Content-Type"] = "application/json"
    if spec.idempotency_header is not None:
        headers["Idempotency-Key"] = spec.idempotency_header
    if api_version:
        headers["TeePay-Version"] = api_version
    return headers


def encode_body(spec: RequestSpec) -> Optional[bytes]:
    if spec.body is None:
        return None
    return json.dumps(spec.body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def parse_retry_after(headers: Mapping[str, str]) -> Optional[float]:
    value = headers.get("retry-after")
    if value is None:
        return None
    try:
        seconds = float(value.strip())
    except ValueError:
        return None
    return max(0.0, seconds)


def should_retry(spec: RequestSpec, status: Optional[int]) -> bool:
    """``status`` is ``None`` for a connection error or timeout."""
    if status == 429:
        # Admission rejected the request before any work was done.
        return True
    if not (spec.method == "GET" or spec.idempotent):
        return False
    return status is None or status in RETRY_STATUSES


def retry_delay(attempt: int, retry_after: Optional[float]) -> Optional[float]:
    """Seconds to wait before retry number ``attempt`` (0-based); ``None`` = do not retry."""
    if retry_after is not None:
        return None if retry_after > MAX_RETRY_AFTER else retry_after
    return random.uniform(0, min(8.0, 0.5 * (2**attempt)))


def _int(value: Optional[str]) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def response_info(status: int, headers: Mapping[str, str], body: Any = None) -> ResponseInfo:
    request_id = headers.get("x-request-id")
    if not request_id and isinstance(body, dict) and isinstance(body.get("error"), dict):
        request_id = body["error"].get("request_id") or None
    rate_limit = None
    if any(h in headers for h in ("ratelimit-limit", "ratelimit-remaining", "ratelimit-reset")):
        rate_limit = RateLimit(
            limit=_int(headers.get("ratelimit-limit")),
            remaining=_int(headers.get("ratelimit-remaining")),
            reset=_int(headers.get("ratelimit-reset")),
        )
    return ResponseInfo(
        status=status,
        headers=dict(headers),
        request_id=request_id,
        idempotent_replayed=(headers.get("idempotent-replayed", "").lower() == "true"),
        rate_limit=rate_limit,
        api_version=headers.get("teepay-version"),
    )


def decode_json(content: bytes) -> Tuple[Any, bool]:
    if not content:
        return None, True
    try:
        return json.loads(content.decode("utf-8")), True
    except (ValueError, UnicodeDecodeError):
        try:
            return content.decode("utf-8", errors="replace"), False
        except Exception:  # pragma: no cover
            return None, False


def make_error(status: int, headers: Mapping[str, str], content: bytes) -> Exception:
    body, _ = decode_json(content)
    code: Optional[str] = None
    message: Optional[str] = None
    request_id: Optional[str] = headers.get("x-request-id") or None
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            code = err.get("code") if isinstance(err.get("code"), str) else None
            message = err.get("message") if isinstance(err.get("message"), str) else None
            if isinstance(err.get("request_id"), str) and err.get("request_id"):
                request_id = err["request_id"]
        elif isinstance(err, str):
            code = err
    cls = error_class(status, code)
    return cls(
        message or generic_message(status),
        status=status,
        code=code,
        request_id=request_id,
        headers=headers,
        body=body,
        retry_after=parse_retry_after(headers),
    )


def make_result(status: int, headers: Mapping[str, str], content: bytes) -> TeePayObject:
    body, ok = decode_json(content)
    if not ok:
        from ._errors import ApiError

        raise ApiError(
            "TeePay returned a response that is not JSON.",
            status=status,
            request_id=headers.get("x-request-id"),
            headers=headers,
            body=body,
        )
    value = wrap(body if isinstance(body, dict) else {"data": body} if body is not None else {})
    value.last_response = response_info(status, headers, body)
    return value  # type: ignore[no-any-return]


def page_items(page: Mapping[str, Any]) -> List[TeePayObject]:
    items = page.get("items")
    if items is None:
        items = page.get("data")
    return list(items or [])


class Redacted:
    """Mixin: never show the API key in reprs."""

    environment: str
    base_url: str

    def __repr__(self) -> str:
        return f"{type(self).__name__}(environment={self.environment!r}, base_url={self.base_url!r})"
