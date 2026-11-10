"""DB orchestration; integrate trusted order access through explicit callables."""

import logging
from collections.abc import Callable
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from .exceptions import (
    AccessDenied,
    GatewayRejected,
    GatewayUncertain,
    InvalidPayment,
    PaymentConflict,
    UnknownPayment,
)
from .models import FulfillmentEvent, Payment, PaymentAttempt, Status, transition
from .payment_adapter import PaymentGateway, validate_authority

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OrderSnapshot:
    reference: str
    amount: int  # Canonical integer IRR, loaded from server data, not a request field.
    currency: str = "IRR"
    payable: bool = True


class PaymentService:
    def __init__(
        self,
        gateway: PaymentGateway,
        order_loader: Callable,
        fulfill: Callable | None = None,
    ):
        self.gateway = gateway
        self.order_loader = order_loader
        self.fulfill = fulfill  # Same-DB writes only. External I/O belongs in the outbox consumer.

    def initiate(self, *, user, order_reference: str) -> Payment:
        if not user.is_authenticated:
            raise AccessDenied("Authentication required.")
        if not isinstance(order_reference, str) or not 1 <= len(order_reference) <= 128:
            raise InvalidPayment("Invalid order reference.")
        with transaction.atomic(durable=True):
            # Durable prevents an outer transaction from rolling back a claim after HTTP.
            # Hook must lock the order, enforce ownership, and report current payability.
            order = self.order_loader(user, order_reference)
            if (
                not isinstance(order, OrderSnapshot)
                or order.reference != order_reference
                or order.currency != "IRR"
                or type(order.amount) is not int
                or type(order.payable) is not bool
                or not 0 < order.amount <= 9_223_372_036_854_775_807
            ):
                raise InvalidPayment("Order must supply a positive integer IRR price.")
            self.gateway.validate_amount(order.amount, order.currency)
            payment, _ = Payment.objects.get_or_create(
                order_reference=order.reference,
                defaults={"owner": user, "amount": order.amount, "sandbox": self.gateway.sandbox},
            )
            payment = Payment.objects.select_for_update().get(pk=payment.pk)
            if payment.owner_id != user.pk:
                raise AccessDenied("Order access denied.")
            if (payment.amount, payment.currency, payment.sandbox) != (
                order.amount,
                order.currency,
                self.gateway.sandbox,
            ):
                raise PaymentConflict("An existing payment has a different price or environment.")
            attempt = payment.attempts.order_by("-initiated_at", "-id").first()
            if payment.status == Status.SUCCEEDED:
                return payment
            if not order.payable:
                raise PaymentConflict("Order is not payable.")
            if attempt is not None:
                if payment.status == Status.PENDING:
                    return payment
                if payment.status != Status.FAILED:
                    raise PaymentConflict("Creation is unresolved; reconcile instead of retrying.")
                transition(payment, Status.CREATED)
            payment.failure_code = None
            payment.failure_message = ""
            payment.save()
            attempt = PaymentAttempt.objects.create(payment=payment)
        # Claim is committed before HTTP; a lost response must not create a second charge.
        try:
            result = self.gateway.create_payment(
                amount=payment.amount,
                currency=payment.currency,
                description=f"Payment {payment.pk}",
            )
        except (GatewayRejected, GatewayUncertain) as error:
            with transaction.atomic():
                payment = Payment.objects.select_for_update().get(pk=payment.pk)
                attempt = PaymentAttempt.objects.get(pk=attempt.pk)
                target = Status.FAILED if isinstance(error, GatewayRejected) else Status.UNKNOWN
                for record in (payment, attempt):
                    transition(record, target)
                    record.failure_code = error.code
                    record.failure_message = (
                        "Creation rejected" if target == Status.FAILED else "Creation uncertain"
                    )
                    record.save()
                logger.warning("payment_create_unconfirmed", extra={"payment_id": str(payment.pk)})
            return payment
        with transaction.atomic():
            payment = Payment.objects.select_for_update().get(pk=payment.pk)
            attempt = PaymentAttempt.objects.get(pk=attempt.pk)
            attempt.gateway_authority = result.authority
            transition(attempt, Status.PENDING)
            transition(payment, Status.PENDING)
            attempt.save()
            payment.save()
        return payment

    def verify_callback(self, *, authority: str, callback_status: str) -> Payment:
        validate_authority(authority)
        if callback_status not in {"OK", "NOK"}:
            raise InvalidPayment("Status must be OK or NOK.")
        try:
            known_attempt = PaymentAttempt.objects.select_related("payment__owner").get(
                gateway_authority=authority
            )
        except PaymentAttempt.DoesNotExist:
            raise UnknownPayment("Unknown authority.") from None
        with transaction.atomic():
            # Lock order everywhere: application order, Payment, PaymentAttempt.
            # Loader must return paid/nonpayable orders too; duplicates still need association.
            self.order_loader(known_attempt.payment.owner, known_attempt.payment.order_reference)
            payment = Payment.objects.select_for_update().get(pk=known_attempt.payment_id)
            attempt = PaymentAttempt.objects.select_for_update().get(pk=known_attempt.pk)
            if payment.sandbox != self.gateway.sandbox:
                raise PaymentConflict("Verification environment differs from creation.")
            attempt.callback_received_at = timezone.now()
            attempt.save(update_fields=["callback_received_at"])
            if payment.status == Status.SUCCEEDED:
                return payment
            if callback_status == "NOK":
                # Untrusted cancellation is advisory; it cannot undo verification or block recovery.
                if payment.status == Status.PENDING:
                    transition(payment, Status.CANCELED)
                    transition(attempt, Status.CANCELED)
                    payment.save()
                    attempt.save()
                return payment
            for record in (payment, attempt):
                transition(record, Status.VERIFYING)
                record.save()
            attempt.verification_attempts += 1
            attempt.last_verified_at = timezone.now()
            attempt.save()
            try:
                # Use frozen local amount/authority, never the client's or a mutable order price.
                result = self.gateway.verify_payment(
                    amount=payment.amount,
                    currency=payment.currency,
                    authority=attempt.gateway_authority,
                )
            except (GatewayRejected, GatewayUncertain) as error:
                # Negative verify codes are not mapped to irreversible failure without authoritative
                # per-code evidence. Preserve their safe numeric code for reconciliation.
                for record in (payment, attempt):
                    transition(record, Status.UNKNOWN)
                    record.failure_code = error.code
                    record.failure_message = "Verification unconfirmed"
                    record.save()
                logger.warning("payment_verify_unconfirmed", extra={"payment_id": str(payment.pk)})
                return payment
            payment.reference_id = result.reference_id
            payment.verified_at = timezone.now()
            attempt.gateway_reference_id = result.reference_id
            for record in (payment, attempt):
                transition(record, Status.SUCCEEDED)
                record.failure_code = None
                record.failure_message = ""
                record.save()
            FulfillmentEvent.objects.create(payment=payment)
            if self.fulfill is not None:
                self.fulfill(payment)
            return payment

    @staticmethod
    def get_payment_status(*, user, payment_id) -> Payment:
        if not user.is_authenticated:
            raise AccessDenied("Authentication required.")
        try:
            return Payment.objects.get(pk=payment_id, owner=user)
        except Payment.DoesNotExist:
            raise UnknownPayment("Payment not found.") from None
