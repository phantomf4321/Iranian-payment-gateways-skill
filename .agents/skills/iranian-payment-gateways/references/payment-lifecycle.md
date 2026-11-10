# Payment lifecycle, locking, and recovery

A `Payment` is one immutable payable obligation (owner, order reference, integer
IRR amount, provider, environment). `PaymentAttempt` records each gateway creation
attempt. Rejected creations may be retried explicitly; pending/uncertain ones
must not be duplicated. The model allows only one nonfailed attempt per payment.

## Legal transitions

| State | Next states | Meaning |
| --- | --- | --- |
| CREATED | PENDING, FAILED, UNKNOWN | Durable request claim; a crash may leave it here |
| PENDING | VERIFYING, CANCELED | Authority stored; no proof of payment yet |
| VERIFYING | SUCCEEDED, UNKNOWN | Authoritative verification under a row lock |
| UNKNOWN | VERIFYING | Ambiguous transport, negative verify code, malformed result |
| CANCELED | VERIFYING | Advisory browser cancellation; later verification may recover |
| FAILED | CREATED | Explicit creation rejection only; a new attempt is permitted |
| SUCCEEDED | none | Verified and atomically finalized; cannot regress |

Self-transitions do not change state. No `EXPIRED` state is modeled because no
verified expiry policy was available. No callback flag can cause `FAILED` or
`SUCCEEDED`. A `NOK` on `UNKNOWN` does not erase uncertainty. A `NOK` on a
successful record does not undo success.

## Creation

Authorize an existing order through the order loader and freeze its price. Under
a transaction, get/create the unique payment and lock it before deciding whether
to reuse it or create an attempt. Commit the attempt claim before HTTP. Send one
create request. Persist its authority and PENDING state before returning its
redirect. Never return an arbitrary URL from a gateway body or frontend input.

If creation times out or parsing fails, keep UNKNOWN. Repeated initiation is a
conflict, not another POST. If a process dies after sending, CREATED without an
authority is also unresolved. A duplicate authority constraint error must be
investigated; do not auto-repeat creation to conceal it.

## Verification and finalization

1. Validate callback shape and authority; resolve it to the stored attempt.
2. Lock the application order using the loader, then `Payment`, then its
   `PaymentAttempt`, within `transaction.atomic`.
3. Return immediately if already SUCCEEDED. Record cancellation only as advisory.
4. Verify with the stored authority, amount, and environment. Increment a local
   verification invocation counter (an invocation can make two bounded HTTP calls).
5. Require code 100/101 plus a valid numeric reference; reject contradictory echoes.
6. Save success, reference, verification time, and unique `FulfillmentEvent` together.
7. Execute only same-database fulfillment writes within that transaction. On an
   exception, all writes roll back. A later verification may return 101 and recover.

`VERIFYING` is normally not externally visible because it is inside the same
transaction. A process crash rolls it back; it does not release an unguarded
in-progress flag. PostgreSQL row locks serialize simultaneous callbacks. Unique
reference and one-to-one fulfillment constraints give additional protection.
SQLite tests do not establish production locking correctness.

## External fulfillment

The included event is a durable outbox row, not an implemented email/wallet worker.
Create a consumer using the existing job system: claim events with database locks,
send the event ID as the downstream idempotency key, and mark delivered only after
acknowledgment. A worker can crash after remote delivery and before marking the
row; the destination must deduplicate redelivery by the event ID. Without remote
idempotency support, exactly-once delivery cannot be guaranteed; report that limit.
Never send external effects directly from `fulfill` or rely only on `on_commit`.

## Reconciliation

Monitor old CREATED/PENDING, UNKNOWN, advisory CANCELED, and undelivered events by
indexed timestamps. An authorized job may reverify a known persisted authority
through the service (using the OK verification path), with a bounded retry policy.
Do not expose an unauthenticated general-purpose retry endpoint. No automatic
scheduler is included. If the authority was lost, investigate through the merchant
dashboard/current official support tools and a documented association process;
never guess it, create a replacement payment, or manually mark success.
