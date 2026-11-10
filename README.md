# Iranian Payment Gateways

A reusable Codex skill for integrating, debugging, testing and auditing Zarinpal
payments in existing applications. **Implemented: Zarinpal.** Phase 1 prioritizes
Python 3.12 / Django 5.2, including backends with a separate Next.js frontend.

The repository provides one skill with an actionable discovery workflow, source
references, configuration/integration validators, and executable Django reference
assets. It does not generate a complete SaaS app. Other gateways/framework
adapters, refunds, settlements, payouts, subscriptions and split payments are not
implemented. Integrating an existing subscription's fulfillment is supported
through the application's own business hook.

## Install and invoke

Use the existing selected repository, `phantomf4321/Iranian-payment-gateways-skill`.
The skill's name is `iranian-payment-gateways`; the existing GitHub repository has
not been renamed. Phase 1 is distributed from **`zarinpal`**, with `master` kept
as the unchanged baseline.

In Codex with the official skill-installer available, request:

```text
Use $skill-installer to install the skill at
https://github.com/phantomf4321/Iranian-payment-gateways-skill/tree/zarinpal/.agents/skills/iranian-payment-gateways
```

The official installer accepts repository/path/ref selections, installs the
directory under Codex's skills directory, and makes it available on the next
turn. Do not install the repository root as the skill. Alternatively, clone
the `zarinpal` branch and copy the **entire**
`.agents/skills/iranian-payment-gateways` directory into your target project's
`.agents/skills/` (preserve existing skills; do not overwrite one without review).
Open that project in Codex. In this repository the project skill is already in
its discovery path; this does not imply it is globally installed.

Example invocations:

```text
Use $iranian-payment-gateways to integrate Zarinpal into this Django project.
Use $iranian-payment-gateways to inspect and fix the payment verification flow.
Use $iranian-payment-gateways to implement payment initiation and callback handling in my Django + Next.js application.
Use $iranian-payment-gateways to audit duplicate payment fulfillment risks.
Use $iranian-payment-gateways برای اتصال درگاه پرداخت زرین‌پال.
Use $iranian-payment-gateways برای بررسی و اصلاح درگاه زرین‌پال.
```

## Contents

```text
.agents/skills/iranian-payment-gateways/
  SKILL.md                     # One authoritative skill definition
  agents/openai.yaml           # Codex UI metadata
  references/                  # Architecture, API evidence, lifecycle, security,
                               # Django/Next.js integration and troubleshooting
  scripts/                     # Skill, config and integration validation
  assets/templates/django/     # Adapter, service, models/migration, views, URLs,
                               # read-only admin, env example and payment tests
tests/                         # Harness and validator regression tests
```

## Django integration

Let Codex inspect and reuse existing payments/orders first. If a new app is
needed, adapt the assets as `payments`, wire the order loader and optional
same-database fulfillment hook, configure URLs/auth/CSRF, and review migrations.
Templates are reference implementations, not safe to copy into every app
unchanged. See the skill's `references/django-integration.md` for the complete
hook contract, settings mapping and concise Next.js example.

| Setting | Purpose |
| --- | --- |
| `ZARINPAL_MERCHANT_ID` | Backend-only UUID from secure merchant configuration |
| `ZARINPAL_SANDBOX` | Explicit true/false selection; never Python truthiness of strings |
| `PAYMENT_CALLBACK_URL` | Fixed public HTTPS Django callback (localhost HTTP only in sandbox) |
| `PAYMENT_CURRENCY` | IRR only at persistence and transport boundaries |
| `PAYMENT_MIN_AMOUNT_IRR`, `PAYMENT_MAX_AMOUNT_IRR` | Local integer policy; confirm merchant-specific limits |
| `PAYMENTS_ORDER_LOADER` | Required Django setting: import path to existing-order hook |
| `PAYMENTS_FULFILL` | Optional Django setting: same-database fulfillment hook |

Environment variables are not loaded automatically: map them through your
project's settings loader. No real credentials are needed for tests. The
template `.env.example` uses an inert UUID and cannot authorize payments.

The backend authorizes the order, freezes integer IRR, creates one gateway request,
and returns its redirect. Django verifies the callback server-to-server before
success. Next.js holds no merchant secret and obtains final status from an
authenticated backend endpoint. Advisory cancellation and transport uncertainty
do not become false success or an automatic second charge.

## Development and checks

