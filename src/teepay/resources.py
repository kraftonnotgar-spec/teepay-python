"""API resources. Each sync class has an async twin with the same methods."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, Iterator, Mapping, Optional

from ._base import RequestSpec, encode_path, generate_idempotency_key, minor, page_items
from ._object import TeePayObject
from .types import (
    CollectionCustomerParam,
    CollectionMoneyParam,
    ControlNumberCustomerParam,
    PayoutDestinationParam,
    PayoutMoneyParam,
)

if TYPE_CHECKING:  # pragma: no cover
    from ._client import AsyncTeePay, TeePay

__all__ = [
    "Collections",
    "Disbursements",
    "ControlNumbers",
    "CheckoutSessions",
    "AsyncCollections",
    "AsyncDisbursements",
    "AsyncControlNumbers",
    "AsyncCheckoutSessions",
]

_MAX_PAGES = 10_000


def _opts(spec: RequestSpec, timeout: Optional[float], max_retries: Optional[int]) -> RequestSpec:
    spec.timeout = timeout
    spec.max_retries = max_retries
    return spec


# ---- request builders (shared) --------------------------------------------


def _collection_create(money: Mapping[str, Any], customer: Mapping[str, Any], description: Optional[str], key: Optional[str]) -> RequestSpec:
    money = dict(money)
    if "amount_minor" in money:
        money["amount_minor"] = minor(money["amount_minor"], "money.amount_minor")
    body: Dict[str, Any] = {"money": money, "customer": dict(customer), "description": description}
    key = key or generate_idempotency_key()
    return RequestSpec("POST", "/v1/collections", body=body, idempotency_header=key, idempotent=True)


def _transaction_list(base: str, limit: Optional[int], cursor: Optional[str], status: Optional[str], currency: Optional[str]) -> RequestSpec:
    return RequestSpec("GET", base, query={"limit": limit, "cursor": cursor, "status": status, "currency": currency})


def _quote(money: Mapping[str, Any], destination: Mapping[str, Any], narration: str) -> RequestSpec:
    body = {"money": dict(money), "destination": dict(destination), "narration": narration}
    return RequestSpec("POST", "/v1/disbursements/quote", body=body)


def _payout_create(quote_id: str, key: Optional[str]) -> RequestSpec:
    body = {"quote_id": quote_id, "idempotency_key": key or generate_idempotency_key()}
    return RequestSpec("POST", "/v1/disbursements", body=body, idempotent=True)


def _control_number_create(
    kind: str,
    customer: Mapping[str, Any],
    description: Optional[str],
    amount_minor: Any,
    maximum_minor: Any,
    payment_mode: Optional[str],
    key: Optional[str],
) -> RequestSpec:
    body = {
        "kind": kind,
        "customer": dict(customer),
        "description": description,
        "amount_minor": minor(amount_minor, "amount_minor"),
        "maximum_minor": minor(maximum_minor, "maximum_minor"),
        "payment_mode": payment_mode,
    }
    return RequestSpec("POST", "/v1/control-numbers", body=body, idempotency_header=key or generate_idempotency_key(), idempotent=True)


def _checkout_create(
    title: str,
    amount_minor: Any,
    currency: str,
    description: Optional[str],
    expires_in: Optional[int],
    payment_profile_id: Optional[str],
    reference: Optional[str],
    metadata: Optional[Mapping[str, str]],
    key: Optional[str],
) -> RequestSpec:
    body = {
        "title": title,
        "description": description,
        "amount_minor": minor(amount_minor, "amount_minor"),
        "currency": currency,
        "expires_in": expires_in,
        "payment_profile_id": payment_profile_id,
        "reference": reference,
        "metadata": dict(metadata) if metadata is not None else None,
    }
    return RequestSpec("POST", "/v1/checkout-sessions", body=body, idempotency_header=key or generate_idempotency_key(), idempotent=True)


class _Resource:
    def __init__(self, client: Any) -> None:
        self._client = client

    def _iterate(self, spec: RequestSpec) -> Iterator[TeePayObject]:
        query = dict(spec.query or {})
        seen = set()
        for _ in range(_MAX_PAGES):
            page = self._client._request(RequestSpec(spec.method, spec.path, query=dict(query), timeout=spec.timeout, max_retries=spec.max_retries))
            yield from page_items(page)
            cursor = page.get("next_cursor")
            if not cursor or cursor in seen:
                return
            seen.add(cursor)
            query["cursor"] = cursor

    async def _aiterate(self, spec: RequestSpec) -> AsyncIterator[TeePayObject]:
        query = dict(spec.query or {})
        seen = set()
        for _ in range(_MAX_PAGES):
            page = await self._client._request(RequestSpec(spec.method, spec.path, query=dict(query), timeout=spec.timeout, max_retries=spec.max_retries))
            for item in page_items(page):
                yield item
            cursor = page.get("next_cursor")
            if not cursor or cursor in seen:
                return
            seen.add(cursor)
            query["cursor"] = cursor


# ---- sync -------------------------------------------------------------------


class Collections(_Resource):
    """Mobile money push payments (``/v1/collections``)."""

    _client: "TeePay"

    def create(
        self,
        *,
        money: CollectionMoneyParam,
        customer: CollectionCustomerParam,
        description: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
    ) -> TeePayObject:
        """Send a USSD payment prompt. 202 = accepted, not paid: read it or wait for the webhook."""
        return self._client._request(_opts(_collection_create(money, customer, description, idempotency_key), timeout, max_retries))

    def retrieve(self, reference: str, *, timeout: Optional[float] = None, max_retries: Optional[int] = None) -> TeePayObject:
        """One collection by its ``public_reference``."""
        return self._client._request(_opts(RequestSpec("GET", "/v1/collections/" + encode_path(reference, "reference")), timeout, max_retries))

    def list(
        self,
        *,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
        status: Optional[str] = None,
        currency: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
    ) -> TeePayObject:
        """One page: ``{"items": [...], "next_cursor": ...}``."""
        return self._client._request(_opts(_transaction_list("/v1/collections", limit, cursor, status, currency), timeout, max_retries))

    def list_all(
        self,
        *,
        limit: Optional[int] = None,
        status: Optional[str] = None,
        currency: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
    ) -> Iterator[TeePayObject]:
        """Iterate over every collection, following ``next_cursor``."""
        return self._iterate(_opts(_transaction_list("/v1/collections", limit, None, status, currency), timeout, max_retries))


class Disbursements(_Resource):
    """Payouts (``/v1/disbursements``)."""

    _client: "TeePay"

    def quote(
        self,
        *,
        money: PayoutMoneyParam,
        destination: PayoutDestinationParam,
        narration: str,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
    ) -> TeePayObject:
        """Price a payout. Expires after two minutes; never moves money."""
        return self._client._request(_opts(_quote(money, destination, narration), timeout, max_retries))

    def create(
        self,
        *,
        quote_id: str,
        idempotency_key: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
    ) -> TeePayObject:
        """Confirm a quote. The key goes in the body; derive it from your own payout record."""
        return self._client._request(_opts(_payout_create(quote_id, idempotency_key), timeout, max_retries))

    def retrieve(self, reference: str, *, timeout: Optional[float] = None, max_retries: Optional[int] = None) -> TeePayObject:
        return self._client._request(_opts(RequestSpec("GET", "/v1/disbursements/" + encode_path(reference, "reference")), timeout, max_retries))

    def list(
        self,
        *,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
        status: Optional[str] = None,
        currency: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
    ) -> TeePayObject:
        return self._client._request(_opts(_transaction_list("/v1/disbursements", limit, cursor, status, currency), timeout, max_retries))

    def list_all(
        self,
        *,
        limit: Optional[int] = None,
        status: Optional[str] = None,
        currency: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
    ) -> Iterator[TeePayObject]:
        return self._iterate(_opts(_transaction_list("/v1/disbursements", limit, None, status, currency), timeout, max_retries))


class ControlNumbers(_Resource):
    """Tanzanian Control Numbers (``/v1/control-numbers``)."""

    _client: "TeePay"

    def create(
        self,
        *,
        kind: str,
        customer: ControlNumberCustomerParam,
        description: Optional[str] = None,
        amount_minor: Any = None,
        maximum_minor: Any = None,
        payment_mode: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
    ) -> TeePayObject:
        """201 = issued; 202 = pending (``number`` is ``None``): call again with the SAME idempotency key."""
        spec = _control_number_create(kind, customer, description, amount_minor, maximum_minor, payment_mode, idempotency_key)
        return self._client._request(_opts(spec, timeout, max_retries))

    def retrieve(self, id: str, *, timeout: Optional[float] = None, max_retries: Optional[int] = None) -> TeePayObject:  # noqa: A002
        return self._client._request(_opts(RequestSpec("GET", "/v1/control-numbers/" + encode_path(id, "id")), timeout, max_retries))

    def list(self, *, cursor: Optional[str] = None, timeout: Optional[float] = None, max_retries: Optional[int] = None) -> TeePayObject:
        """One page: ``{"object": "list", "data": [...], "next_cursor": ...}``."""
        return self._client._request(_opts(RequestSpec("GET", "/v1/control-numbers", query={"cursor": cursor}), timeout, max_retries))

    def list_all(self, *, timeout: Optional[float] = None, max_retries: Optional[int] = None) -> Iterator[TeePayObject]:
        return self._iterate(_opts(RequestSpec("GET", "/v1/control-numbers", query={}), timeout, max_retries))


class CheckoutSessions(_Resource):
    """TeePay hosted checkout (``/v1/checkout-sessions``)."""

    _client: "TeePay"

    def create(
        self,
        *,
        title: str,
        amount_minor: Any,
        currency: str,
        description: Optional[str] = None,
        expires_in: Optional[int] = None,
        payment_profile_id: Optional[str] = None,
        reference: Optional[str] = None,
        metadata: Optional[Mapping[str, str]] = None,
        idempotency_key: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
    ) -> TeePayObject:
        """Create a hosted checkout; redirect the customer to ``checkout_url``."""
        spec = _checkout_create(title, amount_minor, currency, description, expires_in, payment_profile_id, reference, metadata, idempotency_key)
        return self._client._request(_opts(spec, timeout, max_retries))

    def retrieve(self, id: str, *, timeout: Optional[float] = None, max_retries: Optional[int] = None) -> TeePayObject:  # noqa: A002
        return self._client._request(_opts(RequestSpec("GET", "/v1/checkout-sessions/" + encode_path(id, "id")), timeout, max_retries))

    def list(
        self,
        *,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
    ) -> TeePayObject:
        return self._client._request(_opts(RequestSpec("GET", "/v1/checkout-sessions", query={"limit": limit, "cursor": cursor}), timeout, max_retries))

    def list_all(self, *, limit: Optional[int] = None, timeout: Optional[float] = None, max_retries: Optional[int] = None) -> Iterator[TeePayObject]:
        return self._iterate(_opts(RequestSpec("GET", "/v1/checkout-sessions", query={"limit": limit}), timeout, max_retries))


# ---- async ------------------------------------------------------------------


class AsyncCollections(_Resource):
    _client: "AsyncTeePay"

    async def create(
        self,
        *,
        money: CollectionMoneyParam,
        customer: CollectionCustomerParam,
        description: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
    ) -> TeePayObject:
        return await self._client._request(_opts(_collection_create(money, customer, description, idempotency_key), timeout, max_retries))

    async def retrieve(self, reference: str, *, timeout: Optional[float] = None, max_retries: Optional[int] = None) -> TeePayObject:
        return await self._client._request(_opts(RequestSpec("GET", "/v1/collections/" + encode_path(reference, "reference")), timeout, max_retries))

    async def list(
        self,
        *,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
        status: Optional[str] = None,
        currency: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
    ) -> TeePayObject:
        return await self._client._request(_opts(_transaction_list("/v1/collections", limit, cursor, status, currency), timeout, max_retries))

    def list_all(
        self,
        *,
        limit: Optional[int] = None,
        status: Optional[str] = None,
        currency: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
    ) -> AsyncIterator[TeePayObject]:
        return self._aiterate(_opts(_transaction_list("/v1/collections", limit, None, status, currency), timeout, max_retries))


class AsyncDisbursements(_Resource):
    _client: "AsyncTeePay"

    async def quote(
        self,
        *,
        money: PayoutMoneyParam,
        destination: PayoutDestinationParam,
        narration: str,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
    ) -> TeePayObject:
        return await self._client._request(_opts(_quote(money, destination, narration), timeout, max_retries))

    async def create(
        self,
        *,
        quote_id: str,
        idempotency_key: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
    ) -> TeePayObject:
        return await self._client._request(_opts(_payout_create(quote_id, idempotency_key), timeout, max_retries))

    async def retrieve(self, reference: str, *, timeout: Optional[float] = None, max_retries: Optional[int] = None) -> TeePayObject:
        return await self._client._request(_opts(RequestSpec("GET", "/v1/disbursements/" + encode_path(reference, "reference")), timeout, max_retries))

    async def list(
        self,
        *,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
        status: Optional[str] = None,
        currency: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
    ) -> TeePayObject:
        return await self._client._request(_opts(_transaction_list("/v1/disbursements", limit, cursor, status, currency), timeout, max_retries))

    def list_all(
        self,
        *,
        limit: Optional[int] = None,
        status: Optional[str] = None,
        currency: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
    ) -> AsyncIterator[TeePayObject]:
        return self._aiterate(_opts(_transaction_list("/v1/disbursements", limit, None, status, currency), timeout, max_retries))


class AsyncControlNumbers(_Resource):
    _client: "AsyncTeePay"

    async def create(
        self,
        *,
        kind: str,
        customer: ControlNumberCustomerParam,
        description: Optional[str] = None,
        amount_minor: Any = None,
        maximum_minor: Any = None,
        payment_mode: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
    ) -> TeePayObject:
        spec = _control_number_create(kind, customer, description, amount_minor, maximum_minor, payment_mode, idempotency_key)
        return await self._client._request(_opts(spec, timeout, max_retries))

    async def retrieve(self, id: str, *, timeout: Optional[float] = None, max_retries: Optional[int] = None) -> TeePayObject:  # noqa: A002
        return await self._client._request(_opts(RequestSpec("GET", "/v1/control-numbers/" + encode_path(id, "id")), timeout, max_retries))

    async def list(self, *, cursor: Optional[str] = None, timeout: Optional[float] = None, max_retries: Optional[int] = None) -> TeePayObject:
        return await self._client._request(_opts(RequestSpec("GET", "/v1/control-numbers", query={"cursor": cursor}), timeout, max_retries))

    def list_all(self, *, timeout: Optional[float] = None, max_retries: Optional[int] = None) -> AsyncIterator[TeePayObject]:
        return self._aiterate(_opts(RequestSpec("GET", "/v1/control-numbers", query={}), timeout, max_retries))


class AsyncCheckoutSessions(_Resource):
    _client: "AsyncTeePay"

    async def create(
        self,
        *,
        title: str,
        amount_minor: Any,
        currency: str,
        description: Optional[str] = None,
        expires_in: Optional[int] = None,
        payment_profile_id: Optional[str] = None,
        reference: Optional[str] = None,
        metadata: Optional[Mapping[str, str]] = None,
        idempotency_key: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
    ) -> TeePayObject:
        spec = _checkout_create(title, amount_minor, currency, description, expires_in, payment_profile_id, reference, metadata, idempotency_key)
        return await self._client._request(_opts(spec, timeout, max_retries))

    async def retrieve(self, id: str, *, timeout: Optional[float] = None, max_retries: Optional[int] = None) -> TeePayObject:  # noqa: A002
        return await self._client._request(_opts(RequestSpec("GET", "/v1/checkout-sessions/" + encode_path(id, "id")), timeout, max_retries))

    async def list(
        self,
        *,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
    ) -> TeePayObject:
        return await self._client._request(_opts(RequestSpec("GET", "/v1/checkout-sessions", query={"limit": limit, "cursor": cursor}), timeout, max_retries))

    def list_all(self, *, limit: Optional[int] = None, timeout: Optional[float] = None, max_retries: Optional[int] = None) -> AsyncIterator[TeePayObject]:
        return self._aiterate(_opts(RequestSpec("GET", "/v1/checkout-sessions", query={"limit": limit}), timeout, max_retries))
