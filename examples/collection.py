"""Send a mobile money push (USSD prompt) and wait for the result.

    TEEPAY_API_KEY=tp_live_... python examples/collection.py +255712345678
"""

import sys
import time

from teepay import TeePay, ValidationError


def main() -> None:
    phone = sys.argv[1] if len(sys.argv) > 1 else "+255712345678"
    order_id = "order-1001"

    with TeePay() as teepay:
        caps = teepay.capabilities()
        if not caps.features.collection_create:
            sys.exit("Mobile money push is not enabled for this key. Check the dashboard.")

        try:
            payment = teepay.collections.create(
                money={"amount_minor": "100000", "currency": "TZS"},  # TZS 1,000.00
                customer={"country": "TZ", "phone": phone},
                description=f"Order {order_id}",
                idempotency_key=order_id,  # derived from your record: safe to retry
            )
        except ValidationError as error:
            sys.exit(f"Rejected: {error.code} ({error.message})")

        print("Prompt sent:", payment.public_reference, "- ask the customer to approve on their phone")

        # Prefer webhooks in production; poll at most every 3-5 seconds.
        for _ in range(40):
            payment = teepay.collections.retrieve(payment.public_reference)
            if payment.status in ("succeeded", "failed"):
                break
            time.sleep(4)

        print("Final status:", payment.status, payment.get("status_detail", ""))


if __name__ == "__main__":
    main()
