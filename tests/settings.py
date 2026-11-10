"""Load the template under its destination app name without duplicating its source."""

import importlib.util
import os
import sys
from pathlib import Path

TEMPLATE = (
    Path(__file__).resolve().parents[1]
    / ".agents/skills/iranian-payment-gateways/assets/templates/django"
)
spec = importlib.util.spec_from_file_location(
    "payments", TEMPLATE / "__init__.py", submodule_search_locations=[str(TEMPLATE)]
)
module = importlib.util.module_from_spec(spec)
sys.modules["payments"] = module
spec.loader.exec_module(module)

SECRET_KEY = "test-only-not-a-deployment-secret"
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "payments.apps.PaymentsConfig",
]
MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
]
ROOT_URLCONF = "tests.urls"
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
if os.environ.get("PAYMENTS_TEST_POSTGRES") == "1":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("PGDATABASE", "payments"),
            "USER": os.environ.get("PGUSER", "payments"),
            "PASSWORD": os.environ.get("PGPASSWORD", ""),
            "HOST": os.environ.get("PGHOST", "127.0.0.1"),
            "PORT": os.environ.get("PGPORT", "55432"),
        }
    }
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
ALLOWED_HOSTS = ["testserver", "localhost"]
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
ZARINPAL_MERCHANT_ID = "00000000-0000-0000-0000-000000000000"
ZARINPAL_SANDBOX = True
PAYMENT_CALLBACK_URL = "https://example.com/payments/callback/"
PAYMENT_CURRENCY = "IRR"
PAYMENTS_ORDER_LOADER = "tests.hooks.load_order"
