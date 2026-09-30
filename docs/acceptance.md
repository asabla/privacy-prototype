# Reference acceptance record

Validated on 2026-09-30 using synthetic data. The intended result is a working local
reference for support-ticket sharing, AI-prompt preparation, and email review.
The scope and retained risks are defined in the [threat model](threat-model.md).

## Requirement evidence

| Requirement | Evidence |
| --- | --- |
| R1 — Complete workflows | All three workflows exercised in the Browser plugin through analysis, manual masks, review and actual saved downloads. Download bytes were inspected; clipboard, reset, local storage and network requests were checked. Three DOM-to-real-HTTP integration tests compare output bytes and reject replay. |
| R2 — Authenticated input | `tests/test_security.py` verifies absent, invalid and duplicate credentials before body reads; `tests/test_review.py` protects every review route. Keys are generated for tests and absent from committed configuration. Browser storage remains empty. |
| R3 — Minimized disclosure | Scan defaults omit source/matched values. Sentinel tests cover validation and model errors, receipt storage and event metadata. Container logs are checked for synthetic inputs and its generated key. Explicit diagnostic inspection remains documented. |
| R4 — Exact reviewed export | Tests reject changed text, engine, use case, routing and policy; expiry, replay and process restart invalidate receipts. Concurrent export succeeds exactly once. UI tests reject an altered export response and invalidate stale source/reviews. |
| R5 — Measured misses and correction | The unchanged 21-case model-only evaluation below preserves known misses. Ten additional credential-policy cases cover quoted keys, escaped/unclosed values and negatives without model help. Three API export tests cover JSON credentials; actual Browser output was inspected. Manual Unicode masks work in every workflow. |
| R6 — Bounded, controlled failures | Streamed/declared body limits, safe validation, inference errors, recovery and occupied-slot `429` are tested. Actual container execution accepted a burst of 32 requests and remained ready. All were `200` on the recorded local run; the deterministic held-slot test separately proves busy rejection. |
| R7 — Transient processing | Source/candidate never enter receipt storage or events; no raw-text database. Browser checks show no cookies/local/session storage and only local page/API requests. Idle, page departure, explicit clear and late-response tests pass. Model/cache provisioning and OS memory limitations remain explicit. |
| R8 — Local service protections | Exact host/origin checks, HTTPS requirement for configured remote hosts, no wildcard CORS, security headers and text-only rendering have regression coverage. Native and container Browser walkthroughs work without current console errors. |
| R9 — Reproducible operation | Locked native `make serve` passed all three HTTP/DOM flows. The real Compose service passed non-root/read-only/limits/loopback checks, blocked an external processor connection, completed review/export, and rejected old receipts after restart. Readiness requires nonempty successful inference and clears on failure. Real OPF also preloaded and ran all workflows with Python network calls denied. |
| R10 — Explainable reference | README, [showcase](showcase.md), [service boundary](service-boundary.md), [review contract](review-contract.md), [runtime guide](runtime.md), current synthetic screenshots and [threat model](threat-model.md) cover audience, setup, trust, retention, limits and extension points. |
| R11 — Reviewable delivery | Scoped pull requests, conventional commits, local gates, package audits and per-PR CI. PRs #2–#10 merged after their checks passed. Subsequent delivery requires all five current CI jobs to pass on the exact head before merge, followed by a clean updated main checkout. |

## Reproduction gates

```sh
make check
make eval
make test-container
# With the documented real-model environment and assets already provisioned:
make test-opf-offline OPF_TEST_ENV=/absolute/path/to/opf-venv
make eval-opf OPF_TEST_ENV=/absolute/path/to/opf-venv
```

The initial reference code checks passed 114 Python tests, 18 frontend tests, and three
DOM-to-HTTP workflows. Python and npm audits reported no known vulnerabilities.
GitHub's eight previous dependency alerts are now marked fixed; the obsolete idna
3.15 update PR was closed because the merged lock already resolves idna 3.20.
The audits cover registry packages, not a guarantee over OS images, arbitrary
upstream Git code, model weights or future advisories.

The container runtime gate runs on Linux in CI and was also verified locally on
macOS with Docker's arm64 images. It creates an isolated Compose project and removes
its containers and networks afterward. Native real-model checks used CPU and the
checkpoint revision recorded in the runtime guide. Subsequent OPF container evidence
is recorded below; GPU operation remains outside the validated path.

