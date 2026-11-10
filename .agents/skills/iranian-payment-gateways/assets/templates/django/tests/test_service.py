from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock
from time import sleep

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.db.models import F, Value
from django.db.models.functions import Concat
from payments.exceptions import (
    AccessDenied,
    GatewayRejected,
    GatewayUncertain,
    InvalidPayment,
    InvalidTransition,
    PaymentConflict,
    UnknownPayment,
)
from payments.models import FulfillmentEvent, Payment, PaymentAttempt, Status, transition
from payments.payment_adapter import VerifiedPayment
from payments.payment_service import OrderSnapshot

AUTHORITY = "A" + "0" * 35
pytestmark = pytest.mark.django_db


def create(service, owner):
    return service.initiate(user=owner, order_reference="order-1")


def verify(service, status="OK"):
    return service.verify_callback(authority=AUTHORITY, callback_status=status)


def test_initiation_stores_frozen_price_and_authority(service, owner, gateway):
    payment = create(service, owner)
    assert (payment.amount, payment.currency, payment.status) == (50_000, "IRR", Status.PENDING)
    attempt = payment.attempts.get()
    assert attempt.gateway_authority == AUTHORITY
    gateway.create_payment.assert_called_once_with(
        amount=50_000, currency="IRR", description=f"Payment {payment.pk}"
    )


def test_repeated_initiation_reuses_attempt(service, owner, gateway):
    first, second = create(service, owner), create(service, owner)
    assert first.pk == second.pk
    assert Payment.objects.count() == PaymentAttempt.objects.count() == 1
    gateway.create_payment.assert_called_once()


@pytest.mark.parametrize(
    "amount,currency",
    [(0, "IRR"), (-1, "IRR"), (5.0, "IRR"), (True, "IRR"), (5000, "IRT"), (5000, "USD")],
)
def test_invalid_trusted_order_snapshot(service, owner, gateway, amount, currency):
    service.order_loader = lambda u, r: OrderSnapshot(r, amount, currency)
    with pytest.raises(InvalidPayment):
        create(service, owner)
    gateway.create_payment.assert_not_called()


def test_different_price_cannot_reinitiate(service, owner, gateway):
    create(service, owner)
    service.order_loader = lambda u, r: OrderSnapshot(r, 500_000)
    with pytest.raises(PaymentConflict):
        create(service, owner)
    gateway.create_payment.assert_called_once()


def test_creation_rejection_can_be_retried(service, owner, gateway):
    gateway.create_payment.side_effect = GatewayRejected(code=-9)
    payment = create(service, owner)
    assert payment.status == Status.FAILED
    gateway.create_payment.side_effect = None
    assert create(service, owner).status == Status.PENDING
    assert payment.attempts.count() == 2


def test_creation_timeout_blocks_recreation(service, owner, gateway, caplog):
    gateway.create_payment.side_effect = GatewayUncertain()
    assert create(service, owner).status == Status.UNKNOWN
    with pytest.raises(PaymentConflict):
        create(service, owner)
    gateway.create_payment.assert_called_once()
    assert "payment_create_unconfirmed" in caplog.text


def test_amount_limits_checked_before_durable_creation(service, owner, gateway):
    gateway.validate_amount.side_effect = InvalidPayment("Below configured limit")
    with pytest.raises(InvalidPayment):
        create(service, owner)
    assert not Payment.objects.exists()
    gateway.create_payment.assert_not_called()


def test_nonpayable_order_is_not_initiated(service, owner, gateway):
    service.order_loader = lambda u, r: OrderSnapshot(r, 50_000, payable=False)
    with pytest.raises(PaymentConflict):
        create(service, owner)
    assert not Payment.objects.exists()
    gateway.create_payment.assert_not_called()


def test_paid_order_can_process_duplicate_callback(service, owner, gateway):
    create(service, owner)
    verify(service)
    service.order_loader = lambda u, r: OrderSnapshot(r, 50_000, payable=False)
    assert verify(service).status == Status.SUCCEEDED
    assert create(service, owner).status == Status.SUCCEEDED
    assert gateway.verify_payment.call_count == 1


