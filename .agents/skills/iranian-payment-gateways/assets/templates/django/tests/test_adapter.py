import json
from dataclasses import replace

import httpx
import pytest
from payments.exceptions import (
    ConfigurationError,
    GatewayRejected,
    GatewayUncertain,
    InvalidPayment,
)
from payments.payment_adapter import GatewayConfig, ZarinpalGateway, parse_bool, to_irr

AUTHORITY = "A" + "0" * 35
MERCHANT = "00000000-0000-0000-0000-000000000000"


@pytest.fixture
def config():
    return GatewayConfig(MERCHANT, True, "https://example.com/payments/callback/")


def adapter(config, handler):
    return ZarinpalGateway(config, httpx.Client(transport=httpx.MockTransport(handler)))


def test_create_payload_and_redirect(config):
    def handler(request):
        assert str(request.url) == "https://sandbox.zarinpal.com/pg/v4/payment/request.json"
        assert json.loads(request.content) == {
            "merchant_id": MERCHANT,
            "amount": 50_000,
            "description": "Order",
            "callback_url": config.callback_url,
        }
        assert request.extensions["timeout"] == {
            "connect": 3.0,
            "read": 10.0,
            "write": 10.0,
            "pool": 3.0,
        }
        return httpx.Response(
            200, json={"data": {"code": 100, "authority": AUTHORITY}, "errors": []}
        )

    result = adapter(config, handler).create_payment(
        amount=50_000, currency="IRR", description="Order"
    )
    assert result.authority == AUTHORITY
    assert result.redirect_url == f"https://sandbox.zarinpal.com/pg/StartPay/{AUTHORITY}"


@pytest.mark.parametrize("amount", [0, -1, 9999, 1.5, True, "50000", 1_000_000_000_001])
def test_invalid_amount(config, amount):
    with pytest.raises(InvalidPayment):
        config.validate_amount(amount, "IRR")


@pytest.mark.parametrize("currency", ["IRT", "USD", "irr"])
def test_gateway_rejects_noncanonical_currency(config, currency):
    with pytest.raises(InvalidPayment):
        config.validate_amount(50_000, currency)


@pytest.mark.parametrize(
    "body",
    [
        [],
        {},
        {"data": []},
        {"data": {"code": "100"}},
        {"data": {"code": True}},
        {"data": {"code": 100, "authority": "https://evil.example"}},
        {"data": {"code": 101, "authority": AUTHORITY}},
    ],
)
def test_malformed_create_response(config, body):
    gateway = adapter(config, lambda r: httpx.Response(200, json=body))
    with pytest.raises(GatewayUncertain):
        gateway.create_payment(amount=50_000, currency="IRR", description="Order")


def test_invalid_json(config):
    gateway = adapter(config, lambda r: httpx.Response(200, content=b"not JSON"))
    with pytest.raises(GatewayUncertain):
        gateway.create_payment(amount=50_000, currency="IRR", description="Order")


def test_contradictory_rejection_and_success_is_not_retryable_creation(config):
    gateway = adapter(
        config,
        lambda r: httpx.Response(
            200, json={"data": {"code": 100, "authority": AUTHORITY}, "errors": {"code": -9}}
        ),
    )
    with pytest.raises(GatewayUncertain):
        gateway.create_payment(amount=50_000, currency="IRR", description="Order")


def test_creation_timeout_is_not_retried(config):
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("sensitive upstream content")

    with pytest.raises(GatewayUncertain) as error:
        adapter(config, handler).create_payment(amount=50_000, currency="IRR", description="Order")
    assert len(calls) == 1
    assert "sensitive" not in str(error.value)
    assert error.value.__cause__ is None


@pytest.mark.parametrize("http_status", [302, 401, 404, 429, 500])
def test_http_status_never_proves_success(config, http_status):
    gateway = adapter(
        config,
        lambda r: httpx.Response(http_status, json={"data": {"code": 100, "authority": AUTHORITY}}),
    )
    with pytest.raises(GatewayUncertain):
        gateway.create_payment(amount=50_000, currency="IRR", description="Order")


def test_gateway_rejection_redacts_body(config):
    gateway = adapter(
        config,
        lambda r: httpx.Response(
            422,
            json={"errors": {"code": -9, "message": f"merchant={MERCHANT} card=1234567890123456"}},
        ),
    )
    with pytest.raises(GatewayRejected) as error:
        gateway.create_payment(amount=50_000, currency="IRR", description="Order")
    assert error.value.code == -9
    assert MERCHANT not in str(error.value)
    assert "1234567890123456" not in str(error.value)
    assert MERCHANT not in repr(config)


