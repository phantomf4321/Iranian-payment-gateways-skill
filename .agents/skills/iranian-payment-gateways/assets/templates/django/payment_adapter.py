"""Zarinpal v4 transport. See references/zarinpal-api.md for evidence and limits."""

import re
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlsplit
from uuid import UUID

import httpx

from .exceptions import ConfigurationError, GatewayRejected, GatewayUncertain, InvalidPayment

AUTHORITY = re.compile(r"[AS][a-zA-Z0-9]{35}\Z")
MAX_INTEGER = 9_223_372_036_854_775_807


def validate_authority(value: str) -> str:
    if not isinstance(value, str) or not AUTHORITY.fullmatch(value):
        raise InvalidPayment("Invalid authority format.")
    return value


def to_irr(amount: int, currency: str) -> int:
    """Call once at the trusted order boundary, never on gateway responses."""
    if type(amount) is not int or amount <= 0:
        raise InvalidPayment("Amount must be a positive integer.")
    if currency not in {"IRR", "IRT"}:
        raise InvalidPayment("Only IRR and IRT source amounts are supported.")
    result = amount if currency == "IRR" else amount * 10
    if result > MAX_INTEGER:
        raise InvalidPayment("Amount exceeds integer storage.")
    return result


def parse_bool(value: object) -> bool:
    if type(value) is bool:
        return value
    if isinstance(value, str) and value.lower() in {"true", "false"}:
        return value.lower() == "true"
    raise ConfigurationError("ZARINPAL_SANDBOX must be explicitly true or false.")


@dataclass(frozen=True)
class GatewayConfig:
    merchant_id: str = field(repr=False)
    sandbox: bool
    callback_url: str
    currency: str = "IRR"
    # Conservative local policy, not a claim about terminal-specific API limits.
    min_amount: int = 10_000
    max_amount: int = 1_000_000_000_000

    def __post_init__(self):
        try:
            UUID(self.merchant_id)
        except (ValueError, AttributeError, TypeError):
            raise ConfigurationError("ZARINPAL_MERCHANT_ID must be a UUID.") from None
        if type(self.sandbox) is not bool:
            raise ConfigurationError("Sandbox selection must be boolean.")
        if self.currency != "IRR":
            raise ConfigurationError("PAYMENT_CURRENCY must be IRR; convert trusted IRT once.")
        if (
            type(self.min_amount) is not int
            or type(self.max_amount) is not int
            or not 0 < self.min_amount <= self.max_amount <= MAX_INTEGER
        ):
            raise ConfigurationError("Invalid local amount limits.")
        try:
            url = urlsplit(self.callback_url)
            _ = url.port
            allowed_http = self.sandbox and url.hostname in {"localhost", "127.0.0.1", "::1"}
            if (
                not url.hostname
                or url.username is not None
                or url.password is not None
                or url.query
                or url.fragment
                or (url.scheme != "https" and not (url.scheme == "http" and allowed_http))
            ):
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise ConfigurationError(
                "Use a fixed HTTPS callback URL without query or credentials."
            ) from None

    @classmethod
    def from_mapping(cls, values: Mapping):
        return cls(
            merchant_id=values.get("ZARINPAL_MERCHANT_ID", ""),
            sandbox=parse_bool(values.get("ZARINPAL_SANDBOX")),
            callback_url=values.get("PAYMENT_CALLBACK_URL", ""),
            currency=values.get("PAYMENT_CURRENCY", "IRR"),
            min_amount=values.get("PAYMENT_MIN_AMOUNT_IRR", 10_000),
            max_amount=values.get("PAYMENT_MAX_AMOUNT_IRR", 1_000_000_000_000),
        )

    def validate_amount(self, amount: int, currency: str) -> None:
        if currency != "IRR" or type(amount) is not int:
            raise InvalidPayment("Gateway amount must be integer IRR.")
        if not self.min_amount <= amount <= self.max_amount:
            raise InvalidPayment("Amount outside configured local limits.")


@dataclass(frozen=True)
class CreatedPayment:
    authority: str
    redirect_url: str


@dataclass(frozen=True)
class VerifiedPayment:
    reference_id: str
    already_verified: bool = False


