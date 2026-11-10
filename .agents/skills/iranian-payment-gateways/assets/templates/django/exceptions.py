"""Public exception messages must never contain upstream bodies or credentials."""


class PaymentError(Exception):
    pass


class ConfigurationError(PaymentError):
    pass


class InvalidPayment(PaymentError):
    pass


class AccessDenied(PaymentError):
    pass


class UnknownPayment(PaymentError):
    pass


class PaymentConflict(PaymentError):
    pass


class InvalidTransition(PaymentError):
    pass


class GatewayError(PaymentError):
    def __init__(self, *, code: int | None = None):
        self.code = code
        super().__init__("Gateway operation could not be confirmed.")


class GatewayRejected(GatewayError):
    """The provider explicitly rejected this request; not a timeout."""


class GatewayUncertain(GatewayError):
    """The request may have reached the provider. Do not retry creation."""
