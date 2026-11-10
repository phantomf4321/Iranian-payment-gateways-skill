# Troubleshooting Zarinpal integrations

| Symptom | Check and action |
| --- | --- |
| Missing merchant or ambiguous environment | Run config validator without dumping settings; check secret binding names and explicit true/false parsing |
| Tenfold price difference | Inspect canonical unit and `to_irr` call at order boundary; verification must reuse the stored IRR unchanged |
| Callback unknown authority | Compare local persisted attempt and environment; investigate a lost creation response or callback arriving before authority persistence |
| Callback 400 | Check exactly one `Authority` and one `Status`, authority format, OK/NOK; confirm actual provider query conventions against current docs |
| Browser returns success but order unpaid | Callback flags are not proof; inspect private backend status and verification event |
| HTTP 200 but no success | Check numeric `data.code` and required identifiers; raw HTTP status is insufficient |
| 101 but no local finalization | Require matching local attempt and valid numeric reference; missing ref stays UNKNOWN pending reconciliation |
| Creation UNKNOWN or stale CREATED | Do not retry the POST; investigate merchant dashboard and safe authority recovery |
| Verification UNKNOWN | Inspect sanitized numeric code and local state; retry only known-authority verification through an authorized reconciliation process |
| Negative verification code | Consult current official code meaning; the reference conservatively preserves UNKNOWN rather than guessing a permanent rejection |
| CANCELED but merchant says paid | Cancellation is advisory; reverify the existing authority; never create a second obligation |
| Repeated delivery | Check all fulfillment paths, DB uniqueness, row locks, transaction rollback, and downstream deduplication by outbox event ID |
| Callback blocks or deadlocks | Inspect lock order, DB wait timeouts and bounded HTTP calls; throttle or move verification to a durable job at higher volume |
| Production request rejected below/above limits | Verify merchant-specific limits; local defaults are policy, not certified API limits |
| Works in tests but not deployment | Check real PostgreSQL locking, applied migrations, effective callback URL, merchant environment, TLS and access policy |

For a repair, capture a failing test from sanitized local facts and mock responses.
Inspect existing order/subscription/wallet logic before adding any tables. Do not
paste full gateway bodies, merchant values, card details, or cookies into reports.
Record only local payment ID, state, timestamps, operation, and safe numeric code.

For API disagreements, open the pinned official source links in `zarinpal-api.md`
and compare with accessible current documentation. Separate transport failures
from explicit rejection and from invalid JSON/schema. Never disable TLS checks,
replace stored prices, invent identifiers, or mark success to resolve a callback.
