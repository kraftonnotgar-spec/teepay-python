from __future__ import annotations

import json
import pickle
import re

import pytest

import teepay
from teepay import (
    AccountRestrictedError,
    ApiError,
    AuthenticationError,
    ConflictError,
    ConnectionError,
    NotFoundError,
    PermissionError,
    RateLimitError,
    TeePay,
    TeePayError,
    TimeoutError,
    ValidationError,
)

from .conftest import FIXTURES, LIVE_KEY, SANDBOX_KEY

OPS = FIXTURES["operations"]
KEY_RE = re.compile(r"^sdk-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


# ---- configuration ----------------------------------------------------------


def test_environment_from_key(server):
    assert TeePay(SANDBOX_KEY, base_url=server.url).environment == "sandbox"
    assert TeePay(LIVE_KEY, base_url=server.url).environment == "live"


@pytest.mark.parametrize("bad", ["sk_live_123", "tp_prod_x", "tp_test_ abc", "", " tp_test_x"])
def test_rejects_bad_keys_without_echoing_them(bad):
    with pytest.raises(TeePayError) as exc:
        TeePay(bad)
    if bad.strip():
        assert bad.strip() not in str(exc.value)


def test_key_from_environment(monkeypatch, server):
    monkeypatch.setenv("TEEPAY_API_KEY", LIVE_KEY)
    c = TeePay(base_url=server.url)
    assert c.environment == "live"
    c.whoami()
    assert server.last["headers"]["authorization"] == f"Bearer {LIVE_KEY}"


def test_missing_key(monkeypatch):
    monkeypatch.delenv("TEEPAY_API_KEY", raising=False)
    with pytest.raises(TeePayError, match="TEEPAY_API_KEY"):
        TeePay()


def test_key_is_redacted(client):
    assert "mocksecret" not in repr(client)
    assert "tp_test_" not in repr(client)
    assert "mocksecret" not in str(client)
    with pytest.raises(TypeError):
        pickle.dumps(client)


def test_invalid_options():
    with pytest.raises(TeePayError):
        TeePay(SANDBOX_KEY, timeout=0)
    with pytest.raises(TeePayError):
        TeePay(SANDBOX_KEY, max_retries=-1)


def test_default_base_url():
    c = TeePay(SANDBOX_KEY)
    assert c.base_url == "https://api.teepay.me"
    assert teepay.DEFAULT_BASE_URL == "https://api.teepay.me"
    c.close()


# ---- headers ------------------------------------------------------------------


def test_auth_and_standard_headers(client, server):
    client.whoami()
    h = server.last["headers"]
    assert h["authorization"] == f"Bearer {SANDBOX_KEY}"
    assert "x-api-key" not in h
    assert h["accept"] == "application/json"
    assert h["user-agent"].startswith("teepay-python/0.1.0 python/")
    assert "teepay-version" not in h
    assert "idempotency-key" not in h
    assert "content-type" not in h
    assert sum(1 for k, _ in server.last["header_list"] if k.lower() == "authorization") == 1


def test_api_version_header(server):
    c = TeePay(SANDBOX_KEY, base_url=server.url, api_version="2026-10-18")
    c.whoami()
    assert server.last["headers"]["teepay-version"] == "2026-10-18"


def test_get_requests_have_no_query_when_unused(client, server):
    client.capabilities()
    assert server.last["query"] == {}
    assert server.last["path"] == "/v1/capabilities"


# ---- responses --------------------------------------------------------------


def test_whoami(client):
    me = client.whoami()
    assert me == OPS["get-api-key"]["body"]
    assert me.environment == "sandbox"
    assert isinstance(me, teepay.TeePayObject)


def test_capabilities_attribute_access(client):
    caps = client.capabilities()
    assert caps.features.collection_create is True
    assert caps["supported_countries"] == ["TZ"]
    with pytest.raises(AttributeError):
        caps.nope  # noqa: B018
    assert json.loads(json.dumps(caps)) == OPS["get-capabilities"]["body"]
    assert caps.to_dict() == OPS["get-capabilities"]["body"]
    assert type(caps.to_dict()["features"]) is dict


def test_response_metadata(client, server):
    caps = client.capabilities()
    info = caps.last_response
    assert info.status == 200
    assert info.request_id == "req_mock"
    assert info.rate_limit == teepay.RateLimit(limit=120, remaining=119, reset=60)
    assert info.api_version == "2026-10-18"
    assert info.idempotent_replayed is False


def test_idempotent_replayed(client, server):
    server.queue({"headers": {"Idempotent-Replayed": "true"}})
    session = client.checkout_sessions.create(title="Order 1001", amount_minor="500000", currency="TZS", idempotency_key="order-1001")
    assert session.last_response.idempotent_replayed is True
    assert session.last_response.status == 201


# ---- collections ------------------------------------------------------------


def test_collection_create(client, server):
    payment = client.collections.create(
        money={"amount_minor": 500000, "currency": "TZS"},
        customer={"country": "TZ", "phone": "+255712345678", "name": "Asha Juma"},
        description="Order 1001",
        idempotency_key="order-1001",
    )
    assert payment.public_reference == "TP8K2M4QZ1"
    assert payment.last_response.status == 202
    req = server.last
    assert req["method"] == "POST" and req["path"] == "/v1/collections"
    assert req["headers"]["idempotency-key"] == "order-1001"
    assert req["headers"]["content-type"] == "application/json"
    assert req["body"] == {
        "money": {"amount_minor": "500000", "currency": "TZS"},
        "customer": {"country": "TZ", "phone": "+255712345678", "name": "Asha Juma"},
        "description": "Order 1001",
    }


def test_collection_auto_idempotency_key_and_none_dropped(client, server):
    client.collections.create(money={"amount_minor": "1000", "currency": "TZS"}, customer={"country": "TZ", "phone": "+255712345678"})
    key = server.last["headers"]["idempotency-key"]
    assert KEY_RE.match(key) and len(key) == 40
    assert "description" not in server.last["body"]
    client.collections.create(money={"amount_minor": "1000", "currency": "TZS"}, customer={"country": "TZ", "phone": "+255712345678"})
    assert server.last["headers"]["idempotency-key"] != key


def test_collection_retrieve_encodes_path(client, server):
    client.collections.retrieve("TP8K2M4QZ1")
    assert server.last["path"] == "/v1/collections/TP8K2M4QZ1"
    client.collections.retrieve("a/b?c")
    assert server.last["path"] == "/v1/collections/a%2Fb%3Fc"


def test_empty_path_param(client, server):
    with pytest.raises(ValueError):
        client.collections.retrieve("")
    with pytest.raises(ValueError):
        client.checkout_sessions.retrieve(None)  # type: ignore[arg-type]
    assert server.requests == []


def test_collection_list_query(client, server):
    page = client.collections.list(limit=50, status="succeeded", currency="TZS")
    assert server.last["query"] == {"limit": "50", "status": "succeeded", "currency": "TZS"}
    assert page["items"][0]["money"]["amount_minor"] == 500000
    assert page.next_cursor is None


def test_list_all_follows_cursor(client, server):
    first = {"items": [{"id": "a"}], "next_cursor": "c1"}
    second = {"items": [{"id": "b"}], "next_cursor": None}
    server.queue({"status": 200, "body": first}, {"status": 200, "body": second})
    ids = [item.id for item in client.collections.list_all(limit=1, status="succeeded")]
    assert ids == ["a", "b"]
    assert server.requests[0]["query"] == {"limit": "1", "status": "succeeded"}
    assert server.requests[1]["query"] == {"limit": "1", "status": "succeeded", "cursor": "c1"}


def test_list_all_stops_on_repeated_cursor(client, server):
    page = {"items": [{"id": "a"}], "next_cursor": "same"}
    server.queue({"status": 200, "body": page}, {"status": 200, "body": page})
    assert len(list(client.disbursements.list_all())) == 2
    assert len(server.requests) == 2


def test_control_numbers_list_all_uses_data_field(client, server):
    server.queue(
        {"status": 200, "body": {"object": "list", "data": [{"id": "x"}], "next_cursor": "11111111-1111-4111-8111-111111111111"}},
        {"status": 200, "body": {"object": "list", "data": [{"id": "y"}], "next_cursor": None}},
    )
    assert [n.id for n in client.control_numbers.list_all()] == ["x", "y"]
    assert server.requests[1]["query"] == {"cursor": "11111111-1111-4111-8111-111111111111"}


# ---- request body rules -------------------------------------------------------


def test_uppercase_keys_rejected_locally(client, server):
    with pytest.raises(ValueError, match="metadata.Cart"):
        client.checkout_sessions.create(title="x", amount_minor="100", currency="TZS", metadata={"Cart": "1"})
    assert server.requests == []


def test_bool_amount_rejected(client):
    with pytest.raises(ValueError):
        client.checkout_sessions.create(title="x", amount_minor=True, currency="TZS")


def test_checkout_session_create(client, server):
    session = client.checkout_sessions.create(
        title="Order 1001",
        description="2 x Coffee bag",
        amount_minor=500000,
        currency="TZS",
        expires_in=86400,
        reference="order-1001",
        metadata={"cart": "c-77"},
        idempotency_key="order-1001",
    )
    assert session.checkout_url.startswith("https://")
    assert session.payment is None
    assert server.last["body"] == {
        "title": "Order 1001",
        "description": "2 x Coffee bag",
        "amount_minor": "500000",
        "currency": "TZS",
        "expires_in": 86400,
        "reference": "order-1001",
        "metadata": {"cart": "c-77"},
    }
    assert server.last["headers"]["idempotency-key"] == "order-1001"


def test_checkout_session_list(client, server):
    page = client.checkout_sessions.list(limit=10, cursor="abc")
    assert server.last["query"] == {"limit": "10", "cursor": "abc"}
    assert page["items"][0].payment.reference == "TP8K2M4QZ1"


def test_control_number_create(client, server):
    number = client.control_numbers.create(
        kind="bill",
        customer={"name": "Asha Juma", "phone": "0712345678"},
        description="School fees, term 1",
        amount_minor=5000000,
        idempotency_key="invoice-77",
    )
    assert number.number == "991234567890"
    assert server.last["body"] == {
        "kind": "bill",
        "customer": {"name": "Asha Juma", "phone": "0712345678"},
        "description": "School fees, term 1",
        "amount_minor": "5000000",
    }
    assert server.last["headers"]["idempotency-key"] == "invoice-77"


def test_control_number_pending_202(client, server):
    server.queue({"status": 202, "body": {"id": "22222222-2222-4222-8222-222222222222", "object": "control_number", "status": "pending", "number": None, "currency": "TZS"}})
    pending = client.control_numbers.create(kind="customer", customer={"name": "A"}, idempotency_key="cust-1")
    assert pending.number is None and pending.last_response.status == 202


def test_payout_quote_and_create(client, server):
    quote = client.disbursements.quote(
        money={"amount": 2500000, "currency": "TZS"},
        destination={"channel": "mobile", "name": "Juma Ali", "phone": "255712345678"},
        narration="Supplier payment October",
    )
    assert quote.total_minor == "2550000"
    assert server.last["body"]["money"] == {"amount": 2500000, "currency": "TZS"}
    assert "idempotency-key" not in server.last["headers"]
    payout = client.disbursements.create(quote_id=quote.id, idempotency_key="payout-2026-10-0001")
    assert payout.status == "processing"
    assert server.last["body"] == {"quote_id": "q_4f2c8a1b", "idempotency_key": "payout-2026-10-0001"}
    assert "idempotency-key" not in server.last["headers"]


def test_payout_create_generates_body_key(client, server):
    client.disbursements.create(quote_id="q_1")
    assert KEY_RE.match(server.last["body"]["idempotency_key"])


# ---- errors -----------------------------------------------------------------


@pytest.mark.parametrize(
    "fixture,cls,code",
    [
        ("invalid_credential", AuthenticationError, "invalid_credential"),
        ("scope_denied", PermissionError, "scope_denied"),
        ("access_denied", PermissionError, "access_denied"),
        ("account_restricted", AccountRestrictedError, "account_restricted"),
        ("not_found", NotFoundError, "not_found"),
        ("idempotency_conflict", ConflictError, "idempotency_conflict"),
        ("invalid_request", ValidationError, "invalid_request"),
        ("unsupported_market", ValidationError, "unsupported_market"),
        ("funds_under_review", ValidationError, "funds_under_review"),
    ],
)
def test_error_mapping(client, server, fixture, cls, code):
    server.queue({"error": fixture})
    with pytest.raises(cls) as exc:
        client.whoami()
    err = exc.value
    assert isinstance(err, ApiError) and isinstance(err, TeePayError)
    assert err.code == code
    assert err.status == FIXTURES["errors"][fixture]["status"]
    assert err.message
    assert "mocksecret" not in str(err)
    assert len(server.requests) == 1  # 4xx never retried


def test_account_restricted_is_permission_error(client, server):
    server.queue({"error": "account_restricted"})
    with pytest.raises(PermissionError) as exc:
        client.capabilities()
    assert exc.value.request_id == "req_403c"
    assert teepay.PermissionDeniedError is PermissionError


def test_error_request_id_from_header(client, server):
    server.queue({"error": "invalid_credential"})
    with pytest.raises(AuthenticationError) as exc:
        client.whoami()
    assert exc.value.request_id == "req_401"
    assert "req_401" in str(exc.value)


def test_code_only_error_shape(client, server):
    server.queue({"error": "payout_code_only"})
    with pytest.raises(ConflictError) as exc:
        client.disbursements.create(quote_id="q", idempotency_key="payout-key-1")
    assert exc.value.code == "payout_quote_expired_or_changed"
    assert exc.value.message  # generic fallback
    assert exc.value.request_id is None


def test_string_error_shape(client, server):
    server.queue({"error": "payout_string_error"})
    with pytest.raises(ValidationError) as exc:
        client.disbursements.quote(money={"amount": 1, "currency": "TZS"}, destination={"channel": "mobile", "name": "a", "phone": "255700000000"}, narration="x")
    assert exc.value.code == "invalid_request"


def test_non_json_error(client, server):
    server.queue({"status": 502, "body": b"<html>bad gateway</html>"}, {"status": 502, "body": b"x"}, {"status": 502, "body": b"x"})
    with pytest.raises(ApiError) as exc:
        client.whoami()
    assert exc.value.status == 502 and exc.value.code is None
    assert len(server.requests) == 3


def test_non_json_success_raises(client, server):
    server.queue({"status": 200, "body": b"not json"})
    with pytest.raises(ApiError):
        client.whoami()


def test_rate_limit_error(client, server):
    over = {"error": "rate_limited", "headers": {"Retry-After": "0"}}
    server.queue(over, over, over)
    with pytest.raises(RateLimitError) as exc:
        client.whoami()
    assert exc.value.retry_after == 0
    assert exc.value.headers["ratelimit-remaining"] == "0"
    assert len(server.requests) == 3  # 1 + 2 retries


def test_retry_after_too_long_is_not_retried(client, server):
    server.queue({"error": "rate_limited", "headers": {"Retry-After": "3600"}})
    with pytest.raises(RateLimitError) as exc:
        client.whoami()
    assert exc.value.retry_after == 3600
    assert len(server.requests) == 1


# ---- retries ----------------------------------------------------------------


def test_get_retried_on_503_then_succeeds(client, server):
    server.queue({"error": "unavailable"}, {"error": "internal_error"})
    me = client.whoami()
    assert me.application_reference == "app_7d2c91"
    assert len(server.requests) == 3


def test_post_with_key_retried_with_same_key(client, server):
    server.queue({"error": "unavailable"}, {"error": "unavailable"})
    client.collections.create(money={"amount_minor": "1000", "currency": "TZS"}, customer={"country": "TZ", "phone": "+255712345678"})
    keys = {r["headers"]["idempotency-key"] for r in server.requests}
    assert len(server.requests) == 3 and len(keys) == 1
    bodies = {r["raw_body"] for r in server.requests}
    assert len(bodies) == 1


def test_payout_create_retried_with_same_body_key(client, server):
    server.queue({"error": "unavailable"})
    client.disbursements.create(quote_id="q_1")
    assert len(server.requests) == 2
    assert server.requests[0]["body"]["idempotency_key"] == server.requests[1]["body"]["idempotency_key"]


def test_quote_not_retried_on_5xx(client, server):
    server.queue({"error": "unavailable"})
    with pytest.raises(ApiError) as exc:
        client.disbursements.quote(money={"amount": 1, "currency": "TZS"}, destination={"channel": "mobile", "name": "a", "phone": "255700000000"}, narration="x")
    assert exc.value.status == 503 and exc.value.retry_after == 0
    assert len(server.requests) == 1


def test_quote_retried_on_429(client, server):
    server.queue({"error": "rate_limited", "headers": {"Retry-After": "0"}})
    quote = client.disbursements.quote(money={"amount": 1, "currency": "TZS"}, destination={"channel": "bank", "name": "a", "bank": "CRDB", "account": "0150"}, narration="x")
    assert quote.id == "q_4f2c8a1b"
    assert len(server.requests) == 2


def test_max_retries_zero(server):
    c = TeePay(SANDBOX_KEY, base_url=server.url, max_retries=0)
    server.queue({"error": "unavailable"})
    with pytest.raises(ApiError):
        c.whoami()
    assert len(server.requests) == 1


def test_per_request_max_retries(client, server):
    server.queue({"error": "unavailable"}, {"error": "unavailable"}, {"error": "unavailable"}, {"error": "unavailable"})
    with pytest.raises(ApiError):
        client.whoami(max_retries=3)
    assert len(server.requests) == 4


def test_timeout_raises_and_retries_get(client, server):
    server.queue({"delay": 1.0}, {"delay": 1.0}, {"delay": 1.0})
    with pytest.raises(TimeoutError) as exc:
        client.whoami(timeout=0.2)
    assert isinstance(exc.value, ConnectionError)
    assert server.wait_for(3) == 3


def test_timeout_then_success_with_same_key(client, server):
    server.queue({"delay": 1.0})
    client.checkout_sessions.create(title="x", amount_minor="100", currency="TZS", timeout=0.5)
    assert server.wait_for(2) >= 2
    assert len({r["headers"]["idempotency-key"] for r in server.requests}) == 1


def test_connection_refused():
    c = TeePay(SANDBOX_KEY, base_url="http://127.0.0.1:1", max_retries=1, timeout=2)
    with pytest.raises(ConnectionError) as exc:
        c.whoami()
    assert "mocksecret" not in str(exc.value)
    assert teepay.APIConnectionError is ConnectionError


def test_dropped_connection_on_quote_not_retried(client, server):
    server.queue({"drop": True})
    with pytest.raises(ConnectionError):
        client.disbursements.quote(money={"amount": 1, "currency": "TZS"}, destination={"channel": "mobile", "name": "a", "phone": "255700000000"}, narration="x")
    assert len(server.requests) == 1


def test_dropped_connection_on_get_retried(client, server):
    server.queue({"drop": True})
    assert client.whoami().environment == "sandbox"
    assert len(server.requests) == 2


def test_context_manager(server):
    with TeePay(SANDBOX_KEY, base_url=server.url) as c:
        assert c.whoami()
    assert c._http.is_closed


def test_generate_idempotency_key():
    assert KEY_RE.match(teepay.generate_idempotency_key())
