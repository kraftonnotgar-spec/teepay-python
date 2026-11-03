# TeePay Python SDK

[![CI](https://github.com/kraftonnotgar-spec/teepay-python/actions/workflows/ci.yml/badge.svg)](https://github.com/kraftonnotgar-spec/teepay-python/actions/workflows/ci.yml) [![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

The official Python library for the [TeePay API](https://docs.teepay.me): mobile money push payments,
hosted checkout sessions, Control Numbers, payouts and webhook verification.

- Sync (`TeePay`) and async (`AsyncTeePay`) clients built on `httpx`, the only runtime dependency
- Automatic idempotency keys and safe retries with backoff
- Typed errors, response metadata (request ID, rate limits) and `py.typed` hints
- Constant-time webhook signature verification

Python 3.9 or newer.

## Install

```bash
pip install teepay
```

## Quickstart

Create a secret API key in the TeePay dashboard (**Developers → API keys**) and keep it on your server.

```python
import os
from teepay import TeePay

teepay = TeePay(os.environ["TEEPAY_API_KEY"])  # or TeePay() to read TEEPAY_API_KEY

caps = teepay.capabilities()
print(caps.environment, caps.features.collection_create, caps.supported_currencies)
```

### Mobile money push (USSD prompt)

```python
payment = teepay.collections.create(
    money={"amount_minor": "500000", "currency": "TZS"},  # TZS 5,000.00
    customer={"country": "TZ", "phone": "+255712345678", "name": "Asha Juma"},
    description="Order 1001",
    idempotency_key="order-1001",
)
print(payment.public_reference, payment.status)  # "TP8K2M4QZ1", "pending"

# 202 means the prompt was sent, not that the customer paid.
# Wait for the payment.completed webhook, or poll:
latest = teepay.collections.retrieve(payment.public_reference)
if latest.status == "succeeded":
    fulfil_order()
```

### Hosted checkout session

```python
session = teepay.checkout_sessions.create(
    title="Order 1001",
    description="2 x Coffee bag",
    amount_minor="500000",
    currency="TZS",
    reference="order-1001",
    metadata={"cart": "c-77"},
    idempotency_key="checkout-order-1001",
)
redirect(session.checkout_url)

# Later: status becomes "paid" only after TeePay verified the payment.
session = teepay.checkout_sessions.retrieve(session.id)
if session.status == "paid":
    print(session.payment.reference)
```

### Control Numbers and payouts

```python
number = teepay.control_numbers.create(
    kind="bill",
    customer={"name": "Asha Juma", "phone": "0712345678"},
    description="School fees, term 1",
    amount_minor="5000000",
    idempotency_key="invoice-2026-0077",
)
if number.last_response.status == 202:  # still being issued
    ...  # call create again later with the SAME idempotency_key

quote = teepay.disbursements.quote(
    money={"amount": 2500000, "currency": "TZS"},
    destination={"channel": "mobile", "name": "Juma Ali", "phone": "255712345678"},
    narration="Supplier payment October",
)
payout = teepay.disbursements.create(quote_id=quote.id, idempotency_key="payout-2026-10-0001")
```

### Lists and pagination

```python
page = teepay.collections.list(limit=50, status="succeeded")
for item in page["items"]:
    print(item.public_reference)

for payment in teepay.collections.list_all(status="succeeded"):  # follows next_cursor
    print(payment.public_reference)
```

Results are `TeePayObject`s: ordinary `dict`s with attribute access (`obj.status == obj["status"]`).
Field names are the API's own. Use brackets for names that are also `dict` methods, such as
`page["items"]`. Control Number lists put their rows in `page["data"]`.

### Async

```python
import asyncio
from teepay import AsyncTeePay

async def main() -> None:
    async with AsyncTeePay() as teepay:
        session = await teepay.checkout_sessions.create(title="Order 1001", amount_minor="500000", currency="TZS")
        print(session.checkout_url)
        async for payment in teepay.collections.list_all():
            print(payment.public_reference)

asyncio.run(main())
```

## Verify webhooks

TeePay signs every webhook with your signing secret (`whsec_...`, from **Developers → Webhooks**).
Verify the **raw request body** before trusting it; `verify_webhook` checks the
`X-TeePay-Signature` HMAC in constant time and rejects timestamps more than 5 minutes away.

Flask:

```python
import os
from flask import Flask, request
from teepay import WebhookVerificationError, verify_webhook

app = Flask(__name__)

@app.post("/webhooks/teepay")
def teepay_webhook():
    try:
        event = verify_webhook(request.get_data(), request.headers, os.environ["TEEPAY_WEBHOOK_SECRET"])
    except WebhookVerificationError:
        return "", 400
    if event.event == "payment.completed":
        mark_paid(event.data.reference)  # de-duplicate on event.id
    return "", 200
```

FastAPI:

```python
import os
from fastapi import FastAPI, HTTPException, Request
from teepay import WebhookVerificationError, verify_webhook

app = FastAPI()

@app.post("/webhooks/teepay")
async def teepay_webhook(request: Request):
    try:
        event = verify_webhook(await request.body(), request.headers, os.environ["TEEPAY_WEBHOOK_SECRET"])
    except WebhookVerificationError:
        raise HTTPException(status_code=400)
    ...
    return {"ok": True}
```

`teepay.webhooks.verify(...)` on a client does the same. Use `generate_test_headers(payload, secret)`
to build signed requests in your own tests.

## Errors

```python
from teepay import (
    AccountRestrictedError, ApiError, ConnectionError, PermissionError,
    RateLimitError, ValidationError,
)

try:
    teepay.collections.create(...)
except ValidationError as e:          # 422: e.code is invalid_request, unsupported_market, invalid_amount, ...
    print(e.code, e.message)
except AccountRestrictedError:        # 403 account_restricted: contact TeePay support
    ...
except PermissionError as e:          # 403 scope_denied / access_denied
    ...
except RateLimitError as e:           # 429 after retries; wait e.retry_after seconds
    ...
except ConnectionError:               # network error or timeout: the payment may still exist
    ...                               # retry with the SAME idempotency key, or read it
except ApiError as e:                 # anything else, e.g. 503
    print(e.status, e.code, e.request_id)
```

| Exception | When |
|---|---|
| `AuthenticationError` | 401 invalid, revoked, expired or wrong-environment key |
| `PermissionError` (`PermissionDeniedError`) | 403 `scope_denied`, `access_denied`, `developer_access_denied` |
| `AccountRestrictedError` | 403 `account_restricted` (subclass of `PermissionError`) |
| `NotFoundError` | 404 |
| `ConflictError` | 409 `idempotency_conflict`, payout quote expired |
| `ValidationError` | 400/422 |
| `RateLimitError` | 429 (`retry_after`) |
| `ApiError` | base class of the above; also 5xx |
| `ConnectionError` / `TimeoutError` | no response (aliases `APIConnectionError`, `APITimeoutError`) |
| `WebhookVerificationError` | webhook signature or timestamp invalid |

All inherit from `TeePayError`. Every `ApiError` has `status`, `code`, `message`, `request_id`,
`headers`, `body` and `retry_after`. Quote `request_id` when you contact support. `PermissionError`,
`ConnectionError` and `TimeoutError` shadow Python built-ins if you import them by name; use the aliases
or `teepay.PermissionError` if you prefer.

TeePay rejects request JSON whose object keys are not all lowercase (metadata keys included); the SDK
checks this before sending and raises `ValueError`.

## Idempotency and retries

- `collections.create`, `checkout_sessions.create` and `control_numbers.create` send an
  `Idempotency-Key` header; `disbursements.create` sends `idempotency_key` in the body.
- If you do not pass `idempotency_key=...`, the SDK generates one (`sdk-<uuid>`) per call and reuses it
  for that call's retries. **Prefer keys derived from your own records** (`order-1001`) so a retry after
  your process restarts cannot create a second payment.
- Same key + same body returns the original result (`obj.last_response.idempotent_replayed` is `True`
  for replayed checkout sessions). Same key + different body raises `ConflictError`.
- The SDK retries (default 2 times, exponential backoff with jitter, honouring `Retry-After`) only when
  it is safe: `GET`s and keyed creates on connection errors, timeouts, 408, 429 and 5xx. A payout
  quote is retried only on 429. Other 4xx errors are never retried.

```python
teepay = TeePay(timeout=20, max_retries=3)
teepay.collections.retrieve("TP8K2M4QZ1", timeout=5, max_retries=0)  # per request
```

## Response metadata

```python
payment = teepay.collections.create(...)
info = payment.last_response
info.status               # 202
info.request_id           # for support
info.rate_limit           # RateLimit(limit=120, remaining=117, reset=42)
info.idempotent_replayed  # True when TeePay replayed an earlier result
```

## Sandbox and live

| Key prefix | `teepay.environment` | Use |
|---|---|---|
| `tp_test_` | `sandbox` | Authentication, scopes, capability discovery and error handling |
| `tp_live_` | `live` | Real money |

Both use `https://api.teepay.me`; the key decides the environment. Money movement (mobile money push,
checkout, Control Numbers, payouts) currently runs in live only, so check `teepay.capabilities()` to see
what a key can do. Pass `api_version="2026-10-18"` to send a `TeePay-Version` header and have requests
rejected if that version is no longer served.

**Never** put a secret key in a browser, mobile app or public repository. The client never logs and
hides the key from `repr()`.

## Configuration

| Argument | Default | |
|---|---|---|
| `api_key` | `TEEPAY_API_KEY` env | `tp_test_...` or `tp_live_...` |
| `base_url` | `https://api.teepay.me` | |
| `timeout` | `30.0` | seconds per attempt |
| `max_retries` | `2` | |
| `api_version` | `None` | sends `TeePay-Version` when set |
| `http_client` | new `httpx.Client` / `httpx.AsyncClient` | bring your own (proxies, transports) |

## Development

```bash
pip install -e ".[dev]"
pytest
```

The tests run against a local mock server that replays responses from the public OpenAPI contract,
and a contract test checks that every public API operation is covered.

## License

MIT
