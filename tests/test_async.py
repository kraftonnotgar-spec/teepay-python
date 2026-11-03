from __future__ import annotations

import pytest

import teepay
from teepay import AccountRestrictedError, ApiError, AsyncTeePay, ConnectionError, RateLimitError, TimeoutError

from .conftest import FIXTURES, SANDBOX_KEY


async def test_whoami_and_capabilities(aclient, server):
    me = await aclient.whoami()
    assert me == FIXTURES["operations"]["get-api-key"]["body"]
    caps = await aclient.capabilities()
    assert caps.features.checkout_sessions is True
    assert server.last["headers"]["authorization"] == f"Bearer {SANDBOX_KEY}"
    assert "x-api-key" not in server.last["headers"]


async def test_collections(aclient, server):
    payment = await aclient.collections.create(
        money={"amount_minor": 500000, "currency": "TZS"},
        customer={"country": "TZ", "phone": "+255712345678"},
        idempotency_key="order-1001",
    )
    assert payment.status == "pending" and payment.last_response.status == 202
    assert server.last["body"]["money"]["amount_minor"] == "500000"
    assert server.last["headers"]["idempotency-key"] == "order-1001"
    got = await aclient.collections.retrieve("TP8K2M4QZ1")
    assert got.status == "succeeded"
    page = await aclient.collections.list(limit=5)
    assert server.last["query"] == {"limit": "5"}
    assert page.next_cursor is None


async def test_list_all_async(aclient, server):
    server.queue(
        {"status": 200, "body": {"object": "list", "items": [{"id": "a"}], "next_cursor": "n1"}},
        {"status": 200, "body": {"object": "list", "items": [{"id": "b"}], "next_cursor": None}},
    )
    ids = [s.id async for s in aclient.checkout_sessions.list_all(limit=1)]
    assert ids == ["a", "b"]
    assert server.requests[1]["query"] == {"limit": "1", "cursor": "n1"}


async def test_list_all_async_all_resources(aclient, server):
    assert [c.id async for c in aclient.collections.list_all()] == ["pay_6b1f0c2d"]
    assert [d.id async for d in aclient.disbursements.list_all()] == ["pyt_91ab33"]
    assert [n.id async for n in aclient.control_numbers.list_all()] == ["22222222-2222-4222-8222-222222222222"]


async def test_payouts_async(aclient, server):
    quote = await aclient.disbursements.quote(
        money={"amount": 2500000, "currency": "TZS"},
        destination={"channel": "mobile", "name": "Juma Ali", "phone": "255712345678"},
        narration="Supplier payment",
    )
    payout = await aclient.disbursements.create(quote_id=quote.id)
    assert payout.public_reference == "TPPO7Q2X9D"
    assert server.last["body"]["idempotency_key"].startswith("sdk-")
    assert (await aclient.disbursements.retrieve("TPPO7Q2X9D")).operation == "payout"
    assert (await aclient.disbursements.list(status="succeeded"))["items"][0].status == "succeeded"


async def test_control_numbers_and_checkout_async(aclient, server):
    number = await aclient.control_numbers.create(kind="bill", customer={"name": "A"}, amount_minor="5000000")
    assert number.number == "991234567890"
    assert server.last["headers"]["idempotency-key"].startswith("sdk-")
    detail = await aclient.control_numbers.retrieve(number.id)
    assert detail.payments[0].status == "verified"
    assert (await aclient.control_numbers.list()).data[0].kind == "bill"
    session = await aclient.checkout_sessions.create(title="Order", amount_minor=100, currency="TZS")
    assert session.object == "checkout_session"
    assert (await aclient.checkout_sessions.retrieve(session.id)).status == "paid"
    assert (await aclient.checkout_sessions.list()).object == "list"


async def test_async_errors_and_retries(aclient, server):
    server.queue({"error": "account_restricted"})
    with pytest.raises(AccountRestrictedError):
        await aclient.whoami()
    server.queue({"error": "unavailable"}, {"error": "unavailable"})
    await aclient.checkout_sessions.create(title="x", amount_minor="1", currency="TZS")
    created = [r for r in server.requests if r["method"] == "POST"]
    assert len(created) == 3 and len({r["headers"]["idempotency-key"] for r in created}) == 1
    server.queue({"error": "unavailable"})
    with pytest.raises(ApiError):
        await aclient.disbursements.quote(money={"amount": 1, "currency": "TZS"}, destination={"channel": "mobile", "name": "a", "phone": "255700000000"}, narration="x")
    over = {"error": "rate_limited", "headers": {"Retry-After": "0"}}
    server.queue(over, over, over)
    with pytest.raises(RateLimitError):
        await aclient.capabilities()


async def test_async_timeout(aclient, server):
    server.queue({"delay": 1.0}, {"delay": 1.0}, {"delay": 1.0})
    with pytest.raises(TimeoutError):
        await aclient.whoami(timeout=0.2)


async def test_async_connection_error():
    async with AsyncTeePay(SANDBOX_KEY, base_url="http://127.0.0.1:1", max_retries=0) as c:
        with pytest.raises(ConnectionError):
            await c.whoami()


async def test_async_local_validation(aclient, server):
    with pytest.raises(ValueError):
        await aclient.checkout_sessions.create(title="x", amount_minor="1", currency="TZS", metadata={"OrderId": "1"})
    with pytest.raises(ValueError):
        await aclient.collections.retrieve("")
    assert server.requests == []


async def test_async_repr_and_webhooks(aclient):
    assert "mocksecret" not in repr(aclient)
    assert isinstance(aclient.webhooks, teepay.webhooks.Webhooks)
