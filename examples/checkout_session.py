"""Create a TeePay hosted checkout and print the link to send the customer to.

    TEEPAY_API_KEY=tp_live_... python examples/checkout_session.py
"""

from teepay import TeePay


def main() -> None:
    with TeePay() as teepay:
        session = teepay.checkout_sessions.create(
            title="Order 1001",
            description="2 x Coffee bag",
            amount_minor="500000",  # TZS 5,000.00
            currency="TZS",
            expires_in=3600,
            reference="order-1001",
            metadata={"cart": "c-77"},
            idempotency_key="checkout-order-1001",
        )
        print("Redirect the customer to:", session.checkout_url)
        if session.last_response.idempotent_replayed:
            print("(same session as an earlier call with this key)")

        # Fulfil only when the session is paid: from the payment.completed webhook or a read.
        session = teepay.checkout_sessions.retrieve(session.id)
        print("Status:", session.status)


if __name__ == "__main__":
    main()
