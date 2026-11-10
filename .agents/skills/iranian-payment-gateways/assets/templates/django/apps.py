from django.apps import AppConfig


class PaymentsConfig(AppConfig):
    name = "payments"  # Copy this template directory to an application named payments.
    label = "gateway_payments"
    verbose_name = "Zarinpal payments"
    default_auto_field = "django.db.models.BigAutoField"