@pytest.mark.django_db(transaction=True)
def test_outer_transaction_refused_before_gateway_request(service, owner, gateway):
    with pytest.raises(RuntimeError, match="durable"), transaction.atomic():
        create(service, owner)
    gateway.create_payment.assert_not_called()
    assert not Payment.objects.exists()


def test_crash_after_creation_claim_does_not_repeat_request(service, owner, gateway):
    gateway.create_payment.side_effect = RuntimeError("simulated process crash")
    with pytest.raises(RuntimeError):
        create(service, owner)
    assert Payment.objects.get().status == Status.CREATED
    with pytest.raises(PaymentConflict):
        create(service, owner)
    assert PaymentAttempt.objects.count() == 1
    assert gateway.create_payment.call_count == 1


def test_success_fulfills_once_and_enqueues_durable_event(service, owner, gateway):
    create(service, owner)
    calls = []
    service.fulfill = lambda p: calls.append(p.pk)
    payment = verify(service)
    assert payment.status == Status.SUCCEEDED
    assert payment.reference_id == "123456" and payment.verified_at is not None
    assert verify(service).status == Status.SUCCEEDED
    assert verify(service, "NOK").status == Status.SUCCEEDED
    assert calls == [payment.pk]
    assert FulfillmentEvent.objects.filter(payment=payment).count() == 1
    assert payment.attempts.get().verification_attempts == 1
    gateway.verify_payment.assert_called_once_with(
        amount=50_000, currency="IRR", authority=AUTHORITY
    )


def test_already_verified_fulfills_local_record_once(service, owner, gateway):
    create(service, owner)
    gateway.verify_payment.return_value = VerifiedPayment("123456", already_verified=True)
    verify(service)
    verify(service)
    assert FulfillmentEvent.objects.count() == 1
    assert Payment.objects.get().status == Status.SUCCEEDED


@pytest.mark.parametrize("error", [GatewayUncertain(), GatewayRejected(code=-51)])
def test_unconfirmed_verification_never_fulfills(service, owner, gateway, error):
    create(service, owner)
    gateway.verify_payment.side_effect = error
    result = verify(service)
    assert result.status == Status.UNKNOWN
    assert result.failure_code == error.code
    assert not FulfillmentEvent.objects.exists()
    gateway.verify_payment.side_effect = None
    gateway.verify_payment.return_value = VerifiedPayment("123456", True)
    assert verify(service).status == Status.SUCCEEDED


def test_cancel_is_advisory_and_recoverable(service, owner, gateway):
    create(service, owner)
    assert verify(service, "NOK").status == Status.CANCELED
    gateway.verify_payment.assert_not_called()
    with pytest.raises(PaymentConflict):
        create(service, owner)
    assert verify(service).status == Status.SUCCEEDED


def test_unknown_authority(service, gateway):
    with pytest.raises(UnknownPayment):
        verify(service)
    gateway.verify_payment.assert_not_called()


@pytest.mark.parametrize(
    "authority,status",
    [("garbage", "OK"), (AUTHORITY, "YES"), (None, "OK"), (AUTHORITY + "\n", "OK")],
)
def test_malformed_callback_rejected_before_network(service, gateway, authority, status):
    with pytest.raises(InvalidPayment):
        service.verify_callback(authority=authority, callback_status=status)
    gateway.verify_payment.assert_not_called()


def test_fulfillment_failure_rolls_back_then_101_recovers(service, owner, gateway):
    create(service, owner)

    def broken(payment):
        get_user_model().objects.filter(pk=owner.pk).update(last_name="should roll back")
        raise RuntimeError("business update failed")

    service.fulfill = broken
    with pytest.raises(RuntimeError):
        verify(service)
    owner.refresh_from_db()
    assert owner.last_name == ""
    assert Payment.objects.get().status == Status.PENDING
    assert not FulfillmentEvent.objects.exists()
    service.fulfill = None
    gateway.verify_payment.return_value = VerifiedPayment("123456", True)
    assert verify(service).status == Status.SUCCEEDED
    assert FulfillmentEvent.objects.count() == 1


