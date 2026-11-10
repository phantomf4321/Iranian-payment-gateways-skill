# Security review

## Trust boundaries

- Accept only an order reference at initiation. Authenticate and authorize the
  order; fetch its immutable payable price from server-owned data.
- Keep IRR as the canonical integer unit. Never use floats, round a fractional
  amount, trust a frontend price, or convert again at verification.
- Never expose merchant configuration in browser bundles, Next.js public variables,
  API responses, logs, Django admin forms, or transaction tables.
- Require explicit sandbox selection and fixed HTTPS production callback/gateway
  URLs. Keep TLS verification enabled. Do not accept custom gateway hosts or
  arbitrary return URLs. HTTP localhost is for sandbox development only.
- Treat Authority, Status, and redirect flags as untrusted. Resolve local ownership
  and authority first, and verify server-to-server with the persisted amount.

## Configuration and logging

Load credentials using the target project's secure environment/secret store.
Use the format-only config validator without displaying values. Set Django DEBUG
off in deployment; configure its exception reporter, APM and HTTP debugging to
redact merchant IDs, request JSON, session tokens, callback authority, and upstream
bodies. The adapter hides the merchant in its config repr, discards raw error
messages, and logs only fixed events with local payment IDs. Do not enable HTTP
body tracing. No card PAN/hash, email, mobile, or bearer token is persisted here.

## Endpoint controls

Session-based initiation needs CSRF protection; the GET callback does not require
a browser CSRF token and must not be changed to a general CSRF-exempt mutation API.
Use least-privilege methods, strict parameter multiplicity, small request limits,
authenticated owner-only status, and throttling on initiation, callbacks and polling.
The callback intentionally returns only a receipt acknowledgment, not a payment
result. A fixed frontend return page may be added by configuration and must read
the authenticated backend status. Do not interpolate request-controlled destinations.

Rate limits, CORS, CSRF trusted origins, session cookie policy, cross-site auth,
body-size limits and abuse monitoring depend on the host app and its proxy; the
reference does not configure them automatically. Restrict callbacks by behavior,
not a guessed provider IP list: this is a browser redirect and can arrive from users.

## Persistence controls

Use PostgreSQL in production for demonstrated row-lock behavior. Keep every
path that finalizes an order behind the same transaction and consistent lock
order. Never expose write APIs or admin actions that mark unverified records paid.
Use DB constraints for positive IRR, valid states, unique authority/reference,
one unresolved attempt, and one fulfillment event. Application transition checks
do not protect against direct SQL or arbitrary ORM updates; restrict those paths
and database permissions. Add business-specific guards to the fulfillment hook.

Do not silently reuse a payment for a different owner, amount, or environment.
Credential rotation for a merchant/terminal with unresolved attempts needs an
operational plan: retain the correct merchant binding for reconciliation. The
template supports a single configured merchant, not terminal/account rotation.

## Reliability and acceptance review

Creation is never retried automatically. Timeout does not prove rejection. Verify
retry is bounded and can recover an already-verified result without repeating
fulfillment. Unknown/malformed results never activate an order or credit a wallet.
An untrusted cancellation can be recovered by authoritative verification.

Run mocked adapter tests, endpoint authorization/CSRF tests, rollback tests, and
real PostgreSQL concurrent callback/initiation tests. Review hook implementation,
outbox consumer, lock order, effective settings, migration plan, terminal amount
limits, current protocol docs, alerts and reconciliation before rollout. These
templates and static checks alone are not evidence of production readiness.

Never initiate live financial transactions, deploy, or install production merchant
credentials as part of routine tests. Require explicit authorization and record
the environment and expected financial effect for any live acceptance test.
