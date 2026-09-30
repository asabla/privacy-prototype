# Sensitive-data reference project

Objective: a working, demonstrable system that developers can use as a reference
for handling sensitive data, with privacy-team review flows. This document tracks
the full objective; passing a single package does not complete it.

## Product workflows

1. **Share a support ticket:** enter or load synthetic ticket text, analyze it
   locally, inspect suggested masks, add missed redactions, explicitly review the
   resulting text, and download only the reviewed result.
2. **Prepare an AI prompt:** remove sensitive values while preserving repeated
   entities through per-request placeholders; review and copy the result. The
   reference does not send prompts to an external model provider.
3. **Review an email:** inspect subject, body, and routing metadata, distinguish
   sensitivity from a policy decision, and export a minimized review artifact.
   The existing synthetic inbox remains an entry point. Mailbox integration is a
   separate adapter, not required to exercise the complete review workflow.

## Acceptance requirements and evidence

| ID | Requirement | Evidence required before completion |
| --- | --- | --- |
| R1 | All three workflows run from input through review, export, and clear/reset | Browser walkthroughs and DOM/API integration tests covering actual payloads |
| R2 | Arbitrary input requires authentication; demo fixtures can remain public on loopback | Missing/invalid/valid credential tests; documented local and hosted setup; no credentials in source or browser persistence |
| R3 | Minimized API responses are the default; input and matched values do not appear in validation errors, application logs, or audit events | Sentinel-value tests on success and failure paths; explicit inspection contract |
| R4 | Export is bound to the exact reviewed candidate, policy, and engine; tampering, expiry, and replay fail | End-to-end tests for valid approval, changed content, expired receipts, and repeat export |
| R5 | Reviewers can add masks for model misses; credential safeguards cover known sample misses; no claim of complete anonymization | Labeled evaluation, targeted regressions, manual-mask tests, visible residual-risk explanation |
| R6 | Requests and inference are bounded, errors are controlled, and failure never releases an unreviewed result | Oversized/chunked body tests, concurrency tests, inference failure tests, operational checks |
| R7 | Sensitive input is transient; browser state clears; no raw-data database, analytics, third-party assets, or outbound inference call | Data-flow review, browser/storage/network checks, clear/reset tests, documented retention boundaries |
| R8 | Host/origin checks and browser response headers protect the local service | Cross-origin/host tests, security-header tests, live browser checks |
| R9 | Setup is reproducible and operator settings fail safely | Locked native setup, a non-root container path, health/readiness checks, configuration tests, a clean-start walkthrough |
| R10 | Reference documentation explains use cases, trust boundaries, limits, model evaluation, and extension points | Runnable examples, API contract, threat model, showcase walkthrough, and current screenshots |
| R11 | Changes remain reviewable and verified | Scoped PRs, local tests, dependency audits, green CI, real OPF checks, merged default-branch verification |

## Ordered work packages

- **W1 — Service boundary:** explicit settings, authentication for submitted text,
  safe errors, no-store responses, host/origin protections, body and concurrency
  limits. Keep synthetic inbox behavior intact. Gate: API adversarial tests and
  existing checks.
- **W2 — Processing and review contract:** versioned use-case policies, minimized
  findings, credential rules, per-request placeholders, manual masks, expiring
  review/export receipts, and metadata-only audit events. Gate: disclosure,
  tampering, replay, expiry, and model-failure tests.
- **W3 — Complete workbench:** the three workflows, clear data boundaries,
  accessible review controls, explicit export, and reliable reset/error recovery.
  Gate: browser plus payload/storage checks on every workflow.
- **W4 — Runtime and evaluation:** container setup, readiness, preloaded model
  operation, repeatable load/failure checks, expanded labeled cases, measured gaps.
  Gate: clean native/container launches, deterministic checks, and real OPF checks.
- **W5 — Showcase and final audit:** current documentation and screenshots,
  reproducible walkthrough, merged CI and requirement-by-requirement verification.

## Trust and scope

The reference serves one configured operator/API principal. A shared hosted or
multi-tenant deployment needs a real identity provider and tenant isolation; it
must not infer identity from a browser-supplied user name. Raw input is processed
in memory, which is not a promise of physical memory erasure. Redaction is a data
minimization aid with measured misses, not an anonymization or compliance guarantee.
Export means an explicit local artifact, not an email send or external AI request.

The acceptance audit must verify these controls rather than substituting these
statements for implementation.

## Current evidence

- PR #2 merged: scanning fixes, dependency updates, basic CI and audits.
- PR #3 merged: 21 annotated examples, heuristic regression baseline, explicit
  detector selection, and opt-in real OPF smoke/evaluation commands.
- W1 implemented: configured operator key, minimized scan responses with explicit
  inspection opt-in, sanitized errors, host/origin controls, body and inference
  limits, browser headers, and documented service boundary. Local evidence: 64
  Python and 9 frontend tests, dependency audits, real OPF API checks over all 25
  fixture emails, and a live browser check with no console errors. Merged as PR #4
  after all three CI jobs passed; main updated with rebase.
- W2 implemented: three versioned policies, consistent request-scoped placeholders,
  manual ranges, supplementary credential rules, fully removed email routing
  fields, and expiring one-use export receipts. The review store retains only keyed
  fingerprints and metadata. Local gate: 94 Python and 9 frontend tests plus both
  dependency audits. Remote CI and merge remain the next gate for this package.
- R1–R11 as a whole are not yet proven; W3–W5 remain.
