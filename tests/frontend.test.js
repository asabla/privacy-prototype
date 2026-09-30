import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { setImmediate } from "node:timers/promises";
import test from "node:test";
import { JSDOM } from "jsdom";
import { highlightText, renderRedacted } from "../frontend/rendering.js";

const body = "😀 alice@example.com 👩🏽‍💻";
const redactedBody = "😀 [PRIVATE_EMAIL] 👩🏽‍💻";
const emailSpan = { label: "private_email", start: 2, end: 19, text: "alice@example.com", placeholder: "[PRIVATE_EMAIL]" };
const results = ["first", "second"].map((id) => ({
  email: { id, direction: "outbound", sender: "employee@northwind.io", recipients: ["recipient@example.com"], subject: `Message ${id}`, body, timestamp: "2026-01-01T12:00:00Z" },
  classification: { fully_internal: false, sender_internal: true, any_recipient_internal: false, all_recipients_internal: false, crosses_boundary: true, external_domains: ["example.com"] },
  employees_referenced: [],
  scan: { is_sensitive: true, span_count: 1, by_label: { private_email: 1 }, subject: { detected_spans: [] }, body: { detected_spans: [emailSpan], redacted_text: redactedBody } },
}));

let instance = 0;
async function dashboard(t) {
  const html = await readFile(new URL("../frontend/index.html", import.meta.url), "utf8");
  const dom = new JSDOM(html, { url: "http://localhost/" });
  const document = dom.window.document;
  let now = 0;
  let nextId = 0;
  const timers = new Map();
  const schedule = (callback, delay = 0) => {
    const id = ++nextId;
    timers.set(id, { at: now + delay, callback });
    return id;
  };
  const globals = {
    document, Element: dom.window.Element, location: dom.window.location,
    fetch: async (url) => ({ json: async () => ({
      "/api/engine": { engine: "heuristic", detail: "Test detector" },
      "/api/config": { internal_domains: ["northwind.io"] },
      "/api/scan-all": { results },
    })[url] }),
    performance: { now: () => now },
    setTimeout: schedule,
    clearTimeout: (id) => timers.delete(id),
    requestAnimationFrame: (callback) => schedule(() => callback(now), 16),
    cancelAnimationFrame: (id) => timers.delete(id),
  };
  const descriptors = new Map(Object.keys(globals).map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  for (const [key, value] of Object.entries(globals)) {
    Object.defineProperty(globalThis, key, { value, configurable: true, writable: true });
  }
  t.after(() => {
    dom.window.close();
    for (const [key, descriptor] of descriptors) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else delete globalThis[key];
    }
  });
  await import(`../frontend/app.js?test=${++instance}`);
  await setImmediate();
  assert.equal(document.querySelector("#engineLabel").textContent, "Heuristic demo engine");
  return {
    document,
    click: (selector) => document.querySelector(selector).click(),
    key: (element, key, shiftKey = false) => element.dispatchEvent(new dom.window.KeyboardEvent("keydown", { key, shiftKey, bubbles: true, cancelable: true })),
    advance(ms) {
      const end = now + ms;
      while (true) {
        const next = [...timers.entries()].sort((a, b) => a[1].at - b[1].at)[0];
        if (!next || next[1].at > end) break;
        now = next[1].at;
        timers.delete(next[0]);
        next[1].callback();
      }
      now = end;
    },
  };
}

test("Unicode highlights cover exactly the API span", () => {
  const dom = new JSDOM(`<div>${highlightText(body, [emailSpan])}</div>`);
  const mark = dom.window.document.querySelector(".span-hl");
  assert.equal(mark.firstChild.textContent, "alice@example.com");
  mark.querySelector(".hl-tag").remove();
  assert.equal(dom.window.document.querySelector("div").textContent, body);
  dom.window.close();
});

for (const placeholder of ["[PRIVATE_EMAIL]", "<PRIVATE_EMAIL>"]) {
  test(`redacted output preserves Unicode and escapes HTML with ${placeholder}`, () => {
    const text = `😀 ${placeholder} 👩🏽‍💻 <img src=x onerror=alert(1)>`;
    const dom = new JSDOM(`<div>${renderRedacted(text)}</div>`);
    assert.equal(dom.window.document.querySelector("div").textContent, text);
    assert.equal(dom.window.document.querySelector("img"), null);
    assert.equal(dom.window.document.querySelector(".redacted-tok").textContent, placeholder);
    dom.window.close();
  });
}

test("load all cancels pending autoplay", async (t) => {
  const ui = await dashboard(t);
  ui.click("#loadAllBtn");
  ui.advance(1000);
  assert.equal(ui.document.querySelectorAll(".email-row").length, 2);
  assert.match(ui.document.querySelector("#streamSub").textContent, /Simulation complete/);
});

for (const [label, delay, selector] of [["completed run", 600, "#simPlay"], ["in-flight animation", 100, "#simRestart"]]) {
  test(`replay clears all counters after ${label}`, async (t) => {
    const ui = await dashboard(t);
    ui.click("#loadAllBtn");
    ui.advance(delay);
    ui.click(selector);
    ui.click("#simPlay"); // Pause before the next simulated message arrives.
    assert.equal(ui.document.querySelectorAll(".email-row").length, 0);
    const values = () => [...ui.document.querySelectorAll(".kpi .value")].map((el) => el.textContent);
    assert.deepEqual(values(), ["0", "0", "0", "0", "0", "0"]);
    ui.advance(1000); // Previous animation callbacks must not restore old totals.
    assert.deepEqual(values(), ["0", "0", "0", "0", "0", "0"]);
  });
}

test("keyboard inspection traps focus, shows canonical redaction, and restores focus", async (t) => {
  const ui = await dashboard(t);
  const { document } = ui;
  ui.click("#loadAllBtn");
  const row = document.querySelector(".email-row");
  assert.equal(row.getAttribute("role"), "button");
  assert.equal(row.tabIndex, 0);
  row.focus();
  ui.key(row, "Enter");
  const drawer = document.querySelector("#drawer");
  const close = document.querySelector("#drawerClose");
  const redacted = document.querySelector('[data-mode="redacted"]');
  assert.equal(drawer.getAttribute("aria-hidden"), "false");
  assert.equal(document.activeElement, close);
  assert.equal(document.querySelector("main").inert, true);
  ui.key(close, "Tab", true);
  assert.equal(document.activeElement, redacted);
  ui.key(redacted, "Tab");
  assert.equal(document.activeElement, close);
  redacted.click();
  assert.equal(document.querySelector("#bodyBox").textContent, redactedBody);
  assert.equal(redacted.getAttribute("aria-pressed"), "true");
  ui.key(redacted, "Escape");
  assert.equal(drawer.getAttribute("aria-hidden"), "true");
  assert.equal(drawer.inert, true);
  assert.equal(document.querySelector("main").inert, false);
  assert.equal(document.activeElement, row);
  ui.key(row, " ");
  assert.equal(drawer.getAttribute("aria-hidden"), "false");
  assert.match(document.querySelector("#streamSub").textContent, /Simulation complete/);
});
