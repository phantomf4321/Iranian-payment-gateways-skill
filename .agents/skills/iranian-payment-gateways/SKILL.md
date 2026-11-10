---
name: iranian-payment-gateways
description: Integrate, debug, test, and audit Iranian online payments using Zarinpal (Phase 1 only), prioritizing Python/Django backends and Django with Next.js. Use for adding a secure payment gateway, payment initiation or verification, fixing Zarinpal callbacks, preventing duplicate payment fulfillment, auditing Django payments, and generating integration documentation. Support English and Persian requests including اتصال درگاه پرداخت زرین‌پال and بررسی و اصلاح درگاه زرین‌پال.
---

# Iranian payment gateways — Zarinpal

## Discover before editing

1. Read project instructions and inspect the working tree. Use the existing
   checkout; do not create a worktree unless explicitly requested.
2. Find the backend framework, dependency/version pins, configuration conventions,
   database, tests, frontend/backend trust boundary, and authentication scheme.
3. Locate existing payment, order, invoice, subscription, fulfillment, and outbox
   code. Trace the authoritative price and ownership checks. Reuse these components;
   do not generate a parallel payment system or assume an order schema.
4. Classify the task as integration, repair, audit, or documentation. For an audit,
   report evidence with file locations and severity before making unrelated changes.
5. Support only Zarinpal. For other frameworks, apply the domain workflow and
   explain that executable adapters here target Django; do not claim another
   framework/provider adapter exists.

## Load only relevant resources

- Read [architecture](references/architecture.md) when choosing integration boundaries.
- Read [Zarinpal API evidence](references/zarinpal-api.md) before changing transport
  behavior. Recheck official sources when protocol details matter; distinguish
  verified SDK evidence from unavailable documentation and untested live behavior.
- Read [payment lifecycle](references/payment-lifecycle.md) for persistence,
  transitions, timeouts, idempotency, and reconciliation.
- Read [security](references/security.md) for every implementation or audit.
- Read [Django integration](references/django-integration.md) when adapting the
  [Django assets](assets/templates/django), configuring hooks/migrations, or pairing
  Django with Next.js.
- Read [troubleshooting](references/troubleshooting.md) for callback failures,
  amounts, unknown outcomes, or repeat fulfillment.

## Implement the smallest complete flow

1. Reuse the existing configuration and secure secret bindings. Keep credentials
   on the backend; never log or copy their values. Require an explicit environment.
2. Fetch and authorize the order on the server. Freeze a positive integer IRR
   price. Convert trusted integer IRT once at the order boundary, never from a
   frontend amount or during verification. Apply terminal-approved local limits.
3. Separate gateway HTTP from domain orchestration. Use a small `PaymentGateway`
   protocol; keep local payment status in the service, not an invented gateway API.
4. Adapt assets into the existing app rather than blindly copying them. If a new
   Django app is appropriate, copy `assets/templates/django` as `payments`, wire
   the order/fulfillment hooks, and inspect or generate migrations. Preserve existing
   models, permissions, routing, dependency constraints, and client contracts.
5. Commit a unique creation claim before sending a payment request. Store its
   authority before returning a gateway redirect. Never automatically repeat
   creation after a timeout, crash, or malformed result.
6. Treat callback flags as untrusted. Resolve the stored authority and environment,
   verify server-to-server with the frozen price, validate the result, and persist
   success atomically with fulfillment intent. Treat `101` as already verified
   only with adequate local association and valid reference evidence.
7. Serialize finalization with database locks and uniqueness constraints. Keep
   same-database business writes in the finalization transaction. Use a durable
   outbox and a consumer idempotency key for external effects; do not claim
   exactly-once network delivery from a local transaction.
8. Preserve `UNKNOWN` for ambiguous outcomes. Never change `SUCCEEDED` back to
   pending/failed, invent a reference, mark success from HTTP 200, or trust a
   frontend success flag. Do not add refunds, payouts, or other Phase 2 operations.
9. Keep initiation authenticated, authorized, and CSRF-protected as appropriate.
   Use a narrow GET callback without requiring browser CSRF tokens. Make status
   retrieval private and use only fixed, trusted return destinations.
10. Add bounded transport timeouts, safe verification retries, sanitized errors,
    and rate limiting through the target app's existing infrastructure.

## Validate and deliver

1. Run `scripts/validate_config.py` against the effective environment or a secure
   local env file. Never print settings, credentials, raw responses, or card data.
2. Run `scripts/validate_integration.py PATH` as a heuristic audit. Review every
   finding; a passing scan is not proof of security or financial correctness.
3. Adapt and run asset tests covering request failures, malicious prices,
   verification semantics, unknown outcomes, malformed/repeated callbacks,
   authorization, and rollback recovery. Mock all routine gateway calls.
4. Run concurrent finalization and initiation tests on PostgreSQL or the target
   production database. Report skips honestly; SQLite cannot prove row locking.
5. Run target-project checks and review the final diff and secret exposure. Run
   `scripts/validate_skill.py` when modifying this skill itself.
6. Report changed files, executed checks/counts, diagnosed defects, unresolved
   protocol details, hook/migration work, and required environment settings. Write
   integration-specific operational documentation in the target project.

Never automatically deploy or initiate live financial transactions. Request
explicit authorization for any live financial test; prefer mocked tests and
documented sandbox testing.