GitHub Actions now has five jobs: regression/audits, UI on Node 22.22.2, UI on Node 26,
heuristic container runtime and CPU OPF image checks. See the [current workflow runs](https://github.com/asabla/privacy-prototype/actions/workflows/checks.yml)
and [merged change history](https://github.com/asabla/privacy-prototype/pulls?q=is%3Apr+is%3Amerged).
Check the exact head being merged; a prior green revision is not sufficient.

## Current detector measurements

These measurements are from 21 small authored examples, not a representative
accuracy benchmark or a basis for automatic sharing. Dataset SHA-256:
`33cda621064061745841f2658cac0f450db5898d168ec5cd7ce428f962e04c7e`.
The annotation policy and scoring semantics are explained in the README.

| Engine | Exact true positives | False positives | False negatives | Uncovered sensitive characters | Extra masked characters |
| --- | ---: | ---: | ---: | ---: | ---: |
| Heuristic | 17 | 6 | 4 | 36 / 343 | 64 |
| Real OPF | 18 | 1 | 3 | 26 / 343 | 4 |

OPF's remaining uncovered characters are the two annotated synthetic password values;
the review policy covers those separately. Its extra masking is an address boundary
issue. Heuristic misses also include Unicode names and a German address. Neither
engine justifies removing the review step. The ten credential-policy cases and
manual masks are deliberately excluded from these model-only scores.

The real-model smoke check passed nonempty preload, readiness, Unicode offsets,
empty input, all 25 synthetic inbox emails, and three policy-bound exports with
replay rejection. Its offline variant denied Python outbound socket/DNS calls while
running these checks. A deployment still needs its own host and egress controls.

## Follow-up evaluation and real-model container

The [expanded evaluation](expanded-evaluation.md) adds 28 authored cases without
changing the original baseline. Its real-model report retains 271 uncovered
sensitive characters out of 555, so automatic sharing remains unsupported. Policy
`2026-09-30.3` separately fixes multiline quoted and YAML-block credentials; 17
policy cases and all three API workflows test those safeguards without changing
model-only scores. PR #9 merged after all four existing CI jobs passed.

The subsequent local check passed 140 Python tests, 21 frontend tests and three
DOM-to-HTTP workflows, with zero known vulnerabilities in either dependency audit.
Both container targets built and passed their complete runtime checks. Real OPF
ran in Linux/arm64 with the pinned checkpoint and read-only assets: readiness,
three exports, replay rejection, blocked external connection, and restart receipt
invalidation passed. Its 32-request burst produced one successful response and 31
busy responses, followed by successful recovery. The heuristic accepted all 32.
These measured results are not throughput guarantees.

The Browser plugin exercised a [realistic synthetic support ticket](support-ticket-walkthrough.md)
against the OPF container. Model detections, multiline credential policy, a manual
address mask and explicit confirmation produced the exact bytes downloaded by the
browser. Browser storage was empty, all recorded page/API requests stayed on the
local service, and there were no console errors. Clear removed the source and
connection; the temporary container project was stopped afterward.
The walkthrough also reproduced and fixed a connection race: editing source text
while authentication was pending left the UI locked after a successful response.
Three UI regressions now cover that edit and late responses after clear/key changes;
the fixed behavior was exercised against the container with a delayed real request.

Public configuration/tokenizer provisioning and all five asset checksums passed.
The already-downloaded checkpoint was reused after checksum verification. Missing
assets prevented offline image startup; unit checks reject corrupt downloads and
existing altered assets. Linux CI builds the CPU image and tests missing-asset
failure without downloading weights. Full inference is the separate opt-in
`make test-container-opf` gate, not an inference claim about regular CI.

## Copied support logs and forwarded credentials

Policy `2026-09-30.4` adds authentication and cookie header masking, wrapped header
values, and credential blocks inside forwarded text. All 19 positive examples in
the new 24-case support-log corpus failed the preceding policy. They now require
complete annotated coverage without model assistance; the five negative examples
must remain unchanged. Combined with the preceding corpus, 41 policy cases cover
the deterministic safeguard. Model-only baseline measurements are unchanged.

The local gate passed 173 Python tests, 21 UI tests and three DOM-to-HTTP workflows;
both dependency audits reported zero known vulnerabilities. Real OPF passed all
19 additional policy exports with Python outbound network calls denied, alongside
the existing Unicode, empty-input, 25-email and three-workflow checks. The real
OPF container gate also passed exact export, replay rejection, restart receipt
invalidation, restricted execution and blocked external connectivity.

The [support-log Browser walkthrough](support-log-review.md) used the real OPF
container with an invented request header, cookie and forwarded credential block.
It verified the actual download against the exact reviewed candidate, preserved
the public troubleshooting context, and checked that export required confirmation.
Browser storage stayed empty, requests remained local and there were no console
errors. Clear removed the input and connection; the temporary project was stopped.