@pytest.mark.parametrize("code", [100, 101])
def test_verify_success_and_already_verified(config, code):
    def handler(request):
        assert str(request.url).endswith("/pg/v4/payment/verify.json")
        assert json.loads(request.content) == {
            "amount": 50_000,
            "authority": AUTHORITY,
            "merchant_id": MERCHANT,
        }
        return httpx.Response(200, json={"data": {"code": code, "ref_id": 123456}})

    result = adapter(config, handler).verify_payment(
        amount=50_000, currency="IRR", authority=AUTHORITY
    )
    assert result.reference_id == "123456"
    assert result.already_verified == (code == 101)


@pytest.mark.parametrize(
    "extra",
    [
        {"amount": 5000},
        {"amount": 50_000.0},
        {"currency": "IRT"},
        {"authority": "S" + "0" * 35},
        {"ref_id": None},
        {"ref_id": True},
        {"ref_id": 0},
        {"ref_id": ""},
        {"code": 102},
    ],
)
def test_inconsistent_verification_is_unknown(config, extra):
    gateway = adapter(
        config,
        lambda r: httpx.Response(200, json={"data": {"code": 100, "ref_id": 123456, **extra}}),
    )
    with pytest.raises(GatewayUncertain):
        gateway.verify_payment(amount=50_000, currency="IRR", authority=AUTHORITY)


def test_101_without_reference_is_unknown(config):
    gateway = adapter(config, lambda r: httpx.Response(200, json={"data": {"code": 101}}))
    with pytest.raises(GatewayUncertain):
        gateway.verify_payment(amount=50_000, currency="IRR", authority=AUTHORITY)


def test_verification_bounded_retry(config):
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ConnectError("private network details")

    with pytest.raises(GatewayUncertain):
        adapter(config, handler).verify_payment(amount=50_000, currency="IRR", authority=AUTHORITY)
    assert len(calls) == 2


def test_verification_retry_recovers(config):
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"data": {"code": 101, "ref_id": "123456"}})

    assert (
        adapter(config, handler)
        .verify_payment(amount=50_000, currency="IRR", authority=AUTHORITY)
        .already_verified
    )
    assert len(calls) == 2


def test_production_host(config):
    gateway = adapter(replace(config, sandbox=False), lambda r: httpx.Response(200))
    assert (
        gateway.redirect_url(AUTHORITY) == f"https://payment.zarinpal.com/pg/StartPay/{AUTHORITY}"
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/callback/",
        "https://example.com/callback/?next=https://evil.example",
        "https://user:password@example.com/callback/",
        "javascript:alert(1)",
        "https://example.com/#callback",
        "https://example.com:bad/",
    ],
)
def test_bad_callback_url(config, url):
    with pytest.raises(ConfigurationError):
        replace(config, callback_url=url)


def test_local_http_is_sandbox_only(config):
    replace(config, callback_url="http://localhost:8000/payments/callback/")
    with pytest.raises(ConfigurationError):
        replace(config, sandbox=False, callback_url="http://localhost:8000/payments/callback/")


@pytest.mark.parametrize("merchant", ["", None, "not-a-uuid"])
def test_missing_merchant(config, merchant):
    with pytest.raises(ConfigurationError):
        replace(config, merchant_id=merchant)


@pytest.mark.parametrize("value", [None, "yes", "1", 0, ""])
def test_ambiguous_environment_selection(value):
    with pytest.raises(ConfigurationError):
        parse_bool(value)


def test_explicit_environment_selection():
    assert parse_bool("false") is False
    assert parse_bool("TRUE") is True


def test_irr_and_toman_boundary():
    assert to_irr(50_000, "IRR") == 50_000
    assert to_irr(5000, "IRT") == 50_000
    assert to_irr(to_irr(5000, "IRT"), "IRR") == 50_000


@pytest.mark.parametrize(
    "amount,currency",
    [
        (1.5, "IRT"),
        (True, "IRR"),
        (0, "IRR"),
        (100, "USD"),
        (2**63, "IRR"),
        (2**63 // 10 + 1, "IRT"),
    ],
)
def test_currency_rejects_fractional_unknown_or_overflow(amount, currency):
    with pytest.raises(InvalidPayment):
        to_irr(amount, currency)
