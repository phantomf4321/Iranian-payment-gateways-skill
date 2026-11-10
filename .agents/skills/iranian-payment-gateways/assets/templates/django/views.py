"""Session-auth examples. Retain CSRF on initiation; callback is a narrow GET."""

import json
from contextlib import contextmanager

import httpx

from django.conf import settings
from django.db import transaction
from django.http import JsonResponse
from django.utils.module_loading import import_string
from django.views.decorators.debug import sensitive_variables
from django.views.decorators.http import require_GET, require_POST

from .exceptions import (
    AccessDenied,
    ConfigurationError,
    InvalidPayment,
    PaymentConflict,
    UnknownPayment,
)
from .models import Status
from .payment_adapter import GatewayConfig, ZarinpalGateway
from .payment_service import PaymentService


@contextmanager
@sensitive_variables()
def configured_service():
    names = (
        "ZARINPAL_MERCHANT_ID",
        "ZARINPAL_SANDBOX",
        "PAYMENT_CALLBACK_URL",
        "PAYMENT_CURRENCY",
        "PAYMENT_MIN_AMOUNT_IRR",
        "PAYMENT_MAX_AMOUNT_IRR",
    )
    config = GatewayConfig.from_mapping(
        {name: getattr(settings, name) for name in names if hasattr(settings, name)}
    )
    loader_path = getattr(settings, "PAYMENTS_ORDER_LOADER", "")
    if not loader_path:
        raise ConfigurationError("Configure PAYMENTS_ORDER_LOADER before enabling payments.")
    loader = import_string(loader_path)
    fulfill_path = getattr(settings, "PAYMENTS_FULFILL", "")
    fulfill = import_string(fulfill_path) if fulfill_path else None
    with httpx.Client() as client:
        yield PaymentService(ZarinpalGateway(config, client), loader, fulfill)


@transaction.non_atomic_requests
@require_POST
def initiate(request):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Authentication required"}, status=401)
    try:
        if request.content_type != "application/json":
            raise InvalidPayment("Use application/json.")
        body = json.loads(request.body)
        if not isinstance(body, dict) or set(body) != {"order_reference"}:
            raise InvalidPayment("Supply only order_reference; prices are server-owned.")
        with configured_service() as service:
            payment = service.initiate(user=request.user, order_reference=body["order_reference"])
            redirect_url = None
            if payment.status == Status.PENDING:
                attempt = payment.attempts.get(status=Status.PENDING)
                redirect_url = service.gateway.redirect_url(attempt.gateway_authority)
        code = 200 if payment.status in {Status.PENDING, Status.SUCCEEDED} else 409
        return JsonResponse(
            {"payment_id": str(payment.pk), "status": payment.status, "redirect_url": redirect_url},
            status=code,
        )
    except (ValueError, UnicodeError, InvalidPayment):
        return JsonResponse({"error": "Invalid payment request"}, status=400)
    except AccessDenied:
        return JsonResponse({"error": "Order access denied"}, status=403)
    except (PaymentConflict, UnknownPayment):
        return JsonResponse(
            {"error": "Order unavailable or payment needs reconciliation"}, status=409
        )
    except ConfigurationError:
        return JsonResponse({"error": "Payment configuration unavailable"}, status=503)


@transaction.non_atomic_requests
@require_GET
def callback(request):
    try:
        if any(len(request.GET.getlist(key)) != 1 for key in ("Authority", "Status")):
            raise InvalidPayment("Missing or duplicate callback parameters.")
        with configured_service() as service:
            service.verify_callback(
                authority=request.GET["Authority"], callback_status=request.GET["Status"]
            )
        # Public callback discloses no owner, amount, reference, or authoritative status.
        # A frontend return page retrieves status through its authenticated backend session.
        return JsonResponse({"received": True})
    except InvalidPayment:
        return JsonResponse({"error": "Invalid callback"}, status=400)
    except UnknownPayment:
        return JsonResponse({"error": "Unknown payment"}, status=404)
    except (PaymentConflict, AccessDenied):
        return JsonResponse({"error": "Payment needs reconciliation"}, status=409)
    except ConfigurationError:
        return JsonResponse({"error": "Payment configuration unavailable"}, status=503)


@require_GET
def payment_status(request, payment_id):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Authentication required"}, status=401)
    try:
        payment = PaymentService.get_payment_status(user=request.user, payment_id=payment_id)
        return JsonResponse(
            {"payment_id": str(payment.pk), "status": payment.status, "currency": payment.currency}
        )
    except UnknownPayment:
        return JsonResponse({"error": "Payment not found"}, status=404)
