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
  dependency audits, and real OPF execution/export for all three workflows. Merged
  as PR #5 after all CI jobs passed; main updated with rebase.
- W3 implemented: `/workbench` supports all three workflows, manual masks, explicit
  review, exact text download/copy, expiry, and clear/reset. Local evidence: 94
  Python tests, 18 frontend tests, and three DOM-to-HTTP workflow tests, with clean
  audits. Browser plugin walkthroughs saved and inspected actual downloads for
  support tickets, prompts, and email; clipboard, empty storage, local-only requests,
  and clear/reset were checked. Mobile geometry at 390px has no horizontal overflow.
  Merged as PR #6 after all three CI jobs passed; main updated with rebase.
- W4 implemented: explicit engine selection, nonempty-inference readiness with
  failure recovery, preloaded native serving, digest-pinned non-root containers,
  and an isolated processor behind a loopback proxy. Local gate: 101 Python tests,
  18 frontend tests, three HTTP workflows, clean package audits, actual restricted
  Docker execution/restart, and real OPF preload plus 25 inbox examples and three
  workflows with Python network calls denied. Native `make serve` also passed all
  three DOM-to-HTTP workflows. The container runtime gate is now included in CI;
  all four CI jobs passed and it merged as PR #7. Main was updated with rebase.
- W5 implemented: policy `2026-09-30.2` closes JSON/YAML quoted-key and escaped or
  unfinished quoted-value gaps; ten annotated policy cases and three export cases
  were added. Local gates pass 114 Python, 18 frontend and three HTTP workflow
  tests, both package audits, actual container runtime, and real offline OPF
  preload/corpus/workflows. Browser downloads verify the fix and screenshots show
  the current policy. The threat model and requirement-by-requirement evidence are
  in `docs/threat-model.md` and `docs/acceptance.md`.
- PR #8 completed the initial acceptance package after four green CI jobs. PR #9
  added 28 evaluation cases and multiline credential policy coverage. PR #10 added
  the real CPU OPF container, pinned read-only model assets, an offline startup gate,
  the support-ticket walkthrough and a connection-race fix. All five PR checks and
  the merged-main checks passed. R1–R11 remain mapped in the acceptance record.
- Policy `2026-09-30.4` covers copied HTTP authentication/cookie headers and forwarded
  credential blocks. Local evidence: 173 Python tests, 21 UI tests, three HTTP
  workflows, clean dependency audits, 19 real offline OPF policy exports, the real
  OPF container gate and an exact-download Browser walkthrough. Delivery requires
  all five CI jobs to pass on the revision being merged.
