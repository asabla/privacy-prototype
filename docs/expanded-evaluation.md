# Expanded synthetic evaluation

Recorded on 2026-09-30. These 28 additional authored examples expose specific
failure modes; they are not a representative Swedish or support-ticket accuracy
benchmark. People, contact details and credential values are invented. The original
21-case dataset and its regression baseline are unchanged.

## Annotation and scoring

`evaluation/extended-cases.json` uses the same Unicode code-point span convention
as the original dataset. Private addresses include street, postcode and city as one
span, including internal whitespace. Credentials label the entire value, including
embedded line breaks and subsequent indentation, but exclude the key, block header
and enclosing quotes. A synthetic personal identity number uses `account_number`,
the available identifier category; a different predicted label is an exact-span
error even when all its characters are covered. Public release dates and fictional
product names are negative examples. Synthetic credentials remain positive examples
even if their invented nature may influence model output.

The optional groups overlap: Swedish, forwarded text, credentials, multiline input,
Unicode, boundaries and negatives. Group totals must not be summed. Reports contain
IDs and counts, never source messages or matched values. Every heuristic case has
its own regression gate for false positives, false negatives, uncovered characters
and extra masking. A baseline permits known misses; it is not a safety threshold.

## Measured detector output

| Engine | Exact matches | False positives | False negatives | Uncovered sensitive characters | Extra masked characters |
| --- | ---: | ---: | ---: | ---: | ---: |
| Heuristic | 13 | 8 | 15 | 306 / 555 | 71 |
| Real OPF | 17 | 7 | 11 | 271 / 555 | 20 |

The real OPF run used the pinned upstream package, Torch 2.14.0 on CPU and checkpoint
`7ffa9a043d54d1be65afb281eddf0ffbe629385b`. Its count-only result is committed as
`evaluation/opf-extended-reference.json`; the heuristic baseline is
`evaluation/heuristic-extended-baseline.json`. Both identify the exact dataset hash.

OPF covered all names and emails in these examples. It left 52 address characters,
40 private-URL characters and all 179 annotated credential characters exposed.
It covered the synthetic personal number under another label and masked two public
dates. The heuristic missed accented names and most Swedish contact details. These
results require whole-message review and manual masks before export.

## Review-policy fixes

The expanded fixtures exposed multiline credential gaps in policy `2026-09-30.2`.
Policy `2026-09-30.3` adds closed multiline quoted assignments and indented literal
or folded credential blocks. Seventeen separate policy cases verify full value
coverage without model help, preserve following public context and test negative
fields. They include escaped quotes, CRLF, blank lines, nested indentation and
block indicators. All three API workflows test multiline review and export.
These safeguards are deliberately excluded from the detector measurements above.

## Reproduce

```sh
make eval
make eval-extended
make check
# In the documented provisioned real-model environment:
make eval-opf EVAL_ARGS='--dataset evaluation/extended-cases.json --output /tmp/opf-extended.json'
```

Use the [runtime guide](runtime.md) to pin local assets and prohibit model downloads.
Review every changed annotation and per-case error count before replacing a
baseline. Keep representative-data collection and an agreed recipient/use-case
policy as prerequisites for a real-data pilot.
