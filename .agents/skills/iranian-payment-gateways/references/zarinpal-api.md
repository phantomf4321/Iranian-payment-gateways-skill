# Zarinpal v4 — evidence and uncertainties

Source inspection date: **2026-11-11**. No live merchant or sandbox transaction
was performed. Protocol fixtures are synthetic, based on source shapes.

## Authoritative sources inspected

| Source | Revision / evidence |
| --- | --- |
| [Official Python SDK](https://github.com/ZarinPal/Zarinpal-Python-Sdk/tree/f402671430246fd7e244ef29c47f14fe56f706d1) | `setup.py` 0.1.4; `src/zarinpal-py-sdk/zarinpal.py`, `resources/Payments.py`, `resources/Verifications.py`, `zarinpal_utils/Validator.py`, examples and tests |
| [Official Node SDK](https://github.com/ZarinPal/ZarinPal-node-SDK/tree/30813f30d33c9e61df78d3be01bab9db1b4c6c64) | package 2.2.0; `src/Zarinpal.ts`, `resources/Payments.ts`, `resources/Verifications.ts`, `utils/Validator.ts`, examples and tests |
| [Official gateway documentation](https://www.zarinpal.com/docs/paymentGateway/) | Access blocked by this environment's outbound policy (HTTP tunnel 403); not read |
| [Codex skills documentation](https://developers.openai.com/codex/skills) | Access blocked; used official `openai/skills` creator and installer instead |
| [OpenAI skill-creator](https://github.com/openai/skills/tree/49f948faa9258a0c61caceaf225e179651397431/skills/.system/skill-creator) | Structure, metadata, progressive disclosure, UI schema, init and validation tools |
| [OpenAI skill-installer](https://github.com/openai/skills/tree/49f948faa9258a0c61caceaf225e179651397431/skills/.system/skill-installer) | GitHub repo/path/ref distribution and installation into Codex's skills directory |

## Verified from SDK source

| Operation | Protocol |
| --- | --- |
| Create | `POST https://payment.zarinpal.com/pg/v4/payment/request.json` |
| Verify | `POST https://payment.zarinpal.com/pg/v4/payment/verify.json` |
| Sandbox | Replace host with `sandbox.zarinpal.com` (same paths) |
| Redirect | Selected SDK base host + `/pg/StartPay/` + authority |
| Authentication | JSON `merchant_id` (UUID); no bearer token for these operations |
| Create payload | `merchant_id`, integer `amount`, `callback_url`, `description` |
| Verify payload | `merchant_id`, persisted integer `amount`, persisted `authority` |
| Create result | `data.code == 100`, `data.authority`; fee fields unused |
| Verify result | `data.code == 100`, `data.ref_id`; card/fee fields are not persisted |
| Reverification | Both SDK verification examples label `101` as already verified |
| Authority | Both validators use `[AS][a-zA-Z0-9]{35}` |
| Callback examples | Authority/status variables, `OK` for verification |

The adapter accepts a `101` only with a positive numeric `ref_id` and an existing
local authority and frozen amount. The SDK examples do **not** demonstrate whether
every `101` includes a reference. Missing reference remains `UNKNOWN` for manual
reconciliation; never invent a reference or finalize an unrelated payment.

The callback route uses conventional query names `Authority` and `Status` and
accepts `OK`/`NOK`. Exact public query casing and cancellation values were not
independently confirmed against live documentation. Confirm them with your
terminal's current docs before going live. Missing/other values fail closed.

## Currency and limits

The Python Payments docstring explicitly describes IRR. Neither SDK's typed core
creation/verification interface proves an optional currency field there. Both
have IRR/IRT validation for fee calculation, which is not evidence that all
operations accept IRT. Therefore this adapter sends integer IRR and omits a
currency field. Convert trusted integer toman (`IRT`) to IRR once, multiplying by
10 in `to_irr`; store the resulting IRR and never reconvert it during verification.

The Node validator minimum is 1,000; the Python validator minimum is 10,000,
contradicting its docstring/tests. The template adopts **10,000 IRR** as a
conservative local minimum. Its **1,000,000,000,000 IRR** maximum is a local
application ceiling, not a verified gateway or merchant limit. Set both according
to your merchant agreement and current official docs. No terminal-specific maximum
or sandbox availability was verified. Keep all money within signed 64-bit storage.

## Errors and reliability

SDKs return raw response data and do not normalize every API code. The adapter
recognizes negative numeric codes in `errors` or `data` as explicit rejections;
raw error messages are discarded. Creation rejection becomes `FAILED` and can
be retried by a new explicit initiation. Verification rejections remain `UNKNOWN`
with the numeric code because the complete terminal/transient error taxonomy was
unavailable. No guessed error-code catalog is implemented.

Neither inspected SDK sets an explicit REST timeout. The adapter supplies 3s
connect/pool and 10s read/write timeouts, disallows HTTP redirects, never retries
creation, and allows one verification retry for transport errors/429/5xx.
It never treats HTTP 200 alone as success. The provider is responsible for amount
validation in the verify request; the standard success fixture does not echo the
amount or authority. When echoes are present, the adapter checks their values
and types. It cannot independently prove an omitted echo.

## SDK evaluation

The official Python checkout declares Python >=3.12 and pins Requests 2.32.4,
pytest, requests_mock, and setuptools as runtime dependencies. It exposes broad
top-level package names (`resources`, `errors`), raw responses, no explicit HTTP
timeout, and error logs containing upstream bodies. Its tests/docstrings disagree
with its minimum validator. These are concrete compatibility/security reasons
for a small direct HTTP adapter with injectable `httpx.Client`, not a claim that
the SDK is abandoned. Maintenance cadence and current PyPI releases were not
independently audited. Use these source revisions as evidence, recheck before
updating the protocol, and perform an explicitly authorized sandbox/merchant
acceptance test before production rollout.
