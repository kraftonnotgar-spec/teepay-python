"""Typed shapes of TeePay request parameters and responses.

Responses are returned as :class:`teepay.TeePayObject` (a ``dict``); these
``TypedDict`` definitions document their keys for editors and type checkers.
"""

from __future__ import annotations

from typing import Dict, List, Literal, Optional, TypedDict, Union

__all__ = [
    "AmountMinor",
    "CollectionMoneyParam",
    "CollectionCustomerParam",
    "ControlNumberCustomerParam",
    "PayoutMoneyParam",
    "MobileDestinationParam",
    "BankDestinationParam",
    "PayoutDestinationParam",
    "Money",
    "Collection",
    "Transaction",
    "TransactionPage",
    "Whoami",
    "Capabilities",
    "CapabilityFeatures",
    "PayoutQuote",
    "Payout",
    "ControlNumberCreated",
    "ControlNumber",
    "ControlNumberPayment",
    "ControlNumberDetail",
    "ControlNumberPage",
    "CheckoutSession",
    "CheckoutSessionPage",
    "WebhookEvent",
    "TransactionStatus",
    "CheckoutSessionStatus",
    "Environment",
]

AmountMinor = Union[str, int]
"""Integer minor units. Strings are sent as-is; ints are converted to strings."""

Environment = Literal["sandbox", "live"]
TransactionStatus = Literal["created", "pending", "processing", "succeeded", "failed", "reversed", "refunded"]
CheckoutSessionStatus = Literal["open", "processing", "paid", "expired", "unavailable"]


# ---- request params -------------------------------------------------------


class CollectionMoneyParam(TypedDict):
    amount_minor: AmountMinor
    currency: str


class _CollectionCustomerRequired(TypedDict):
    country: str
    phone: str


class CollectionCustomerParam(_CollectionCustomerRequired, total=False):
    name: str
    email: str


class ControlNumberCustomerParam(TypedDict, total=False):
    name: str
    phone: str
    email: str


class PayoutMoneyParam(TypedDict):
    amount: int
    currency: Literal["TZS"]


class MobileDestinationParam(TypedDict):
    channel: Literal["mobile"]
    name: str
    phone: str


class BankDestinationParam(TypedDict):
    channel: Literal["bank"]
    name: str
    bank: str
    account: str


PayoutDestinationParam = Union[MobileDestinationParam, BankDestinationParam]


# ---- responses ------------------------------------------------------------


class Money(TypedDict):
    amount_minor: int
    currency: str


class _CollectionRequired(TypedDict):
    id: str
    operation: Literal["charge"]
    status: TransactionStatus
    money: Money
    created_at: str
    updated_at: str


class Collection(_CollectionRequired, total=False):
    public_reference: str
    status_detail: Literal["cancelled", "expired"]


class _TransactionRequired(TypedDict):
    id: str
    operation: Literal["charge", "payout"]
    status: TransactionStatus
    money: Money
    created_at: str
    updated_at: str


class Transaction(_TransactionRequired, total=False):
    public_reference: str
    status_detail: str
    customer_name: str
    customer_phone: str
    method: str
    channel: str
    source: str
    fee: Money
    net: Money


class TransactionPage(TypedDict):
    items: List[Transaction]
    next_cursor: Optional[str]


class Whoami(TypedDict):
    application_reference: str
    environment: Environment
    scopes: List[str]
    credential_prefix: str


class CapabilityFeatures(TypedDict):
    integration_read: bool
    collection_read: bool
    disbursement_read: bool
    collection_create: bool
    disbursement_create: bool
    payments: bool
    checkout_sessions: bool
    payment_links: bool
    payment_pages: bool
    invoice_payments: bool
    payouts: bool
    beneficiaries: bool
    balances: bool
    refunds: bool
    webhook_endpoints: bool
    control_number_read: bool
    control_number_create: bool
    checkout_session_read: bool


class Capabilities(TypedDict):
    api_version: str
    environment: Environment
    release_stage: Literal["read_only", "owned_payouts", "owned_collections"]
    features: CapabilityFeatures
    supported_countries: List[str]
    supported_currencies: List[str]


class PayoutQuote(TypedDict):
    id: str
    expires_at: str
    currency: str
    amount_minor: str
    merchant_fee_minor: str
    provider_fee_minor: str
    total_minor: str


class PayoutPayoutMoney(TypedDict):
    amount_minor: int
    currency: str


class Payout(TypedDict):
    id: str
    public_reference: str
    status: TransactionStatus
    money: PayoutPayoutMoney
    fee_minor: str
    total_minor: str
    created_at: str
    updated_at: str
    destination: Dict[str, str]


class ControlNumberCreated(TypedDict):
    id: str
    object: Literal["control_number"]
    status: str
    number: Optional[str]
    currency: Literal["TZS"]


class ControlNumber(TypedDict):
    id: str
    object: Literal["control_number"]
    number: Optional[str]
    kind: Literal["bill", "customer"]
    currency: Literal["TZS"]
    amount_minor: Optional[str]
    collected_minor: Optional[str]
    remaining_minor: Optional[str]
    status: str
    payment_count: int
    created_at: str


class _ControlNumberPaymentRequired(TypedDict):
    id: str
    status: Literal["verified", "pending_verification", "under_review"]
    received_at: str


class ControlNumberPayment(_ControlNumberPaymentRequired, total=False):
    reference: str
    amount_minor: str
    fee_minor: str
    paid_at: str


class ControlNumberDetail(ControlNumber):
    payments: List[ControlNumberPayment]


class _ControlNumberPageRequired(TypedDict):
    object: Literal["list"]
    data: List[ControlNumber]
    next_cursor: Optional[str]


class ControlNumberPage(_ControlNumberPageRequired, total=False):
    can_create: bool


class CheckoutSessionPayment(TypedDict):
    reference: str


class CheckoutSession(TypedDict):
    id: str
    object: Literal["checkout_session"]
    status: CheckoutSessionStatus
    title: str
    description: str
    currency: str
    amount_minor: str
    checkout_url: Optional[str]
    payment_profile_id: Optional[str]
    reference: Optional[str]
    metadata: Dict[str, str]
    payment: Optional[CheckoutSessionPayment]
    environment: Environment
    created_at: str
    expires_at: Optional[str]


class CheckoutSessionPage(TypedDict):
    object: Literal["list"]
    items: List[CheckoutSession]
    next_cursor: Optional[str]


class WebhookEventData(TypedDict, total=False):
    reference: str
    transaction_id: str
    status: str
    occurred_at: str
    money: Dict[str, str]
    source: Optional[Dict[str, str]]


class WebhookEvent(TypedDict):
    id: str
    event: Literal[
        "payment.completed",
        "payment.failed",
        "payment.voided",
        "payment.expired",
        "payout.completed",
        "payout.failed",
        "payout.reversed",
    ]
    environment: Environment
    created_at: str
    data: WebhookEventData
