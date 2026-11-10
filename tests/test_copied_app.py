"""Smoke-test the documented asset copy, not just the in-repository import harness."""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_copied_payments_app_migrates_and_runs_mocked_browser_flow(tmp_path):
    source = ROOT / ".agents/skills/iranian-payment-gateways/assets/templates/django"
    shutil.copytree(source, tmp_path / "payments", ignore=shutil.ignore_patterns("__pycache__"))
    script = r"""
import json
import sys
import types
from pathlib import Path

import django
import httpx
from django.conf import settings

settings.configure(
    SECRET_KEY="isolated-smoke-test-only",
    INSTALLED_APPS=["django.contrib.auth", "django.contrib.contenttypes",
                    "django.contrib.sessions", "payments.apps.PaymentsConfig"],
    DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
    ROOT_URLCONF="smoke_urls",
    MIDDLEWARE=["django.contrib.sessions.middleware.SessionMiddleware",
                "django.middleware.csrf.CsrfViewMiddleware",
                "django.contrib.auth.middleware.AuthenticationMiddleware"],
    ALLOWED_HOSTS=["testserver"],
    ZARINPAL_MERCHANT_ID="00000000-0000-0000-0000-000000000000",
    ZARINPAL_SANDBOX=True,
    PAYMENT_CALLBACK_URL="https://example.com/payments/callback/",
    PAYMENTS_ORDER_LOADER="smoke_hooks.load_order",
    PAYMENT_CURRENCY="IRR",
    USE_TZ=True,
)
django.setup()
import payments
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client
from django.urls import include, path
from payments.models import FulfillmentEvent, Payment
from payments.payment_service import OrderSnapshot

assert Path(payments.__file__).resolve().parent == Path.cwd() / "payments"
urls = types.ModuleType("smoke_urls")
urls.urlpatterns = [path("payments/", include("payments.urls"))]
sys.modules["smoke_urls"] = urls
hooks = types.ModuleType("smoke_hooks")
hooks.load_order = lambda user, reference: OrderSnapshot(reference, 50000)
sys.modules["smoke_hooks"] = hooks
call_command("check", verbosity=0)
call_command("migrate", verbosity=0, interactive=False)
user = get_user_model().objects.create_user(username="buyer")
authority = "A" + "0" * 35
calls = []
def handler(request):
    calls.append(str(request.url))
    payload = json.loads(request.content)
    assert payload["amount"] == 50000
    if str(request.url).endswith("/request.json"):
        return httpx.Response(200, json={"data": {"code": 100, "authority": authority}})
    assert str(request.url).endswith("/verify.json")
    assert payload["authority"] == authority
    return httpx.Response(200, json={"data": {"code": 100, "ref_id": 123456}})
original_client = httpx.Client
httpx.Client = lambda: original_client(transport=httpx.MockTransport(handler))
browser = Client()
browser.force_login(user)
response = browser.post(
    "/payments/initiate/", {"order_reference": "owned-order"}, content_type="application/json"
)
assert response.status_code == 200, response.content
payment_id = response.json()["payment_id"]
assert response.json()["redirect_url"] == f"https://sandbox.zarinpal.com/pg/StartPay/{authority}"
browser.logout()
for _ in range(2):
    response = browser.get("/payments/callback/", {"Authority": authority, "Status": "OK"})
    assert response.status_code == 200 and response.json() == {"received": True}
browser.force_login(user)
assert browser.get(f"/payments/{payment_id}/").json()["status"] == "SUCCEEDED"
assert FulfillmentEvent.objects.count() == Payment.objects.count() == 1
assert len(calls) == 2  # One creation, one verification despite duplicate callback.
print("COPIED_APP_FLOW_OK")
"""
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=tmp_path, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "COPIED_APP_FLOW_OK" in result.stdout
