import json
from contextlib import contextmanager

import pytest
from django.test import Client
from payments.models import Status
from payments.views import configured_service

AUTHORITY = "A" + "0" * 35
pytestmark = pytest.mark.django_db


@pytest.fixture
def configured(monkeypatch, service):
    @contextmanager
    def context():
        yield service

    monkeypatch.setattr("payments.views.configured_service", context)
    return service


def test_initiation_requires_authentication(client, configured):
    assert client.post("/payments/initiate/", data={}).status_code == 401


@pytest.mark.parametrize(
    "extra", [{"amount": 1}, {"currency": "IRT"}, {"redirect_url": "https://evil.example"}]
)
def test_client_cannot_supply_price_or_return_url(client, owner, configured, gateway, extra):
    client.force_login(owner)
    response = client.post(
        "/payments/initiate/",
        {"order_reference": "order-1", **extra},
        content_type="application/json",
    )
    assert response.status_code == 400
    gateway.create_payment.assert_not_called()


def test_frontend_initiation_and_authenticated_status(client, owner, configured):
    client.force_login(owner)
    result = client.post(
        "/payments/initiate/", {"order_reference": "order-1"}, content_type="application/json"
    )
    assert result.status_code == 200
    data = result.json()
    assert data["redirect_url"].startswith("https://sandbox.zarinpal.com/pg/StartPay/")
    assert client.get(f"/payments/{data['payment_id']}/").json()["status"] == Status.PENDING


def test_csrf_retained_on_initiation_and_not_required_on_callback(owner, configured, gateway):
    client = Client(enforce_csrf_checks=True)
    client.force_login(owner)
    assert (
        client.post(
            "/payments/initiate/", {"order_reference": "order-1"}, content_type="application/json"
        ).status_code
        == 403
    )
    configured.initiate(user=owner, order_reference="order-1")
    client.logout()
    result = client.get("/payments/callback/", {"Authority": AUTHORITY, "Status": "OK"})
    assert result.status_code == 200
    assert result.json() == {"received": True}
    gateway.verify_payment.assert_called_once()


@pytest.mark.parametrize(
    "query",
    [
        "",
        "Authority=garbage&Status=OK",
        f"Authority={AUTHORITY}&Status=YES",
        f"Authority={AUTHORITY}&Status=OK&Status=NOK",
        f"Authority={AUTHORITY}&Authority={AUTHORITY}&Status=OK",
    ],
)
def test_malformed_callback(client, configured, gateway, query):
    assert client.get(f"/payments/callback/?{query}").status_code == 400
    gateway.verify_payment.assert_not_called()


def test_unknown_authority(client, configured):
    assert (
        client.get("/payments/callback/", {"Authority": AUTHORITY, "Status": "OK"}).status_code
        == 404
    )


def test_status_is_private(client, configured, owner, django_user_model):
    payment = configured.initiate(user=owner, order_reference="order-1")
    url = f"/payments/{payment.pk}/"
    assert client.get(url).status_code == 401
    other = django_user_model.objects.create_user(username="other")
    client.force_login(other)
    assert client.get(url).status_code == 404


def test_view_uses_repository_order_authorization(client, owner, gateway, monkeypatch):
    from payments.exceptions import AccessDenied
    from payments.payment_service import PaymentService

    def load_order(user, reference):
        raise AccessDenied("Unowned order")

    @contextmanager
    def context():
        yield PaymentService(gateway, load_order)

    monkeypatch.setattr("payments.views.configured_service", context)
    client.force_login(owner)
    assert (
        client.post(
            "/payments/initiate/",
            json.dumps({"order_reference": "somebody-elses-order"}),
            content_type="application/json",
        ).status_code
        == 403
    )


def test_missing_configuration_fails_closed(settings, client, owner):
    settings.ZARINPAL_MERCHANT_ID = ""
    client.force_login(owner)
    response = client.post(
        "/payments/initiate/", {"order_reference": "order-1"}, content_type="application/json"
    )
    assert response.status_code == 503
    assert "MERCHANT" not in response.content.decode()


def test_order_hook_required(settings):
    from payments.exceptions import ConfigurationError

    settings.PAYMENTS_ORDER_LOADER = ""
    with pytest.raises(ConfigurationError), configured_service():
        pass


def test_method_restrictions(client, configured):
    assert client.get("/payments/initiate/").status_code == 405
    assert client.post("/payments/callback/").status_code == 405
