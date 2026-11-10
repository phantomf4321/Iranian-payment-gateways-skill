# Django and Next.js integration

Contents: [adapting](#adapting-the-assets), [configuration](#configuration),
[hooks](#order-and-fulfillment-hooks), [frontend](#nextjs-boundary),
[checks](#tests-and-deployment-checks).

## Adapting the assets

Read the existing project first. If it already has payment/order tables, adapt
the service/adapter to them instead of installing a second payment subsystem.
For a new app, copy `assets/templates/django` to a destination directory named
`payments`. Its `PaymentsConfig.name` is `payments`, label `gateway_payments`.
If renaming either, adjust imports, tests, migration references and index names.
The template is tested with Django 5.2 and Python 3.12; its dependencies are
Django and httpx. PyYAML is needed for skill validation, not by the payment app.

Add `payments.apps.PaymentsConfig` to `INSTALLED_APPS`, retain Django auth/session/
CSRF middleware, and include `payments.urls` under `/payments/`. Inspect the
included initial migration; when integrating existing tables, generate appropriate
migrations instead of blindly applying it. Keep payment and business tables in
the same database. Use PostgreSQL for the demonstrated locking semantics.

## Configuration

The template does not load `.env` automatically. Use the host project's settings
loader. Map these variables to Django settings; parse booleans explicitly:

```python
import os
from payments.payment_adapter import parse_bool

ZARINPAL_MERCHANT_ID = os.environ["ZARINPAL_MERCHANT_ID"]
ZARINPAL_SANDBOX = parse_bool(os.environ["ZARINPAL_SANDBOX"])
PAYMENT_CALLBACK_URL = os.environ["PAYMENT_CALLBACK_URL"]
PAYMENT_CURRENCY = "IRR"
PAYMENT_MIN_AMOUNT_IRR = int(os.environ.get("PAYMENT_MIN_AMOUNT_IRR", "10000"))
PAYMENT_MAX_AMOUNT_IRR = int(os.environ.get("PAYMENT_MAX_AMOUNT_IRR", "1000000000000"))
PAYMENTS_ORDER_LOADER = "shop.payment_hooks.load_order"
PAYMENTS_FULFILL = "shop.payment_hooks.fulfill"  # Optional same-DB hook.
```

Never use `bool(os.environ["ZARINPAL_SANDBOX"])`: the string `false` is truthy.
The `.env.example` UUID is inert and only suitable for local format checks and
mock tests. Set real merchant configuration securely on the backend. Confirm
terminal limits and current callback conventions before production use. Callback
must exactly match the deployed public route, including trailing slash; it is
fixed server configuration, never built from untrusted request Host/next values.

## Order and fulfillment hooks

These are contracts to implement against the **existing application's schema**:

```python
def load_order(user, reference) -> OrderSnapshot:
    # Query your existing order by owner and reference using select_for_update.
    # Raise AccessDenied/UnknownPayment for unauthorized or nonexistent orders.
    # Return canonical integer IRR, and payable=False for already-paid/closed orders.
    # Do not reject a valid owned order solely because it is already paid:
    # duplicate callbacks need to lock it and observe the existing success.
    ...


def fulfill(payment) -> None:
    # Perform same-database order/credit/entitlement writes only.
    # The associated order is already locked by load_order in this transaction.
    # Recheck business invariants and the frozen price. Raise on conflicts;
    # do not overwrite prices, silently skip an unpaid order, or make network calls.
    ...
```

The hook names above describe the required adaptation; they are not shipped as
empty runnable hooks. Import `OrderSnapshot` from `payments.payment_service` and
`to_irr` from `payments.payment_adapter` if your trusted order storage uses IRT.
Apply the conversion once when producing the snapshot, not at every layer.
`payable` defaults to true for immutable, explicitly payable order stores.

Both initiation and callbacks call the loader inside a transaction. Always acquire
locks in this order: application order, Payment, PaymentAttempt. Other order
update/fulfillment paths must follow that order too. The callback supplies the
stored owner to the hook; it does not require the browser to be logged in.
Never bind a callback to a request-controlled user/order.

Initiation uses a **durable** atomic block to commit its claim before HTTP. The
views are marked `non_atomic_requests`. Do not wrap service initiation in an
outer transaction or enable a surrounding transaction through another wrapper.
It deliberately refuses such nesting. Django TestCase's isolation is a special
test exception; use transaction tests for real commit/locking behavior.

If omitting the synchronous fulfillment hook, consume `FulfillmentEvent` using
your existing worker before claiming product delivery. Events are unique per
payment but delivery is at least once; use event IDs for downstream idempotency.
See payment-lifecycle.md for the crash window and reconciliation procedure.

## Next.js boundary

For a same-origin reverse proxy, send only the order reference with session
credentials and the application's CSRF token:

```typescript
const response = await fetch('/payments/initiate/', {
  method: 'POST',
  credentials: 'include',
  headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
  body: JSON.stringify({ order_reference: orderReference }),
});
if (!response.ok) throw new Error('Payment could not be initiated');
const payment = await response.json();
// Retain payment_id in authenticated order state before navigating away.
if (payment.redirect_url) window.location.assign(payment.redirect_url);
```

Django returns a redirect only for a locally pending authority. The browser
visits Zarinpal, which returns to Django's fixed callback. The callback verifies
and returns `{received: true}` without exposing a public result. For a frontend
return page, adapt that final response to a fixed configured/allowlisted frontend
URL. Do not propagate success from callback query flags. Retrieve the final
state from authenticated `GET /payments/<payment_id>/`; poll UNKNOWN/PENDING
with bounded backoff and provide a reconciliation message rather than treating
an unresolved result as either paid or unpaid.

For separate origins, configure exact CORS/CSRF origins, secure cookies and an
appropriate SameSite policy through existing auth infrastructure. Do not use
wildcard credentialed CORS, put merchant IDs in `NEXT_PUBLIC_*`, or verify payment
from Next.js client code. A Next.js server proxy must still preserve backend
authorization/CSRF protections or use the project's established service auth.

## Tests and deployment checks

Adapt the included tests to your app imports, URL prefix and auth strategy. Add
tests for the real order hooks, stale prices, tenant boundaries and outbox consumer.
Run migrations, Django checks and the project's test suite on the actual database.
Repository harness settings are test-only; never deploy them. Rate limiting,
TLS termination, DEBUG=False, cookie policy, alerts, a reconciliation job and
merchant acceptance testing remain application deployment work. Do not deploy
automatically or initiate live financial tests without explicit authorization.
