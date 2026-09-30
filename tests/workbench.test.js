import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { setImmediate } from "node:timers/promises";
import test from "node:test";
import { JSDOM } from "jsdom";
import { matchingMasks, mountWorkbench, reviewedText } from "../frontend/workbench.js";

const html = await readFile(new URL("../frontend/workbench.html", import.meta.url), "utf8");
const response = (data, status = 200) => ({ ok: status < 400, status, json: async () => data });
function resultFor(body) {
  return { candidate: { use_case: body.use_case, policy_version: "2026-09-30.1", engine: "heuristic",
    fields: Object.fromEntries(Object.entries(body.fields).map(([key, value]) => [key,
      ["sender", "recipients"].includes(key) ? `[${key.toUpperCase()}_REMOVED]` : value.replaceAll("alice@example.com", "[PRIVATE_EMAIL_1]")])), routing: null },
    findings: [], summary: { span_count: 1, manual_mask_count: body.manual_masks.length },
    review: { receipt: "synthetic-review-receipt-for-tests", expires_in_seconds: 600 }, warnings: [] };
}

function workbench(t, fetchOverride) {
  const dom = new JSDOM(html, { url: "http://127.0.0.1/workbench" });
  const { window } = dom;
  const calls = [], clipboard = [], blobs = [], revoked = [], downloads = [];
  let clock = 0, nextTimer = 0;
  const timers = new Map();
  window.setTimeout = (fn, delay = 0) => { const id = ++nextTimer; timers.set(id, { fn, at: clock + delay }); return id; };
  window.clearTimeout = (id) => timers.delete(id);
  window.URL.createObjectURL = (blob) => { blobs.push(blob); return `blob:review-${blobs.length}`; };
  window.URL.revokeObjectURL = (url) => revoked.push(url);
  Object.defineProperty(window.navigator, "clipboard", { value: { writeText: async (value) => clipboard.push(value) } });
  window.HTMLAnchorElement.prototype.click = function () { downloads.push({ name: this.download, href: this.href }); };
  const fetch = async (url, options) => {
    const body = options.body ? JSON.parse(options.body) : undefined;
    calls.push({ url, options, body });
    const override = fetchOverride?.(url, options, body);
    if (override) return override;
    if (url === "/api/session") return response({ engine: "heuristic" });
    if (url === "/api/prepare") return response(resultFor(body));
    if (url === "/api/review/export") return response({ reviewed: true, candidate: body.candidate });
    return response({ discarded: true });
  };
  mountWorkbench({ document: window.document, window, fetch });
  t.after(() => window.close());
  const $ = (id) => window.document.getElementById(id);
  const input = (id, value) => { $(id).value = value; $(id).dispatchEvent(new window.Event("input", { bubbles: true })); };
  const click = async (id) => { $(id).click(); await setImmediate(); };
  return { window, $, calls, clipboard, blobs, revoked, downloads, input, click,
    async connect() { input("operatorKey", "synthetic-access-for-dom-test-only"); await click("connect"); },
    async analyze(text = "😀 alice@example.com <img src=x onerror=alert(1)>") { input("source-text", text); await click("analyze"); },
    async approve() { $("reviewConfirmed").checked = true; $("reviewConfirmed").dispatchEvent(new window.Event("change")); await click("approveExport"); },
    advance(ms) { clock += ms; for (const [id, timer] of [...timers]) if (timer.at <= clock) { timers.delete(id); timer.fn(); } },
  };
}

test("workbench requires connection and uses authenticated minimized requests", async (t) => {
  const ui = workbench(t);
  assert.equal(ui.$("analyze").disabled, true);
  await ui.connect();
  await ui.analyze();
  const call = ui.calls.find((c) => c.url === "/api/prepare");
  assert.equal(call.body.include_source, undefined);
  assert.equal(call.body.use_case, "support_ticket");
  assert.deepEqual(call.body.manual_masks, []);
  assert.match(call.options.headers.Authorization, /^Bearer /);
  assert.equal(call.options.credentials, "omit");
  assert.equal(ui.$("candidateFields").querySelector("img"), null);
  assert.match(ui.$("candidateFields").textContent, /<img src=x onerror=alert\(1\)>/);
  assert.doesNotMatch(ui.$("candidateFields").textContent, /alice@example.com/);
  assert.equal(ui.window.localStorage.length, 0);
  assert.equal(ui.window.sessionStorage.length, 0);
  assert.equal(ui.$("download").disabled, true);
});

