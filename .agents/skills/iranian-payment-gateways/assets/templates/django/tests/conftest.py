from unittest.mock import Mock

import pytest
from payments.payment_adapter import CreatedPayment, VerifiedPayment
from payments.payment_service import OrderSnapshot, PaymentService

AUTHORITY = "A" + "0" * 35


@pytest.fixture
def owner(django_user_model):
    return django_user_model.objects.create_user(username="owner")


@pytest.fixture
def gateway():
    result = Mock()
    result.sandbox = True
    result.create_payment.return_value = CreatedPayment(
        AUTHORITY, f"https://sandbox.zarinpal.com/pg/StartPay/{AUTHORITY}"
    )
    result.verify_payment.return_value = VerifiedPayment("123456")
    result.redirect_url.return_value = f"https://sandbox.zarinpal.com/pg/StartPay/{AUTHORITY}"
    return result


@pytest.fixture
def service(gateway):
    return PaymentService(gateway, lambda user, reference: OrderSnapshot(reference, 50_000))
