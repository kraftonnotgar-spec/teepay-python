"""Receive and verify TeePay webhooks with Flask.

    pip install flask teepay
    TEEPAY_WEBHOOK_SECRET=whsec_... flask --app examples/webhook_flask.py run --port 8000
"""

import os

from flask import Flask, request

from teepay import WebhookVerificationError, verify_webhook

app = Flask(__name__)
processed: set = set()  # use your database in production


@app.post("/webhooks/teepay")
def teepay_webhook():  # type: ignore[no-untyped-def]
    try:
        # The raw body, exactly as received: do not use request.json here.
        event = verify_webhook(request.get_data(), request.headers, os.environ["TEEPAY_WEBHOOK_SECRET"])
    except WebhookVerificationError:
        return "", 400

    if event.id in processed:  # deliveries can repeat; X-TeePay-Event-ID is stable
        return "", 200
    processed.add(event.id)

    if event.event == "payment.completed":
        print("Paid:", event.data.reference, event.data.money)
    elif event.event in ("payment.failed", "payment.expired", "payment.voided"):
        print("Not paid:", event.data.reference)
    elif event.event.startswith("payout."):
        print("Payout", event.event, event.data.reference)

    # Answer quickly with 2xx; do slow work in the background.
    return "", 200
