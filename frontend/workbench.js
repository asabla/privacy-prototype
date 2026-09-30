const FIELD_LABELS = { text: "Text", sender: "Sender", recipients: "Recipients", subject: "Subject", body: "Body" };
const SAMPLES = {
  support_ticket: { text: "Ticket 1042 — login problem\n\nCustomer: Åsa Lindström\nContact: asa@example.com\n\nThe account is locked after a password reset. The customer pasted password=demo into the conversation. Please investigate the reset flow.\n\nReview tip: check the customer's name even if the detector misses it." },
  ai_prompt: { text: "Summarize the following synthetic customer conversation and suggest next steps.\n\nAlice Smith (alice@example.com) reported a recurring sign-in error. Send the follow-up to alice@example.com. The pasted diagnostic notes include token=demo.\n\nKeep the problem description useful without exposing customer details." },
  email: { sender: "Alice Smith <alice@northwind.io>", recipients: "Support <support@example.com>", subject: "Support request for alice@example.com", body: "Hello,\n\nPlease investigate the account for alice@example.com. The customer Åsa Lindström is unable to sign in. A note included password=demo.\n\nCan you explain the reset steps without sharing these details?" },
};
const ERROR_MESSAGES = {
  authentication_required: "The access key was not accepted. Reconnect with the operator key.",
  input_disabled: "This server is in fixture-only mode. Configure SENTINEL_API_KEY and restart it to enable submitted text.",
  processing_busy: "Another scan is running. Wait for it to finish, then analyze again.",
  processing_failed: "Processing failed. No reviewed export was released. Try again or check the service.",
  invalid_request: "Check the input fields and their length, then try again.",
  body_too_large: "This content exceeds the request limit. Shorten it before analyzing.",
  candidate_too_large: "The candidate exceeds the export limit. Shorten the source content.",
  too_many_findings: "This content has too many findings for one review. Split it into smaller parts.",
  invalid_email_routing: "Use one valid sender and up to 20 comma-separated recipients, without header newlines.",
  candidate_changed: "The candidate changed. Analyze and review it again before exporting.",
  review_unavailable: "This review expired or was already used. Analyze and review the content again.",
  review_capacity_reached: "The service has reached its pending-review limit. Clear an unused review or try later.",
};

export function reviewedText(candidate) {
  if (candidate.use_case !== "email") return candidate.fields.text;
  return ["sender", "recipients", "subject", "body"].map((field) => `${FIELD_LABELS[field]}: ${candidate.fields[field]}`).join("\n\n");
}

export function matchingMasks(field, text, needle) {
  if (!needle) return [];
  const masks = [];
  for (let index = text.indexOf(needle); index !== -1; index = text.indexOf(needle, index + 1)) {
    const start = Array.from(text.slice(0, index)).length;
    masks.push({ field, start, end: start + Array.from(needle).length });
  }
  return masks;
}

const canonical = (value) => JSON.stringify(value, (_, item) => item && typeof item === "object" && !Array.isArray(item)
  ? Object.fromEntries(Object.keys(item).sort().map((key) => [key, item[key]])) : item);

