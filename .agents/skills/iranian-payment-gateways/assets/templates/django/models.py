"""Keep these tables in the same database as order fulfillment writes."""

import uuid

from django.conf import settings
from django.db import models

from .exceptions import InvalidTransition


class Status(models.TextChoices):
    CREATED = "CREATED"
    PENDING = "PENDING"
    VERIFYING = "VERIFYING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"
    UNKNOWN = "UNKNOWN"


TRANSITIONS = {
    Status.CREATED: {Status.PENDING, Status.FAILED, Status.UNKNOWN},
    Status.PENDING: {Status.VERIFYING, Status.CANCELED},
    Status.VERIFYING: {Status.SUCCEEDED, Status.UNKNOWN},
    Status.UNKNOWN: {Status.VERIFYING},
    Status.CANCELED: {Status.VERIFYING},
    Status.FAILED: {Status.CREATED},  # Only explicit creation rejections may be retried.
    Status.SUCCEEDED: set(),
}


def transition(record, target: Status) -> None:
    if record.status != target and target not in TRANSITIONS[record.status]:
        raise InvalidTransition("Illegal payment state transition.")
    record.status = target


class Payment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Adapt this association to your existing order model; keep its uniqueness scope explicit.
    order_reference = models.CharField(max_length=128, unique=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    provider = models.CharField(max_length=16, default="zarinpal", editable=False)
    sandbox = models.BooleanField()
    amount = models.BigIntegerField()
    currency = models.CharField(max_length=3, default="IRR")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.CREATED)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    reference_id = models.CharField(max_length=64, null=True, blank=True, unique=True)
    failure_code = models.IntegerField(null=True, blank=True)
    failure_message = models.CharField(max_length=100, blank=True)

    class Meta:
        indexes = [models.Index(fields=["status", "updated_at"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0), name="payment_positive_amount"
            ),
            models.CheckConstraint(condition=models.Q(currency="IRR"), name="payment_irr_only"),
            models.CheckConstraint(
                condition=models.Q(provider="zarinpal"), name="payment_provider"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=Status.values), name="payment_status"
            ),
            models.CheckConstraint(
                condition=~models.Q(status=Status.SUCCEEDED)
                | (models.Q(verified_at__isnull=False) & models.Q(reference_id__isnull=False)),
                name="payment_success_evidence",
            ),
        ]


class PaymentAttempt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="attempts")
    gateway_authority = models.CharField(max_length=36, unique=True, null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.CREATED)
    initiated_at = models.DateTimeField(auto_now_add=True)
    callback_received_at = models.DateTimeField(null=True, blank=True)
    verification_attempts = models.PositiveIntegerField(default=0)
    last_verified_at = models.DateTimeField(null=True, blank=True)
    gateway_reference_id = models.CharField(max_length=64, null=True, blank=True, unique=True)
    failure_code = models.IntegerField(null=True, blank=True)
    failure_message = models.CharField(max_length=100, blank=True)

    class Meta:
        indexes = [models.Index(fields=["status", "initiated_at"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=Status.values), name="attempt_status"
            ),
            models.UniqueConstraint(
                fields=["payment"],
                condition=~models.Q(status=Status.FAILED),
                name="one_unresolved_attempt",
            ),
        ]


class FulfillmentEvent(models.Model):
    """Durable handoff for external effects. Consumer must deduplicate by this ID."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payment = models.OneToOneField(Payment, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["delivered_at", "created_at"])]