Run from the repository root; Python 3.12+ is required:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/python -m django check --settings=tests.settings
.venv/bin/python -m django makemigrations --check --dry-run --settings=tests.settings
```

The default suite uses SQLite and explicitly skips PostgreSQL concurrency tests.
For the complete suite, run a local **test-only** PostgreSQL instance:

```sh
docker run -d --name zarinpal-test-postgres \
  -e POSTGRES_USER=payments -e POSTGRES_DB=payments \
  -e POSTGRES_HOST_AUTH_METHOD=trust \
  -p 127.0.0.1:55432:5432 \
  postgres@sha256:5264710be20f409750ac6dc4e5706dcef929c87e241605463f0f9aefa932a8d9
docker exec zarinpal-test-postgres pg_isready -U payments -d payments
PAYMENTS_TEST_POSTGRES=1 .venv/bin/python -m pytest -q
docker stop zarinpal-test-postgres
```

Wait for `pg_isready` to report accepting connections before running tests.
If reusing this dedicated container after stopping it, use `docker start`.
Trust authentication here is only for the disposable loopback-bound test server;
never use it for a deployed or shared database. To use an existing test server,
set `PGHOST`, `PGPORT`, `PGUSER`, `PGDATABASE`, and securely `PGPASSWORD` as needed.
The test role must be able to create a disposable test database. Tests mock gateway
HTTP and block the real httpx transport; they never spend money.
The GitHub Actions workflow runs the full PostgreSQL suite and validators on
`zarinpal` pushes and pull requests targeting `master`.

Run all three validators (paths shown explicitly so no shell activation is needed):

```sh
.venv/bin/python .agents/skills/iranian-payment-gateways/scripts/validate_skill.py
.venv/bin/python .agents/skills/iranian-payment-gateways/scripts/validate_config.py \
  --env-file .agents/skills/iranian-payment-gateways/assets/templates/django/.env.example
.venv/bin/python .agents/skills/iranian-payment-gateways/scripts/validate_integration.py \
  .agents/skills/iranian-payment-gateways/assets/templates/django
```

`validate_skill` reuses the vendored official OpenAI metadata validator and adds
resource/link/syntax checks. `validate_config` accepts the actual environment or
a simple env file without executing shell syntax or displaying values.
`validate_integration PATH` inspects Python/JS source heuristically for payment
components, verification, locking, tests, configuration and obvious credential
exposure. It does not execute target code. Validators return 0 for passing checks,
1 for findings/config errors, and argparse's 2 for invalid CLI usage. Static scans
and structure validation cannot certify security or financial correctness.

## Reliability and security

Money is integer IRR; convert trusted IRT once using `to_irr`. Never accept prices
from a client or change a price at verification. Persist creation claims durably
before HTTP; never retry an ambiguous create. Serialize verification/finalization
with PostgreSQL row locks, unique authority/reference constraints and a unique
fulfillment event. `SUCCEEDED` is terminal. A timeout, malformed response, or
unclassified verification rejection remains `UNKNOWN` for reconciliation.

Keep merchant credentials in backend secure configuration, DEBUG off in production,
TLS verification on, and raw bodies/card details out of logs and APM. Admin is
read-only. Implement host-specific throttling, order invariants, same-database
business hooks, an idempotent outbox consumer and an operational reconciliation
process before rollout. The reference does not provide a background worker or
automatically configure CORS, rate limits, cookies, secrets or production deployment.

## Protocol evidence and limitations

Official Zarinpal Python and Node SDK sources were inspected at pinned commits
on **2026-11-11**. The adapter implements v4 create/verify and 100/101 handling,
fixed sandbox/production hosts, explicit timeouts and strict response parsing.
Direct HTTP avoids the inspected Python SDK's test-package runtime pins, raw
response logging and missing timeout. See `references/zarinpal-api.md` for exact
source URLs and the compatibility assessment.

The direct documentation sites were blocked in the implementation environment.
SDK minimum amounts disagree; the default 10,000 IRR minimum is conservative local
policy, and the maximum is also local policy. Confirm terminal-specific limits,
callback parameter conventions and sandbox availability against current merchant
documentation. A 101 without a valid reference remains unresolved. No live or
sandbox merchant transaction was executed. Do not treat mocked tests as live
acceptance evidence or automatically deploy this reference.

For unknown authorities, repeated callbacks, tenfold errors and timeouts, use
`references/troubleshooting.md`. Never resolve an error by inventing payment
success, guessing an authority or blindly retrying creation.

License: Apache-2.0. See LICENSE and THIRD_PARTY_NOTICES.md for the official
validator's provenance. A second provider is future work: retain the small gateway
contract and add independently sourced protocol evidence and contract tests;
do not add it as part of Phase 1.
