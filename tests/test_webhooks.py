from __future__ import annotations

import json

import pytest

import teepay
from teepay import TeePay, WebhookVerificationError, compute_signature, generate_test_headers, verify_webhook

from .conftest import FIXTURES, SANDBOX_KEY

W = FIXTURES["webhook"]
BODY = W["body"].encode()
TS = W["timestamp"]
SECRET = W["secret"]
HEADERS = {
    "X-TeePay-Event-ID": "0f8d7c2e-5b1a-5e3f-9c4d-7a6b2e1f0c9d",
    "X-TeePay-Timestamp": str(TS),
    "X-TeePay-Signature": W["signature"],
}


def test_fixture_signature_matches_scheme():
    assert compute_signature(BODY, SECRET, TS) == W["signature"]


def test_verify_valid():
    event = verify_webhook(BODY, HEADERS, SECRET, now=TS + 10)
    assert event.event == "payment.completed"
    assert event.data.reference == "TP8K2M4QZ1"
    assert event.data.source.type == "checkout_session"


def test_verify_str_payload_and_lowercase_headers():
    lower = {k.lower(): v for k, v in HEADERS.items()}
    assert verify_webhook(BODY.decode(), lower, SECRET, now=TS).id == HEADERS["X-TeePay-Event-ID"]


def test_verify_list_of_pairs_and_list_values():
    pairs = [(k.encode(), v.encode()) for k, v in HEADERS.items()]
    assert verify_webhook(BODY, pairs, SECRET, now=TS)
    multi = {k: [v] for k, v in HEADERS.items()}
    assert verify_webhook(BODY, multi, SECRET, now=TS)


def test_client_webhooks_helper():
    c = TeePay(SANDBOX_KEY)
    assert c.webhooks.verify(BODY, HEADERS, SECRET, now=TS).event == "payment.completed"
    assert c.webhooks.is_valid(BODY, HEADERS, "whsec_wrong") is False


def test_tampered_body():
    with pytest.raises(WebhookVerificationError, match="signature"):
        verify_webhook(BODY.replace(b"500000", b"900000"), HEADERS, SECRET, now=TS)


def test_wrong_secret():
    with pytest.raises(WebhookVerificationError):
        verify_webhook(BODY, HEADERS, "whsec_other", now=TS)


@pytest.mark.parametrize("offset", [301, -301, 10_000])
def test_timestamp_outside_tolerance(offset):
    with pytest.raises(WebhookVerificationError, match="tolerance"):
        verify_webhook(BODY, HEADERS, SECRET, now=TS + offset)


def test_custom_tolerance():
    assert verify_webhook(BODY, HEADERS, SECRET, tolerance=1000, now=TS + 900)
    with pytest.raises(WebhookVerificationError):
        verify_webhook(BODY, HEADERS, SECRET, tolerance=5, now=TS + 6)


def test_timestamp_header_swapped_is_rejected():
    h = dict(HEADERS, **{"X-TeePay-Timestamp": str(TS + 1)})
    with pytest.raises(WebhookVerificationError):
        verify_webhook(BODY, h, SECRET, now=TS)


@pytest.mark.parametrize("value", ["", "abc", "-5", "1.5", "١٢٣"])
def test_invalid_timestamp(value):
    h = dict(HEADERS, **{"X-TeePay-Timestamp": value})
    with pytest.raises(WebhookVerificationError):
        verify_webhook(BODY, h, SECRET, now=TS)


def test_missing_headers():
    with pytest.raises(WebhookVerificationError, match="Missing"):
        verify_webhook(BODY, {}, SECRET, now=TS)
    with pytest.raises(WebhookVerificationError):
        verify_webhook(BODY, {"X-TeePay-Timestamp": str(TS)}, SECRET, now=TS)


def test_multiple_signatures_one_valid():
    h = dict(HEADERS, **{"X-TeePay-Signature": "v1=" + "0" * 64 + ", " + W["signature"]})
    assert verify_webhook(BODY, h, SECRET, now=TS)


def test_signature_without_scheme_rejected():
    h = dict(HEADERS, **{"X-TeePay-Signature": W["signature"][3:]})
    with pytest.raises(WebhookVerificationError):
        verify_webhook(BODY, h, SECRET, now=TS)


def test_parsed_payload_rejected():
    with pytest.raises(TypeError, match="raw request body"):
        verify_webhook(json.loads(BODY), HEADERS, SECRET, now=TS)  # type: ignore[arg-type]


def test_empty_secret():
    with pytest.raises(WebhookVerificationError):
        verify_webhook(BODY, HEADERS, "", now=TS)


def test_non_json_body_with_valid_signature():
    h = generate_test_headers(b"not json", SECRET, timestamp=TS)
    with pytest.raises(WebhookVerificationError, match="JSON"):
        verify_webhook(b"not json", h, SECRET, now=TS)


def test_generate_test_headers_roundtrip():
    payload = json.dumps({"id": "e1", "event": "payout.completed", "environment": "live", "created_at": "x", "data": {}})
    h = generate_test_headers(payload, SECRET)
    assert verify_webhook(payload, h, SECRET).event == "payout.completed"
    assert h["X-TeePay-Event-ID"] == "evt_test"


def test_exports():
    assert teepay.verify_webhook is verify_webhook
    assert issubclass(WebhookVerificationError, teepay.TeePayError)
