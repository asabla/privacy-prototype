# Prepare, review, export

These authenticated endpoints power the three workbench workflows at `/workbench`.
They can also be exercised from a client with the
[configured operator key](service-boundary.md).

## Use cases and policy

| Use case | Required fields | Policy `2026-09-30.3` |
| --- | --- | --- |
| `support_ticket` | `text` | Mask all detector findings, credential rules, and manual ranges before sharing a ticket |
| `ai_prompt` | `text` | Apply the same masks with consistent repeated-value placeholders within this request; never call an external AI provider |
| `email` | `sender`, `recipients`, `subject`, `body` | Remove entire routing fields and mask subject/body; report routing against the synthetic example's internal domains |

All three require explicit human review, including when there are no findings.
Recipient relationships are a review signal, not an allow/block verdict. The
example domains are defined in `backend/corpus.py`; they are not an organization's
approved policy. Email routing accepts one sender and up to 20 recipients in
comma-separated mailbox notation. Header newlines and invalid mailboxes fail.

Credential rules supplement either detector with credential-shaped values, short
or quoted password/token assignments, and private-key blocks. Policy `2026-09-30.3`
covers quoted JSON/YAML keys, escaped quotes, closed multiline quoted values and
indented YAML literal/folded blocks. Unfinished quoted values are covered through
their first line; malformed or other credential formats still require review.
Block coverage stops at the next nonblank line at the key's indentation or less.
The output is reviewed plain text and does not
promise valid JSON/YAML syntax after assignment redaction. These rules address
known fixture misses; they are not a complete secrets scanner. Model-only metrics
from `make eval` remain separate so policy safeguards cannot hide model misses.
Seventeen annotated cases in `evaluation/credential-cases.json` check policy coverage
independently of model findings, including negative reset/description examples.

Repeated identical values with the same label receive the same numbered placeholder
within one request, including across an email's subject and body. Numbering resets
for the next request, and generated placeholders avoid text already present in the
input. No reversible value map is retained. Different representations or model
labels may receive different placeholders. Context can still identify people.

## Request sequence

1. `POST /api/prepare` with a use case, fields, and optional `manual_masks`:

   ```json
   {
     "use_case": "support_ticket",
     "fields": {"text": "😀 Åsa met alice@example.com"},
     "manual_masks": [{"field": "text", "start": 2, "end": 5}]
   }
   ```

   Offsets are Unicode code points, start-inclusive and end-exclusive, relative to
   the submitted field. The response includes `candidate`, minimized `findings`
   (field, label, ranges, placeholder, sources), counts, warnings, and an opaque
   `review.receipt` valid for 600 seconds. It contains no source field or matched
   values. Unmatched sensitive content can remain in the candidate.

2. Review **every candidate field** and add masks for missed sensitive information.
   Re-submit the complete original fields plus all manual ranges to prepare a new
   candidate. Added masks preserve the union of automatic findings; they cannot
   remove an automatic mask. The service supports 128 manual ranges and at most
   512 pre-merge findings per detected field. Total source input is bounded to
   16,000 code points across fields. A candidate that cannot fit through the
   65,536-byte export request limit is rejected before a receipt is issued.

3. `POST /api/review/export` with `receipt`, the exact `candidate` object, and
   `confirmed: true`. Export returns `{ "schema_version": 1, "reviewed": true,
   "candidate": { ... }, "notice": "..." }`. Save or copy this returned artifact.
   A human confirmation is an assertion by the authenticated client, not proof of
   attention or approval by a second person. No email or external AI request occurs.

4. `POST /api/review/discard` with `receipt` when abandoning or replacing a candidate.
   Discard is idempotent. Clear original fields, candidate data, and access key in
   the client when finished. Server shutdown clears all pending receipts and events.

Changing candidate text, routing summary, use case, policy version, or engine makes
the old receipt invalid for that candidate. A fingerprint mismatch returns `409
candidate_changed`; missing, used, expired, or restarted-process receipts return
`410 review_unavailable`. A successful export atomically consumes its receipt,
including with concurrent requests. If a response is lost, prepare and review
again rather than retrying a consumed receipt.

## Data and operational boundaries

Source and candidate text exist transiently during processing. Between requests,
the server retains only an opaque token, a keyed fingerprint of the canonical
candidate, expiry, and non-content metadata. Fingerprints use a random process key
and are not returned in API responses. No original text, candidate text, matched
values, or reversible placeholder maps are retained in the review store. Memory
objects can survive temporarily in the runtime and are not securely erased.

The store is bounded to 256 outstanding receipts. Expired records are pruned on
store operations; reaching capacity returns `429 review_capacity_reached`. There
is no background disk store or cross-process replication. Run one worker; a
restart invalidates receipts and rotates the fingerprint key. This intentionally
does not provide durable queueing or distributed review sessions.

`GET /api/review/events` requires authentication and returns the last 128 events
until restart: generated event ID, time, configured-operator identity, action,
use case, engine, policy version, and mask counts. It excludes text, addresses,
tokens, fingerprints, and URLs. This is a bounded demonstration of minimized
audit events, not a durable or tamper-evident compliance audit. Add a separately
governed metadata sink and real identities for a shared service.

`tests/test_review.py` covers all three workflows, Unicode/manual masks, known
credential misses, metadata disclosure, altered candidates, explicit confirmation,
expiry, replay, concurrency, bounded stores, and process-instance separation.
`make test-opf` exercises each workflow with the real model and exports/replays the
reviewed candidates. Neither check establishes accuracy on unlabelled real input.
