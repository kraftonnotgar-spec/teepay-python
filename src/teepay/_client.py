from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Optional

import httpx

from . import _base
from ._base import RequestSpec
from ._errors import ConnectionError, TeePayError, TimeoutError
from ._object import TeePayObject
from .resources import (
    AsyncCheckoutSessions,
    AsyncCollections,
    AsyncControlNumbers,
    AsyncDisbursements,
    CheckoutSessions,
    Collections,
    ControlNumbers,
    Disbursements,
)
from .webhooks import Webhooks

__all__ = ["TeePay", "AsyncTeePay"]


class _Config(_base.Redacted):
    def __init__(
        self,
        api_key: Optional[str],
        base_url: Optional[str],
        timeout: float,
        max_retries: int,
        api_version: Optional[str],
    ) -> None:
        self.__api_key = _base.resolve_api_key(api_key)
        self.environment: str = _base.environment_for_key(self.__api_key)
        self.base_url: str = (base_url or _base.DEFAULT_BASE_URL).rstrip("/")
        if timeout is None or timeout <= 0:
            raise TeePayError("timeout must be a positive number of seconds")
        if max_retries is None or max_retries < 0:
            raise TeePayError("max_retries must be 0 or more")
        self.timeout = float(timeout)
        self.max_retries = int(max_retries)
        self.api_version = api_version
        self.webhooks = Webhooks()

    def _headers(self, spec: RequestSpec) -> Dict[str, str]:
        return _base.build_headers(self.__api_key, self.api_version, spec)

    def _prepare(self, spec: RequestSpec) -> Dict[str, Any]:
        if spec.body is not None:
            spec.body = _base.clean_body(spec.body)
        return {
            "method": spec.method,
            "url": self.base_url + spec.path,
            "params": _base.clean_query(spec.query),
            "headers": self._headers(spec),
            "content": _base.encode_body(spec),
            "timeout": spec.timeout if spec.timeout is not None else self.timeout,
        }

    def _retries(self, spec: RequestSpec) -> int:
        return self.max_retries if spec.max_retries is None else max(0, int(spec.max_retries))

    @staticmethod
    def _lower(headers: httpx.Headers) -> Dict[str, str]:
        return {k.lower(): v for k, v in headers.items()}

    def __getstate__(self) -> Any:
        raise TypeError("TeePay clients cannot be pickled (they hold your API key).")


class TeePay(_Config):
    """Synchronous TeePay client.

    >>> teepay = TeePay("tp_test_...")          # or set TEEPAY_API_KEY
    >>> teepay.capabilities().features.collection_create
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        base_url: Optional[str] = None,
        timeout: float = _base.DEFAULT_TIMEOUT,
        max_retries: int = _base.DEFAULT_MAX_RETRIES,
        api_version: Optional[str] = None,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        super().__init__(api_key, base_url, timeout, max_retries, api_version)
        self._owns_http = http_client is None
        self._http = http_client or httpx.Client(follow_redirects=False)
        self.collections = Collections(self)
        self.disbursements = Disbursements(self)
        self.control_numbers = ControlNumbers(self)
        self.checkout_sessions = CheckoutSessions(self)

    def whoami(self, *, timeout: Optional[float] = None, max_retries: Optional[int] = None) -> TeePayObject:
        """Application, environment, scopes and prefix of the current key."""
        return self._request(RequestSpec("GET", "/v1/whoami", timeout=timeout, max_retries=max_retries))

    def capabilities(self, *, timeout: Optional[float] = None, max_retries: Optional[int] = None) -> TeePayObject:
        """What this key can do now, and the markets it can collect in."""
        return self._request(RequestSpec("GET", "/v1/capabilities", timeout=timeout, max_retries=max_retries))

    def _request(self, spec: RequestSpec) -> TeePayObject:
        request = self._prepare(spec)
        retries = self._retries(spec)
        attempt = 0
        while True:
            try:
                response = self._http.request(**request)
            except httpx.TimeoutException:
                if attempt < retries and _base.should_retry(spec, None):
                    time.sleep(_base.retry_delay(attempt, None) or 0)
                    attempt += 1
                    continue
                raise TimeoutError("The request to TeePay timed out. For a create, retry with the same idempotency key or read the resource.") from None
            except httpx.TransportError as exc:
                if attempt < retries and _base.should_retry(spec, None):
                    time.sleep(_base.retry_delay(attempt, None) or 0)
                    attempt += 1
                    continue
                raise ConnectionError(f"Could not connect to TeePay ({type(exc).__name__}).") from None
            headers = self._lower(response.headers)
            if response.status_code < 400:
                return _base.make_result(response.status_code, headers, response.content)
            if attempt < retries and _base.should_retry(spec, response.status_code):
                delay = _base.retry_delay(attempt, _base.parse_retry_after(headers))
                if delay is not None:
                    time.sleep(delay)
                    attempt += 1
                    continue
            raise _base.make_error(response.status_code, headers, response.content)

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> "TeePay":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


class AsyncTeePay(_Config):
    """Asynchronous TeePay client (same methods as :class:`TeePay`, awaitable).

    >>> async with AsyncTeePay() as teepay:
    ...     session = await teepay.checkout_sessions.create(title="Order 1001", amount_minor=500000, currency="TZS")
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        base_url: Optional[str] = None,
        timeout: float = _base.DEFAULT_TIMEOUT,
        max_retries: int = _base.DEFAULT_MAX_RETRIES,
        api_version: Optional[str] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        super().__init__(api_key, base_url, timeout, max_retries, api_version)
        self._owns_http = http_client is None
        self._http = http_client or httpx.AsyncClient(follow_redirects=False)
        self.collections = AsyncCollections(self)
        self.disbursements = AsyncDisbursements(self)
        self.control_numbers = AsyncControlNumbers(self)
        self.checkout_sessions = AsyncCheckoutSessions(self)

    async def whoami(self, *, timeout: Optional[float] = None, max_retries: Optional[int] = None) -> TeePayObject:
        return await self._request(RequestSpec("GET", "/v1/whoami", timeout=timeout, max_retries=max_retries))

    async def capabilities(self, *, timeout: Optional[float] = None, max_retries: Optional[int] = None) -> TeePayObject:
        return await self._request(RequestSpec("GET", "/v1/capabilities", timeout=timeout, max_retries=max_retries))

    async def _request(self, spec: RequestSpec) -> TeePayObject:
        request = self._prepare(spec)
        retries = self._retries(spec)
        attempt = 0
        while True:
            try:
                response = await self._http.request(**request)
            except httpx.TimeoutException:
                if attempt < retries and _base.should_retry(spec, None):
                    await asyncio.sleep(_base.retry_delay(attempt, None) or 0)
                    attempt += 1
                    continue
                raise TimeoutError("The request to TeePay timed out. For a create, retry with the same idempotency key or read the resource.") from None
            except httpx.TransportError as exc:
                if attempt < retries and _base.should_retry(spec, None):
                    await asyncio.sleep(_base.retry_delay(attempt, None) or 0)
                    attempt += 1
                    continue
                raise ConnectionError(f"Could not connect to TeePay ({type(exc).__name__}).") from None
            headers = self._lower(response.headers)
            if response.status_code < 400:
                return _base.make_result(response.status_code, headers, response.content)
            if attempt < retries and _base.should_retry(spec, response.status_code):
                delay = _base.retry_delay(attempt, _base.parse_retry_after(headers))
                if delay is not None:
                    await asyncio.sleep(delay)
                    attempt += 1
                    continue
            raise _base.make_error(response.status_code, headers, response.content)

    async def close(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def __aenter__(self) -> "AsyncTeePay":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()
