# A guided privacy review

The audience is developers building privacy-aware applications, with a review flow
that privacy teams can inspect. The demonstration is intentionally single-operator
and uses synthetic examples. It demonstrates controlled input, minimized responses,
human review, and an exact reviewed export; it does not certify that output is anonymous.

## Start locally

```sh
make install
export SENTINEL_API_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
```

On macOS, copy the key without printing it, then start the service:

```sh
printf '%s' "$SENTINEL_API_KEY" | pbcopy
make run
```

On other systems, use your clipboard manager before running `make run`.
Open `http://127.0.0.1:8000/workbench`, paste into **Operator access key**, and
choose **Connect**. The browser
does not write it to cookies, local storage, or session storage. Your clipboard
is separate from the application session; copying reviewed text replaces its
current content. The key should never be placed in a URL or committed configuration.

The default engine is a heuristic unless OPF is installed. The badge identifies the
active engine. Follow the README's OPF setup to repeat the same workflows with the
real local model. In either mode, credential rules supplement detection and every
candidate still needs review.

## 1. Share a support ticket

Choose **Share a support ticket**, then **Load sample** and **Analyze content**.
The sample contains an email address, a credential-like assignment, and a Swedish
name. With the heuristic, the name is a deliberate demonstration of a miss.

Read the candidate. Enter `Åsa Lindström` in **Exact text to mask**, choose **Add
mask for every match**, and analyze again. The name, email, and credential should
now be replaced. **Inspect detected ranges** selects original text without
changing it; manual masks use Unicode code-point ranges.

Confirm that you reviewed every candidate field and choose **Confirm review**.
Then download or copy the reviewed text. The export contains the candidate, not
the original customer details. Changing source input disables export and clears
the old review and manual ranges so offsets cannot silently apply to changed text.

## 2. Prepare an AI prompt

Choose **Prepare an AI prompt**, load its sample, and analyze it. The repeated
email address receives the same placeholder within this request, preserving useful
references. The synthetic token assignment is masked. Review the entire prompt,
confirm, and copy or download it. No model provider is contacted by this workflow.

Placeholders reset on the next request; there is no persistent reversible identity
map. Context, writing style, unusual circumstances, and missed spans can still
identify someone. Add manual masks or remove unnecessary context before export.

## 3. Review an email

Choose **Review an email**, load its sample, and analyze it. Sender and recipient
fields are removed entirely. Subject and body use the same detection and credential
rules. The routing note compares addresses with the repository's example company
domains; it does not declare a policy violation or allow delivery.

Check the name in the body. With the heuristic, select **Body** in the mask field,
mask `Åsa Lindström`, and analyze again. Review all four output fields and confirm.
The downloaded text includes removed-routing placeholders plus the reviewed subject
and body. It cannot quietly append the original sender or recipient details.

## Finish and clear

**Clear this session** empties original fields, candidate, manual ranges, and key,
disables export, and discards an outstanding server receipt. Late responses cannot
restore cleared content. Leaving the page clears the session too. After 15 minutes
without input, key, or pointer activity, the tab clears automatically; unconfirmed
review receipts expire after 10 minutes.

Downloads and clipboard copies are user-controlled artifacts and remain after
clearing. Server memory is not securely erased, and a crashed browser or operating
system can retain data outside the application's control. Review metadata is
bounded and volatile; it is not a compliance audit archive.

## Evidence and extension points

`make check` runs backend, UI, real HTTP workflow checks, and dependency audits.
`make test-opf` exercises real model inference, all 25 inbox examples, and the three
review/export policies. Evaluation metrics and known detector misses are described
in the README. Automated integration checks verify downloaded/copied text against
the reviewed candidate rather than trusting a success message.

The main extension points are detector adapters, the versioned policy in
`backend/review.py`, the identity boundary in `backend/security.py`, and a separately
governed metadata event sink. Shared hosting needs real identities, tenant isolation,
and operational controls; adding a mailbox or external AI call is a new data-flow
decision with its own review, retention, and failure policy.