test("confirmed export copies and downloads only the exact reviewed candidate", async (t) => {
  const ui = workbench(t);
  await ui.connect(); await ui.analyze();
  await ui.click("approveExport");
  assert.equal(ui.calls.filter((c) => c.url === "/api/review/export").length, 0);
  await ui.approve();
  await ui.click("copy"); await ui.click("download");
  const payload = ui.calls.find((c) => c.url === "/api/review/export").body;
  assert.equal(payload.confirmed, true);
  assert.equal(ui.clipboard[0], payload.candidate.fields.text);
  assert.doesNotMatch(ui.clipboard[0], /alice@example.com/);
  assert.equal(ui.downloads[0].name, "sentinel-support_ticket-reviewed.txt");
  const downloaded = await new Promise((resolve) => { const reader = new ui.window.FileReader(); reader.onload = () => resolve(reader.result); reader.readAsText(ui.blobs[0]); });
  assert.equal(downloaded, ui.clipboard[0]);
  await ui.click("clearAll");
  assert.deepEqual(ui.revoked, ["blob:review-1"]);
  assert.equal(ui.$("source-text").value, "");
  assert.equal(ui.$("operatorKey").value, "");
  assert.equal(ui.$("candidateFields").textContent, "");
  assert.equal(ui.$("download").disabled, true);
});

test("manual masks use Unicode code points and source edits invalidate them", async (t) => {
  const ui = workbench(t);
  await ui.connect(); await ui.analyze("😀 Åsa met Åsa");
  ui.input("maskText", "Åsa"); await ui.click("addMask");
  assert.equal(ui.$("candidateFields").hidden, true);
  assert.equal(ui.$("manualMasks").children.length, 2);
  assert.equal(ui.$("maskText").value, "");
  await ui.click("analyze");
  assert.deepEqual(ui.calls.filter((c) => c.url === "/api/prepare").at(-1).body.manual_masks,
    [{ field: "text", start: 2, end: 5 }, { field: "text", start: 10, end: 13 }]);
  ui.input("source-text", "new input");
  assert.equal(ui.$("manualMasks").children.length, 0);
  assert.equal(ui.$("reviewConfirmed").disabled, true);
  assert.equal(ui.$("candidateFields").textContent, "");
});

test("late analysis cannot repopulate a cleared session", async (t) => {
  let finish;
  const ui = workbench(t, (url, _, body) => url === "/api/prepare" ? new Promise((resolve) => { finish = () => resolve(response(resultFor(body))); }) : undefined);
  await ui.connect(); await ui.analyze();
  assert.equal(ui.$("analyze").textContent, "Processing…");
  await ui.click("clearAll");
  finish(); await setImmediate();
  assert.equal(ui.$("candidateFields").textContent, "");
  assert.equal(ui.$("source-text").value, "");
  assert.equal(ui.$("operatorKey").value, "");
  assert.equal(ui.$("download").disabled, true);
  assert.equal(ui.calls.at(-1).url, "/api/review/discard");
});

test("review expiry and idle timeout remove results and credentials", async (t) => {
  const ui = workbench(t);
  await ui.connect(); await ui.analyze();
  ui.advance(600_000);
  assert.equal(ui.$("candidateFields").textContent, "");
  assert.match(ui.$("status").textContent, /expired/);
  ui.advance(300_000);
  assert.equal(ui.$("source-text").value, "");
  assert.equal(ui.$("operatorKey").value, "");
  assert.equal(ui.$("analyze").disabled, true);
});

test("processing errors recover and never enable export", async (t) => {
  let fail = true;
  const ui = workbench(t, (url) => url === "/api/prepare" && fail ? response({ error: { code: "processing_busy" } }, 429) : undefined);
  await ui.connect(); await ui.analyze();
  assert.match(ui.$("status").textContent, /Another scan/);
  assert.equal(ui.$("download").disabled, true);
  assert.equal(ui.$("analyze").disabled, false);
  fail = false; await ui.click("analyze");
  assert.equal(ui.$("candidateFields").hidden, false);
});

test("a changed export response is rejected", async (t) => {
  const ui = workbench(t, (url, _, body) => url === "/api/review/export" ? response({ reviewed: true,
    candidate: { ...body.candidate, fields: { text: "unreviewed content" } } }) : undefined);
  await ui.connect(); await ui.analyze(); await ui.approve();
  assert.equal(ui.$("download").disabled, true);
  assert.equal(ui.$("copy").disabled, true);
  assert.match(ui.$("status").textContent, /could not be verified/);
});

test("use-case switches and page departure clear previous content", async (t) => {
  const ui = workbench(t);
  await ui.connect(); await ui.analyze();
  ui.window.document.querySelector('input[value="email"]').click();
  await ui.click("loadSample");
  assert.equal(ui.$("source-text"), null);
  assert.equal(ui.$("candidateFields").textContent, "");
  assert.match(ui.$("source-sender").value, /northwind/);
  ui.window.dispatchEvent(new ui.window.Event("pagehide"));
  assert.equal(ui.$("source-sender").value, "");
  assert.equal(ui.$("operatorKey").value, "");
});

test("overlapping manual matches and complete email text output", () => {
  assert.deepEqual(matchingMasks("text", "aaaa", "aaa"), [{ field: "text", start: 0, end: 3 }, { field: "text", start: 1, end: 4 }]);
  const text = reviewedText({ use_case: "email", fields: { sender: "[SENDER_REMOVED]", recipients: "[RECIPIENTS_REMOVED]", subject: "Hello", body: "Reviewed body" } });
  assert.equal(text, "Sender: [SENDER_REMOVED]\n\nRecipients: [RECIPIENTS_REMOVED]\n\nSubject: Hello\n\nBody: Reviewed body");
});