def test_frozen_amount_used_even_if_order_changes(service, owner, gateway):
    create(service, owner)
    service.order_loader = lambda u, r: OrderSnapshot(r, 500_000)
    verify(service)
    gateway.verify_payment.assert_called_once_with(
        amount=50_000, currency="IRR", authority=AUTHORITY
    )


def test_environment_cannot_change_between_creation_and_verification(service, owner, gateway):
    create(service, owner)
    gateway.sandbox = False
    with pytest.raises(PaymentConflict):
        verify(service)
    gateway.verify_payment.assert_not_called()


def test_other_user_cannot_reuse_or_read_payment(service, owner, django_user_model):
    payment = create(service, owner)
    other = django_user_model.objects.create_user(username="other")
    with pytest.raises(AccessDenied):
        create(service, other)
    with pytest.raises(UnknownPayment):
        service.get_payment_status(user=other, payment_id=payment.pk)


@pytest.mark.parametrize("target", [Status.PENDING, Status.FAILED, Status.CANCELED, Status.UNKNOWN])
def test_succeeded_never_regresses(service, owner, target):
    create(service, owner)
    payment = verify(service)
    with pytest.raises(InvalidTransition):
        transition(payment, target)


def test_db_enforces_amount_and_success_evidence(owner):
    for values in [
        {"amount": -1},
        {"amount": 1, "currency": "IRT"},
        {"amount": 1, "status": Status.SUCCEEDED},
    ]:
        with pytest.raises(IntegrityError), transaction.atomic():
            Payment.objects.create(order_reference="invalid", owner=owner, sandbox=True, **values)


def test_unique_fulfillment_and_reference_constraints(service, owner):
    create(service, owner)
    payment = verify(service)
    with pytest.raises(IntegrityError), transaction.atomic():
        FulfillmentEvent.objects.create(payment=payment)
    with pytest.raises(IntegrityError), transaction.atomic():
        Payment.objects.create(
            order_reference="other",
            owner=owner,
            amount=50_000,
            sandbox=True,
            reference_id=payment.reference_id,
        )


@pytest.mark.postgres
@pytest.mark.django_db(transaction=True)
def test_concurrent_callbacks_lock_payment_and_fulfill_once(service, owner, gateway):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL is required to validate select_for_update")

    def locked_order(user, reference):
        get_user_model().objects.select_for_update().get(pk=user.pk)
        return OrderSnapshot(reference, 50_000)

    service.order_loader = locked_order
    create(service, owner)
    barrier = Barrier(2)
    count_lock = Lock()
    calls = []

    def remote_verify(**kwargs):
        with count_lock:
            calls.append(kwargs)
        sleep(0.2)  # Keep the real row lock while the competing transaction arrives.
        return VerifiedPayment("123456")

    def fulfill(payment):
        get_user_model().objects.filter(pk=payment.owner_id).update(
            last_name=Concat(F("last_name"), Value("x"))
        )

    gateway.verify_payment.side_effect = remote_verify
    service.fulfill = fulfill

    def worker(_):
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            return verify(service).status
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(worker, range(2)))
    owner.refresh_from_db()
    assert statuses == [Status.SUCCEEDED, Status.SUCCEEDED]
    assert len(calls) == 1 and owner.last_name == "x"
    assert FulfillmentEvent.objects.count() == 1
    assert PaymentAttempt.objects.get().verification_attempts == 1


@pytest.mark.postgres
@pytest.mark.django_db(transaction=True)
def test_concurrent_initiation_creates_only_one_remote_request(service, owner, gateway):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL is required to validate creation serialization")

    def locked_order(user, reference):
        get_user_model().objects.select_for_update().get(pk=user.pk)
        return OrderSnapshot(reference, 50_000)

    service.order_loader = locked_order
    barrier = Barrier(2)
    original = gateway.create_payment.return_value

    def remote_create(**kwargs):
        sleep(0.2)
        return original

    gateway.create_payment.side_effect = remote_create

    def worker(_):
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            try:
                return create(service, owner).status
            except PaymentConflict:
                return "IN_PROGRESS"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(worker, range(2)))
    assert Status.PENDING in statuses
    assert gateway.create_payment.call_count == 1
    assert Payment.objects.count() == PaymentAttempt.objects.count() == 1