export function mountWorkbench({ document, window, fetch }) {
  const $ = (id) => document.getElementById(id);
  let useCase = "support_ticket";
  let connected = false;
  let busy = false;
  let revision = 0;
  let connectionRevision = 0;
  let result = null;
  let exported = null;
  let masks = [];
  let controller;
  let expiryTimer;
  let idleTimer;
  let previousKey = "";
  const objectUrls = new Set();
  const sourceFields = () => Object.fromEntries([...$("sourceFields").querySelectorAll("textarea")].map((el) => [el.dataset.field, el.value]));
  const key = () => $("operatorKey").value;

  function element(tag, text, className) {
    const el = document.createElement(tag);
    if (text !== undefined) el.textContent = text;
    if (className) el.className = className;
    return el;
  }
  function status(message, error = false) {
    $("status").textContent = message;
    $("status").dataset.error = String(error);
  }
  function syncControls() {
    const fields = sourceFields();
    const count = Object.values(fields).reduce((n, value) => n + Array.from(value).length, 0);
    $("characterCount").textContent = `${count.toLocaleString("en-US")} / 16,000 characters`;
    $("analyze").disabled = !connected || busy || count === 0 || count > 16000;
    $("analyze").textContent = busy ? "Processing…" : "Analyze content";
    $("addMask").disabled = busy || count === 0;
    $("reviewConfirmed").disabled = !result || busy || Boolean(exported);
    $("approveExport").disabled = !result || busy || !$("reviewConfirmed").checked || Boolean(exported);
    $("download").disabled = !exported || busy;
    $("copy").disabled = !exported || busy;
    for (const id of ["stepInput", "stepReview", "stepExport"]) $(id).removeAttribute("aria-current");
    $(exported ? "stepExport" : result ? "stepReview" : "stepInput").setAttribute("aria-current", "step");
  }
  async function api(path, body, { accessKey = key(), signal, keepalive = false } = {}) {
    const response = await fetch(path, { method: body === undefined ? "GET" : "POST",
      headers: { Authorization: `Bearer ${accessKey}`, ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
      body: body === undefined ? undefined : JSON.stringify(body), cache: "no-store", credentials: "omit", signal, keepalive });
    const data = await response.json();
    if (!response.ok) {
      const error = new Error(ERROR_MESSAGES[data?.error?.code] || "The service could not complete this request. Try again.");
      error.code = data?.error?.code;
      throw error;
    }
    return data;
  }
  function discard(receipt, accessKey = key()) {
    if (receipt && accessKey) void api("/api/review/discard", { receipt }, { accessKey, keepalive: true }).catch(() => {});
  }
  function revokeDownloads() {
    for (const url of objectUrls) window.URL.revokeObjectURL(url);
    objectUrls.clear();
  }
  function invalidate({ clearMasks = false, accessKey = key() } = {}) {
    revision += 1;
    controller?.abort();
    controller = null;
    window.clearTimeout(expiryTimer);
    discard(result?.review.receipt, accessKey);
    result = null;
    exported = null;
    busy = false;
    revokeDownloads();
    if (clearMasks) masks = [];
    $("reviewConfirmed").checked = false;
    $("candidateFields").replaceChildren();
    $("candidateFields").hidden = true;
    $("candidateEmpty").hidden = false;
    $("candidateMeta").textContent = "";
    $("routingNotice").textContent = "";
    $("routingNotice").hidden = true;
    $("findings").replaceChildren();
    $("findingCount").textContent = "No current analysis";
    $("receiptStatus").textContent = "Analyze content before confirming a review.";
    renderMasks();
    syncControls();
  }
  function renderFields(values = {}) {
    $("sourceFields").replaceChildren();
    $("maskField").replaceChildren();
    const fields = useCase === "email" ? ["sender", "recipients", "subject", "body"] : ["text"];
    for (const field of fields) {
      const wrap = element("div", undefined, "source-field");
      const label = element("label", FIELD_LABELS[field]);
      label.htmlFor = `source-${field}`;
      const input = element("textarea");
      input.id = `source-${field}`;
      input.dataset.field = field;
      input.autocomplete = "off";
      input.spellcheck = false;
      input.setAttribute("autocapitalize", "off");
      input.value = values[field] || "";
      if (["sender", "recipients", "subject"].includes(field)) { input.className = "compact"; input.rows = 2; }
      input.addEventListener("input", () => {
        invalidate({ clearMasks: true });
        $("maskText").value = "";
        status("Source changed. Previous review and manual masks cleared; analyze again.");
      });
      wrap.append(label, input);
      $("sourceFields").append(wrap);
      const option = element("option", FIELD_LABELS[field]);
      option.value = field;
      $("maskField").append(option);
    }
    syncControls();
  }
  function renderMasks() {
    $("manualMasks").replaceChildren();
    masks.forEach((mask, index) => {
      const item = element("li", `${FIELD_LABELS[mask.field]} · ${mask.start}–${mask.end}`);
      const remove = element("button", "Remove");
      remove.setAttribute("aria-label", `Remove manual mask ${index + 1}`);
      remove.addEventListener("click", () => {
        masks.splice(index, 1);
        invalidate();
        status("Manual mask removed. Analyze again to update the candidate.");
      });
      item.append(remove);
      $("manualMasks").append(item);
    });
  }
  function renderCandidate() {
    const candidate = result.candidate;
    $("candidateEmpty").hidden = true;
    $("candidateFields").hidden = false;
    $("candidateFields").replaceChildren();
    for (const [field, value] of Object.entries(candidate.fields)) {
      const section = element("div", undefined, "candidate-field");
      const pre = element("pre");
      // Build DOM text nodes, never interpret source or candidate text as HTML.
      for (const piece of value.split(/(\[[A-Z_]+(?:_\d+|_REMOVED)\])/g)) {
        pre.append(/^\[[A-Z_]+(?:_\d+|_REMOVED)\]$/.test(piece) ? element("mark", piece) : document.createTextNode(piece));
      }
      section.append(element("h3", FIELD_LABELS[field]), pre);
      $("candidateFields").append(section);
    }
    $("candidateMeta").textContent = `Policy ${candidate.policy_version} · ${candidate.engine === "opf" ? "OpenAI Privacy Filter" : "Heuristic detector"} + credential rules · ${result.summary.span_count} masks`;
    $("findingCount").textContent = `${result.summary.span_count} masks · ${result.summary.manual_mask_count} added manually`;
    $("routingNotice").hidden = !candidate.routing;
    if (candidate.routing) {
      $("routingNotice").textContent = `${candidate.routing.recipient_count} recipient(s). ${candidate.routing.crosses_example_boundary ? "Crosses" : "Does not cross"} the example company's domain boundary. This is a review signal, not a policy verdict. Sender and recipient fields are removed from export.`;
    }
    $("findings").replaceChildren();
    for (const finding of result.findings) {
      const item = element("li");
      const button = element("button", `${FIELD_LABELS[finding.field]} · ${finding.label.replaceAll("_", " ")} · ${finding.start}–${finding.end} (${finding.sources.join(", ")})`);
      button.addEventListener("click", () => {
        const input = $(`source-${finding.field}`);
        const chars = Array.from(input.value);
        input.focus();
        input.setSelectionRange(chars.slice(0, finding.start).join("").length, chars.slice(0, finding.end).join("").length);
      });
      item.append(button);
      $("findings").append(item);
    }
    $("receiptStatus").textContent = "Review is available for 10 minutes. Changes require a new analysis.";
    const preparedRevision = revision;
    expiryTimer = window.setTimeout(() => {
      if (preparedRevision !== revision || exported) return;
      invalidate();
      status("Review expired. Your source remains here; analyze it again before exporting.");
    }, result.review.expires_in_seconds * 1000);
    syncControls();
  }
  async function analyze() {
    if ($("analyze").disabled) return;
    invalidate();
    const requestRevision = revision;
    const accessKey = key();
    controller = new window.AbortController();
    busy = true;
    syncControls();
    status("Analyzing on this service. Model initialization may be required on the first request.");
    try {
      const prepared = await api("/api/prepare", { use_case: useCase, fields: sourceFields(), manual_masks: masks }, { accessKey, signal: controller.signal });
      if (requestRevision !== revision) { discard(prepared.review?.receipt, accessKey); return; }
      result = prepared;
      renderCandidate();
      status("Candidate ready. Review every field and add masks for anything missed.");
    } catch (error) {
      if (requestRevision === revision && error.name !== "AbortError") status(ERROR_MESSAGES[error.code] || "Could not analyze this content. Check the service and try again.", true);
    } finally {
      if (requestRevision === revision) { busy = false; controller = null; syncControls(); }
    }
  }
  async function approve() {
    if ($("approveExport").disabled) return;
    const requestRevision = revision;
    const expected = canonical(result.candidate);
    busy = true;
    syncControls();
    try {
      const artifact = await api("/api/review/export", { receipt: result.review.receipt, candidate: result.candidate, confirmed: true });
      if (requestRevision !== revision) return;
      if (artifact.reviewed !== true || canonical(artifact.candidate) !== expected) throw new Error("Invalid export response");
      exported = artifact.candidate;
      window.clearTimeout(expiryTimer);
      $("receiptStatus").textContent = "Review confirmed. Download or copy this exact version; edits will clear it.";
      status("Reviewed version ready. Choose download or copy when you want it to leave this tab.");
    } catch (error) {
      if (requestRevision === revision) {
        invalidate();
        status(ERROR_MESSAGES[error.code] || "Export could not be verified. Analyze and review again.", true);
      }
    } finally {
      if (requestRevision === revision) { busy = false; syncControls(); }
    }
  }
  function clearSession() {
    connectionRevision += 1;
    invalidate({ clearMasks: true });
    window.clearTimeout(idleTimer);
    connected = false;
    $("operatorKey").value = "";
    previousKey = "";
    $("maskText").value = "";
    $("connectionState").textContent = "Locked";
    $("connectionPanel").open = true;
    $("engine").textContent = "Not connected";
    $("connectionMessage").textContent = "Session cleared. Connect again to analyze new content.";
    renderFields();
    status("Session cleared: input, candidate, manual masks, and access key removed from this tab. Existing downloads and clipboard copies remain.");
  }
  function resetIdleTimer() {
    window.clearTimeout(idleTimer);
    idleTimer = window.setTimeout(clearSession, 15 * 60 * 1000);
  }

  $("connect").addEventListener("click", async () => {
    if (!key()) { $("connectionMessage").textContent = "Enter the configured operator key."; return; }
    const requestRevision = connectionRevision;
    $("connect").disabled = true;
    try {
      const session = await api("/api/session");
      if (requestRevision !== connectionRevision) return;
      connected = true;
      $("connectionState").textContent = "Connected";
      $("connectionMessage").textContent = "Connected. The key is kept only in this tab. Clear the session when finished.";
      $("connectionPanel").open = false;
      $("engine").textContent = session.engine === "opf" ? "Privacy Filter" : "Heuristic demo";
      status("Connected. Load a sample or enter content, then analyze it.");
    } catch (error) {
      if (requestRevision === connectionRevision) $("connectionMessage").textContent = ERROR_MESSAGES[error.code] || "Could not connect to the service. Check that it is running.";
    } finally {
      $("connect").disabled = false;
      syncControls();
    }
  });
  $("operatorKey").addEventListener("input", () => {
    connectionRevision += 1;
    invalidate({ accessKey: previousKey });
    previousKey = key();
    connected = false;
    $("connectionState").textContent = "Locked";
    $("engine").textContent = "Not connected";
    syncControls();
  });
  $("operatorKey").addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); $("connect").click(); } });
  document.querySelectorAll('input[name="useCase"]').forEach((input) => input.addEventListener("change", () => {
    invalidate({ clearMasks: true });
    useCase = input.value;
    $("maskText").value = "";
    renderFields();
    status("Use case changed. Load its sample or enter new content.");
  }));
  $("loadSample").addEventListener("click", () => {
    invalidate({ clearMasks: true });
    $("maskText").value = "";
    renderFields(SAMPLES[useCase]);
    status("Synthetic sample loaded. Analyze it, then check for missed details such as names.");
  });
  $("addMask").addEventListener("click", () => {
    const field = $("maskField").value;
    const added = matchingMasks(field, sourceFields()[field], $("maskText").value)
      .filter((mask) => !masks.some((old) => canonical(mask) === canonical(old)));
    if (!added.length) { status("No new exact match found in that field. Check the text and selected field.", true); return; }
    if (masks.length + added.length > 128) { status("A review supports up to 128 manual ranges. Shorten or split the content.", true); return; }
    masks.push(...added);
    $("maskText").value = "";
    invalidate();
    status(`${added.length} manual mask(s) added. Analyze again to update the candidate.`);
  });
  $("analyze").addEventListener("click", analyze);
  $("reviewConfirmed").addEventListener("change", syncControls);
  $("approveExport").addEventListener("click", approve);
  $("download").addEventListener("click", () => {
    if (!exported) return;
    const url = window.URL.createObjectURL(new window.Blob([reviewedText(exported)], { type: "text/plain;charset=utf-8" }));
    objectUrls.add(url);
    const anchor = element("a");
    anchor.href = url;
    anchor.download = `sentinel-${exported.use_case}-reviewed.txt`;
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => { window.URL.revokeObjectURL(url); objectUrls.delete(url); }, 30_000);
    status("Download requested for the reviewed text. The saved file is outside this session's clear controls.");
  });
  $("copy").addEventListener("click", async () => {
    if (!exported) return;
    const requestRevision = revision;
    try {
      await window.navigator.clipboard.writeText(reviewedText(exported));
      if (requestRevision === revision) status("Reviewed text copied. Clear does not remove it from your clipboard.");
    } catch {
      if (requestRevision === revision) status("Clipboard access was unavailable. Download the reviewed text instead.", true);
    }
  });
  $("clearAll").addEventListener("click", () => { clearSession(); previousKey = ""; $("operatorKey").focus(); });
  window.addEventListener("pagehide", () => { clearSession(); previousKey = ""; });
  for (const event of ["input", "keydown", "pointerdown"]) document.addEventListener(event, resetIdleTimer);
  renderFields();
  resetIdleTimer();
}
