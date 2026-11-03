from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

__all__ = ["TeePayObject", "ResponseInfo", "RateLimit"]


@dataclass(frozen=True)
class RateLimit:
    """Values of the ``RateLimit-*`` response headers."""

    limit: Optional[int]
    remaining: Optional[int]
    reset: Optional[int]


@dataclass(frozen=True)
class ResponseInfo:
    """HTTP metadata of the response a ``TeePayObject`` came from."""

    status: int
    headers: Mapping[str, str]
    request_id: Optional[str]
    idempotent_replayed: bool
    rate_limit: Optional[RateLimit]
    api_version: Optional[str]


class TeePayObject(dict):  # type: ignore[type-arg]
    """A ``dict`` of the API's JSON with attribute access.

    ``obj["status"]`` and ``obj.status`` are equivalent. Field names are the API's
    snake_case names. ``obj.last_response`` holds the HTTP metadata (only on the
    top-level object returned by a call).
    """

    last_response: Optional[ResponseInfo] = None

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name) from None

    def to_dict(self) -> dict:  # type: ignore[type-arg]
        """A plain ``dict`` copy (nested objects included)."""

        def plain(value: Any) -> Any:
            if isinstance(value, dict):
                return {k: plain(v) for k, v in value.items()}
            if isinstance(value, list):
                return [plain(v) for v in value]
            return value

        return plain(self)  # type: ignore[no-any-return]


def wrap(value: Any) -> Any:
    if isinstance(value, dict):
        return TeePayObject({k: wrap(v) for k, v in value.items()})
    if isinstance(value, list):
        return [wrap(v) for v in value]
    return value
