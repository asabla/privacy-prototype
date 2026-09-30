import assert from "node:assert/strict";
import { setTimeout } from "node:timers/promises";
import test from "node:test";
import { JSDOM } from "jsdom";
import { mountWorkbench } from "../frontend/workbench.js";

const base = process.env.SENTINEL_TEST_URL;
const accessKey = process.env.SENTINEL_TEST_KEY;
assert.ok(base && accessKey, "Run through make test-workbench-api");

async function until(condition) {
  const deadline = Date.now() + 5000;
  while (!condition()) {
    if (Date.now() >= deadline) throw new Error("Workbench state did not reach the expected result");
    await setTimeout(10);
  }
}

for (const useCase of ["support_ticket", "ai_prompt", "email"]) {
  test(`real API: ${useCase} review, manual masks, copy, download, and clear`, async (t) => {
    const htmlResponse = await fetch(`${base}/workbench`);
    assert.equal(htmlResponse.status, 200);
    assert.equal(htmlResponse.headers.get("cache-control"), "no-store");
    const dom = new JSDOM(await htmlResponse.text(), { url: `${base}/workbench` });
    const { window } = dom;
    // Native Node fetch and its abort signal must share a realm, as they do in a browser.
    window.AbortController = globalThis.AbortController;
    const $ = (id) => window.document.getElementById(id);
    const calls = [], copied = [], downloads = [], blobs = [];
    window.URL.createObjectURL = (blob) => { blobs.push(blob); return "blob:reviewed"; };
    window.URL.revokeObjectURL = () => {};
    window.HTMLAnchorElement.prototype.click = function () { downloads.push(this.download); };
    Object.defineProperty(window.navigator, "clipboard", { value: { writeText: async (text) => copied.push(text) } });
    mountWorkbench({ document: window.document, window, fetch: async (path, options) => {
      const response = await fetch(new URL(path, base), options);
      calls.push({ path, body: options.body ? JSON.parse(options.body) : null, status: response.status });
      return response;
    } });
    t.after(() => window.close());
    $("operatorKey").value = accessKey;
    $("operatorKey").dispatchEvent(new window.Event("input", { bubbles: true }));
    $("connect").click();
    try {
      await until(() => $("connectionState").textContent === "Connected");
    } catch {
      throw new Error(`${$("connectionMessage").textContent}; HTTP statuses: ${calls.map((call) => `${call.path} ${call.status}`).join(", ")}`);
    }
    window.document.querySelector(`input[value="${useCase}"]`).click();
    $("loadSample").click();
    $("analyze").click();
    try {
      await until(() => !$("candidateFields").hidden);
    } catch {
      throw new Error(`${$("status").textContent}; HTTP statuses: ${calls.map((call) => `${call.path} ${call.status}`).join(", ")}`);
    }
    assert.doesNotMatch($("candidateFields").textContent, /password=demo|token=demo|alice@example.com|asa@example.com/);
    const field = useCase === "email" ? "body" : "text";
    const needle = useCase === "ai_prompt" ? "recurring sign-in error" : "Åsa Lindström";
    $("maskField").value = field;
    $("maskText").value = needle;
    $("addMask").click();
    assert.equal($("candidateFields").hidden, true);
    $("analyze").click();
    await until(() => !$("candidateFields").hidden);
    assert.doesNotMatch($("candidateFields").textContent, new RegExp(needle));
    const finalCandidateText = [...$("candidateFields").querySelectorAll("pre")].map((pre) => pre.textContent);
    $("reviewConfirmed").checked = true;
    $("reviewConfirmed").dispatchEvent(new window.Event("change"));
    $("approveExport").click();
    await until(() => !$("download").disabled);
    $("copy").click(); $("download").click();
    await until(() => copied.length === 1);
    assert.ok(finalCandidateText.every((text) => copied[0].includes(text)));
    assert.doesNotMatch(copied[0], /password=demo|token=demo|alice@example.com|asa@example.com|Åsa Lindström/);
    if (useCase === "email") assert.doesNotMatch(copied[0], /alice@northwind.io|support@example.com/);
    const saved = await new Promise((resolve) => { const reader = new window.FileReader(); reader.onload = () => resolve(reader.result); reader.readAsText(blobs[0]); });
    assert.equal(saved, copied[0]);
    assert.deepEqual(downloads, [`sentinel-${useCase}-reviewed.txt`]);
    assert.ok(calls.every((call) => call.status === 200));
    const originalReceipt = calls.find((call) => call.path === "/api/review/export").body;
    const replay = await fetch(`${base}/api/review/export`, { method: "POST", headers: {
      Authorization: `Bearer ${accessKey}`, "Content-Type": "application/json",
    }, body: JSON.stringify(originalReceipt) });
    assert.equal(replay.status, 410);
    $("clearAll").click();
    assert.equal($("operatorKey").value, "");
    assert.equal($("candidateFields").textContent, "");
    assert.ok([...$("sourceFields").querySelectorAll("textarea")].every((input) => input.value === ""));
    assert.equal(window.localStorage.length, 0);
    assert.equal(window.sessionStorage.length, 0);
  });
}
