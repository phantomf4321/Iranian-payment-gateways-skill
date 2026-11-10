# Architecture and adaptation

Phase 1 implements Zarinpal only. The skill is framework-independent orchestration
with one executable Django 5.2/Python 3.12 reference app. Other framework adapters
and providers are future work. Assets are adaptable reference implementations,
not an automatically installed application or a payment certification.

## Boundaries

| Component | Responsibility |
| --- | --- |
| `PaymentGateway` | Typed creation/verification results and redirect construction |
| `ZarinpalGateway` | Fixed v4 hosts, merchant payload, transport, strict parsing |
| `PaymentService` | Ownership, immutable payment snapshot, state, persistence, locks |
| Order loader hook | Existing schema, user authorization, payable price and order locking |
| Fulfillment hook | Same-database business writes after verification |
| `FulfillmentEvent` | Unique durable handoff for external effects |
| Views | HTTP shape, auth, methods, callback parsing; no financial truth in browser |

`get_payment_status` is a local service lookup. No gateway status API is invented.
Do not use GraphQL access tokens for the two v4 merchant operations. There is no
provider registry or plugin loader; adding a second provider later requires
reviewing the contract, per-provider currencies, states, uniqueness scopes, and
contract tests first.

## Discovery checklist

Inspect dependency/lockfiles, settings modules, URLs, auth middleware, order/invoice
schemas, money units, tenant boundaries, existing payment tables, jobs, webhook
handlers, delivery/credit logic, database routers, tests, and deployment secrets.
Use existing equivalents of these components before adding tables or dependencies.
For repairs, reproduce the failure before replacing a working subsystem.

The reference associates a unique `order_reference` string and protected owner
with a payment. In a target app, prefer its real order relation and tenant-aware
uniqueness. Freeze the payable price through the application's own order policy;
if the order can change, reject fulfillment of a stale price and reconcile the
received payment instead of silently altering the recorded amount.

Keep order and payment writes in one database. Follow order, Payment, then
PaymentAttempt lock ordering across initiation, verification, order updates and
fulfillment. The loader is called before payment locks on both service paths.
The loader and fulfillment hook are application-specific contracts, not generic
helpers that can guess business rules.

## Intentional tradeoffs

Verification keeps a payment row lock across bounded HTTP attempts and database
finalization. This favors a small, understandable correctness model over throughput.
Configure appropriate connection/read timeouts, lock waits, worker capacity, and
callback throttling. HTTP timeouts are per phase; a slow stream is not bounded by
a single wall-clock deadline. High-volume systems may replace this with a durable
verification job/lease, while retaining the unique finalization transaction.

Creation runs outside the database transaction after a durable local claim; its
service refuses an outer transaction and the views use `non_atomic_requests`. A
process crash or authority uniqueness conflict can leave `CREATED` without an
authority; this is deliberately blocked from recreation and needs reconciliation.
There is no automatic expiry, no dashboard reconciliation API, and no automatic
new attempt after an advisory cancellation. Add such behavior only with verified
provider semantics and a safe operational process.