class PaymentGateway(Protocol):
    sandbox: bool

    def validate_amount(self, amount: int, currency: str) -> None: ...

    def create_payment(self, *, amount: int, currency: str, description: str) -> CreatedPayment: ...

    def verify_payment(self, *, amount: int, currency: str, authority: str) -> VerifiedPayment: ...

    def redirect_url(self, authority: str) -> str: ...


class ZarinpalGateway:
    def __init__(self, config: GatewayConfig, client: httpx.Client):
        self.config = config
        self.client = client
        self.sandbox = config.sandbox
        self.base_url = (
            "https://sandbox.zarinpal.com" if config.sandbox else "https://payment.zarinpal.com"
        )

    def redirect_url(self, authority: str) -> str:
        return f"{self.base_url}/pg/StartPay/{validate_authority(authority)}"

    def validate_amount(self, amount: int, currency: str) -> None:
        self.config.validate_amount(amount, currency)

    def _post(self, operation: str, payload: dict, *, retries: int) -> dict:
        for attempt in range(retries + 1):
            try:
                response = self.client.post(
                    f"{self.base_url}/pg/v4/payment/{operation}.json",
                    json={**payload, "merchant_id": self.config.merchant_id},
                    headers={"Accept": "application/json"},
                    timeout=httpx.Timeout(10.0, connect=3.0, pool=3.0),
                    follow_redirects=False,
                )
            except httpx.TransportError:
                if attempt < retries:
                    time.sleep(0.1)
                    continue
                raise GatewayUncertain() from None
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < retries:
                    time.sleep(0.1)
                    continue
                raise GatewayUncertain()
            try:
                body = response.json()
            except (ValueError, UnicodeError):
                raise GatewayUncertain() from None
            if not isinstance(body, dict):
                raise GatewayUncertain()
            errors = body.get("errors")
            if isinstance(errors, dict) and type(errors.get("code")) is int and errors["code"] < 0:
                if body.get("data") not in (None, [], {}):
                    raise GatewayUncertain()
                raise GatewayRejected(code=errors["code"])
            if response.status_code != 200 or errors not in (None, [], {}):
                raise GatewayUncertain()
            data = body.get("data")
            if not isinstance(data, dict) or type(data.get("code")) is not int:
                raise GatewayUncertain()
            if data["code"] < 0:
                raise GatewayRejected(code=data["code"])
            return data
        raise AssertionError("Unreachable retry loop")

    def create_payment(self, *, amount: int, currency: str, description: str) -> CreatedPayment:
        self.config.validate_amount(amount, currency)
        if not isinstance(description, str) or not 1 <= len(description) <= 255:
            raise InvalidPayment("Provide a short non-sensitive description.")
        data = self._post(
            "request",
            {
                "amount": amount,
                "callback_url": self.config.callback_url,
                "description": description,
            },
            retries=0,  # Creation has no verified idempotency key: never retry automatically.
        )
        if data["code"] != 100:
            raise GatewayUncertain(code=data["code"])
        try:
            authority = validate_authority(data.get("authority"))
        except InvalidPayment:
            raise GatewayUncertain() from None
        return CreatedPayment(authority, self.redirect_url(authority))

    def verify_payment(self, *, amount: int, currency: str, authority: str) -> VerifiedPayment:
        self.config.validate_amount(amount, currency)
        validate_authority(authority)
        data = self._post("verify", {"amount": amount, "authority": authority}, retries=1)
        if data["code"] not in {100, 101}:
            raise GatewayUncertain(code=data["code"])
        # These echoes are not guaranteed by the SDK schema; reject inconsistencies if present.
        for key, expected in {
            "amount": amount,
            "currency": currency,
            "authority": authority,
        }.items():
            if key in data and (type(data[key]) is not type(expected) or data[key] != expected):
                raise GatewayUncertain()
        reference = data.get("ref_id")
        if type(reference) is int and reference > 0:
            reference = str(reference)
        if not isinstance(reference, str) or not re.fullmatch(r"[0-9]{1,64}", reference):
            # A 101 without a reference is an unresolved result, never invented success.
            raise GatewayUncertain()
        if int(reference) == 0:
            raise GatewayUncertain()
        return VerifiedPayment(reference, already_verified=data["code"] == 101)
