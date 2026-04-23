// Sentinel — privacy detector PoC

const LABEL_META = {
  private_person:  { short: "Person",   hex: "#a78bfa" },
  private_email:   { short: "Email",    hex: "#22d3ee" },
  private_phone:   { short: "Phone",    hex: "#38bdf8" },
  private_address: { short: "Address",  hex: "#f472b6" },
  private_url:     { short: "URL",      hex: "#fb7185" },
  private_date:    { short: "Date",     hex: "#f59e0b" },
  account_number:  { short: "Account",  hex: "#fbbf24" },
  secret:          { short: "Secret",   hex: "#ef4444" },
};

const LABEL_ORDER = [
  "secret",
  "account_number",
  "private_address",
  "private_person",
  "private_email",
  "private_phone",
  "private_date",
  "private_url",
];

const state = {
  engine: null,
  engineDetail: null,
  internalDomains: [],
  // The full scanned corpus (fetched once), used as the source for simulation.
  allResults: [],
  // Currently shown results (grows during simulation).
  results: [],
  filter: "all",
  // Simulation state.
  sim: {
    mode: "idle",          // "idle" | "running" | "paused" | "done"
    queue: [],             // remaining results to reveal
    speed: 1,
    timer: null,
  },
  // Cached live aggregate (updated incrementally each time a result is added).
  aggregates: null,
};

const $ = (sel) => document.querySelector(sel);

async function loadAll() {
  const [engine, config, scan] = await Promise.all([
    fetch("/api/engine").then((r) => r.json()),
    fetch("/api/config").then((r) => r.json()),
    fetch("/api/scan-all").then((r) => r.json()),
  ]);
  state.engine = engine.engine;
  state.engineDetail = engine.detail;
  state.internalDomains = config.internal_domains;
  state.allResults = scan.results;

  renderEngineBadge();
  renderLegend();
  renderFooter();
  renderScaffold();
  resetDisplay();

  // If the user deep-linked to a specific email, skip simulation and load everything.
  const params = new URLSearchParams(location.search);
  if (params.get("email")) {
    loadAllInstant();
    openDrawer(params.get("email"));
    if (params.get("view") === "redacted") {
      setTimeout(() => {
        const btn = document.querySelector('#viewToggle button[data-mode="redacted"]');
        btn && btn.click();
      }, 50);
    }
  } else {
    // Autoplay the simulation shortly after page load so the user sees it breathe.
    setTimeout(() => simPlay(), 600);
  }
}

// ---------- Engine badge / legend / footer ----------

function renderEngineBadge() {
  const badge = $("#engineBadge");
  const label = $("#engineLabel");
  if (state.engine === "opf") {
    badge.classList.remove("heuristic");
    label.textContent = "OpenAI privacy-filter · live";
  } else {
    badge.classList.add("heuristic");
    label.textContent = "Heuristic demo engine";
  }
}

function renderFooter() {
  $("#engineDetail").textContent = state.engineDetail;
  $("#internalDomains").textContent = state.internalDomains.join("  ·  ");
}

function renderLegend() {
  const el = $("#legend");
  el.innerHTML = LABEL_ORDER.map((k) => {
    const m = LABEL_META[k];
    return `<span class="legend-item" style="color:${m.hex}">
      <span class="legend-swatch"></span>${m.short}
    </span>`;
  }).join("");
}

// ---------- Scaffolding (done once) ----------

/** Build the KPI / bars / split-chart DOM once so later updates can animate in place. */
function renderScaffold() {
  // KPIs
  const kpiDefs = [
    { key: "total",         label: "Total emails",         sub: "", cls: "" },
    { key: "sensitive",     label: "Sensitive",            sub: "", cls: "kpi-warn" },
    { key: "leaks_out",     label: "Outbound leaks",       sub: "sensitive → external recipient", cls: "kpi-danger" },
    { key: "sensitive_inbound", label: "Inbound PII",      sub: "external → internal with PII", cls: "kpi-accent" },
    { key: "crossing_boundary", label: "Boundary crossings", sub: "internal ↔ external", cls: "" },
    { key: "spans",         label: "PII spans",            sub: "across categories", cls: "kpi-ok" },
  ];
  $("#kpis").innerHTML = kpiDefs.map((c) => `
    <div class="kpi ${c.cls}" data-key="${c.key}">
      <div class="label">${c.label}</div>
      <div class="value" data-value="0">0</div>
      <div class="sub" data-sub>${c.sub}</div>
    </div>
  `).join("");

  // PII label bars
  $("#labelBars").innerHTML = LABEL_ORDER.map((k) => {
    const m = LABEL_META[k];
    return `
      <div class="bar-row" data-label="${k}" style="color:${m.hex}">
        <div class="bar-label"><span class="bar-dot"></span>${m.short}</div>
        <div class="bar-track"><div class="bar-fill" style="width:0%"></div></div>
        <div class="bar-count">0</div>
      </div>
    `;
  }).join("");

  // Split chart
  $("#splitChart").innerHTML = [
    { id: "sens-clean", title: "Sensitive vs clean", left: "sensitive", right: "clean", leftClass: "sens", rightClass: "safe" },
    { id: "leak-safe",  title: "Outbound leaks vs safe outbound", left: "leaks", right: "safe", leftClass: "leak", rightClass: "safe" },
    { id: "int-ext",    title: "Traffic by recipient", left: "internal-only", right: "external", leftClass: "internal-seg", rightClass: "external-seg" },
  ].map((r) => `
    <div class="split-row" data-id="${r.id}">
      <div class="split-row-header">
        <span>${r.title}</span>
        <span><span class="n" data-left>0</span> / <span data-total>0</span></span>
      </div>
      <div class="split-bar">
        <div class="split-seg ${r.leftClass}" data-seg="left" style="flex:0"></div>
        <div class="split-seg ${r.rightClass}" data-seg="right" style="flex:0"></div>
      </div>
      <div class="split-row-header" style="font-size:11px">
        <span>${r.left}</span>
        <span>${r.right}</span>
      </div>
    </div>
  `).join("");
}

// ---------- Aggregates ----------

function emptyAggregates() {
  return {
    total: 0, inbound: 0, outbound: 0, internal: 0,
    sensitive: 0, sensitive_inbound: 0, sensitive_outbound: 0, sensitive_internal: 0,
    crossing_boundary: 0, leaks_out: 0,
    by_label: {},
  };
}

function updateAggregate(agg, r) {
  const e = r.email;
  const c = r.classification;
  agg.total += 1;
  agg[e.direction] = (agg[e.direction] || 0) + 1;
  if (c.crosses_boundary) agg.crossing_boundary += 1;
  if (r.scan.is_sensitive) {
    agg.sensitive += 1;
    agg["sensitive_" + e.direction] = (agg["sensitive_" + e.direction] || 0) + 1;
    if (e.direction === "outbound" && !c.all_recipients_internal) agg.leaks_out += 1;
  }
  for (const [label, n] of Object.entries(r.scan.by_label)) {
    agg.by_label[label] = (agg.by_label[label] || 0) + n;
  }
}

// ---------- Incremental renderers ----------

function renderKpis(prev, next) {
  const spansOf = (a) => Object.values(a.by_label).reduce((s, n) => s + n, 0);
  const values = {
    total: next.total,
    sensitive: next.sensitive,
    leaks_out: next.leaks_out,
    sensitive_inbound: next.sensitive_inbound,
    crossing_boundary: next.crossing_boundary,
    spans: spansOf(next),
  };
  const prevValues = {
    total: prev.total,
    sensitive: prev.sensitive,
    leaks_out: prev.leaks_out,
    sensitive_inbound: prev.sensitive_inbound,
    crossing_boundary: prev.crossing_boundary,
    spans: spansOf(prev),
  };
  document.querySelectorAll(".kpi").forEach((el) => {
    const key = el.dataset.key;
    const to = values[key];
    const from = prevValues[key];
    const valEl = el.querySelector(".value");
    if (from !== to) {
      animateNumber(valEl, from, to, 500);
      el.classList.remove("kpi-bump");
      void el.offsetWidth;
      el.classList.add("kpi-bump");
    }
    const subEl = el.querySelector("[data-sub]");
    if (key === "total") {
      subEl.textContent = `${next.inbound} in · ${next.outbound} out · ${next.internal} internal`;
    } else if (key === "sensitive") {
      subEl.textContent = next.total ? `${Math.round((next.sensitive / next.total) * 100)}% of inbox` : "0% of inbox";
    } else if (key === "spans") {
      subEl.textContent = `across ${Object.keys(next.by_label).length} categor${Object.keys(next.by_label).length === 1 ? "y" : "ies"}`;
    }
  });
}

function renderLabelBars(agg) {
  const counts = agg.by_label;
  const max = Math.max(1, ...Object.values(counts), 1);
  document.querySelectorAll(".bar-row").forEach((row) => {
    const k = row.dataset.label;
    const n = counts[k] || 0;
    row.querySelector(".bar-fill").style.width = `${(n / max) * 100}%`;
    row.querySelector(".bar-count").textContent = n;
  });
}

function renderSplitChart(agg) {
  const data = {
    "sens-clean": { left: agg.sensitive, right: Math.max(0, agg.total - agg.sensitive) },
    "leak-safe":  { left: agg.leaks_out, right: Math.max(0, agg.outbound - agg.leaks_out) },
    "int-ext":    { left: Math.max(0, agg.total - agg.crossing_boundary), right: agg.crossing_boundary },
  };
  for (const [id, { left, right }] of Object.entries(data)) {
    const row = document.querySelector(`.split-row[data-id="${id}"]`);
    if (!row) continue;
    const total = Math.max(1, left + right);
    row.querySelector('[data-seg="left"]').style.flex  = String((left  / total) * 100 || 0.0001);
    row.querySelector('[data-seg="right"]').style.flex = String((right / total) * 100 || 0.0001);
    row.querySelector("[data-left]").textContent = left;
    row.querySelector("[data-total]").textContent = left + right;
  }
}

function renderStreamSub() {
  const total = state.allResults.length;
  const shown = state.results.length;
  const sub = $("#streamSub");
  if (state.sim.mode === "running") sub.textContent = `Receiving live · ${shown}/${total}`;
  else if (state.sim.mode === "paused") sub.textContent = `Paused · ${shown}/${total}`;
  else if (state.sim.mode === "done") sub.textContent = `Simulation complete · ${shown} messages processed`;
  else sub.textContent = `${shown}/${total} messages`;
}

function updateLiveIndicator() {
  const el = $("#liveIndicator");
  const running = state.sim.mode === "running";
  el.hidden = !(running || state.sim.mode === "paused");
  el.classList.toggle("paused", state.sim.mode === "paused");
  $("#liveCount").textContent = state.results.length;
  $("#liveTotal").textContent = state.allResults.length;
}

// ---------- Email list ----------

function filteredResults() {
  const f = state.filter;
  return state.results.filter((r) => {
    if (f === "all") return true;
    if (f === "sensitive") return r.scan.is_sensitive;
    if (f === "leaks") return r.email.direction === "outbound" && !r.classification.all_recipients_internal && r.scan.is_sensitive;
    if (f === "inbound") return r.email.direction === "inbound";
    if (f === "outbound") return r.email.direction === "outbound";
    if (f === "internal") return r.email.direction === "internal";
    return true;
  });
}

function renderEmailList() {
  const list = $("#emailList");
  const results = filteredResults();
  list.innerHTML = results.map((r) => emailRowHtml(r, false)).join("");
  attachRowHandlers(list);
  renderStreamSub();
}

function prependEmailRow(r) {
  // Respect filter: only insert if the row passes the filter.
  if (!passesFilter(r)) return;
  const list = $("#emailList");
  const tmp = document.createElement("div");
  tmp.innerHTML = emailRowHtml(r, true);
  const row = tmp.firstElementChild;
  list.insertBefore(row, list.firstChild);
  attachRowHandlers(row);
  // Trigger entrance animation after mount.
  requestAnimationFrame(() => {
    row.classList.add("entered");
  });
  // Remove scanline overlay once its animation finishes.
  const line = row.querySelector(".scanline");
  if (line) line.addEventListener("animationend", () => line.remove(), { once: true });
}

function passesFilter(r) {
  const f = state.filter;
  if (f === "all") return true;
  if (f === "sensitive") return r.scan.is_sensitive;
  if (f === "leaks") return r.email.direction === "outbound" && !r.classification.all_recipients_internal && r.scan.is_sensitive;
  if (f === "inbound") return r.email.direction === "inbound";
  if (f === "outbound") return r.email.direction === "outbound";
  if (f === "internal") return r.email.direction === "internal";
  return true;
}

function attachRowHandlers(root) {
  const rows = root instanceof Element && root.classList.contains("email-row")
    ? [root]
    : root.querySelectorAll(".email-row");
  rows.forEach((el) => {
    el.addEventListener("click", () => openDrawer(el.dataset.id));
  });
}

function emailRowHtml(r, live) {
  const e = r.email;
  const dir = e.direction;
  const dirIcon = dirGlyph(dir);
  const primary = dir === "inbound" ? e.sender : e.recipients[0];
  const primaryDomain = domainOf(primary);
  const secondary = dir === "inbound"
    ? `to ${e.recipients.map(short).join(", ")}`
    : `from ${short(e.sender)}`;
  const isLeak = dir === "outbound" && r.scan.is_sensitive && !r.classification.all_recipients_internal;
  const risk = isLeak ? { label: "Leak", cls: "leak" }
                      : r.scan.is_sensitive ? { label: "Sensitive", cls: "sensitive" }
                      : { label: "Clean", cls: "clean" };
  const dots = piiDots(r.scan.by_label);
  const liveCls = live ? " is-new" : "";
  const leakCls = isLeak ? " row-leak" : "";
  const scanline = live ? `<div class="scanline"></div>` : "";
  return `
    <div class="email-row${liveCls}${leakCls}" data-id="${e.id}">
      ${scanline}
      <div class="dir-icon ${dir}" title="${dir}">${dirIcon}</div>
      <div class="email-addr">
        <div class="addr-primary">${escape(nameFor(primary))}</div>
        <div class="addr-secondary mono">${escape(primaryDomain || primary)}</div>
      </div>
      <div class="email-subject">
        <div class="subject-line">${escape(e.subject)}</div>
        <div class="subject-preview">${escape(secondary)}</div>
      </div>
      <div class="pii-dots">${dots}</div>
      <div class="risk ${risk.cls}">${risk.label}</div>
    </div>
  `;
}

function dirGlyph(d) {
  if (d === "inbound") return "↓";
  if (d === "outbound") return "↑";
  return "⇄";
}

function piiDots(byLabel) {
  const labels = Object.keys(byLabel).sort((a, b) => LABEL_ORDER.indexOf(a) - LABEL_ORDER.indexOf(b));
  if (!labels.length) return `<span class="pii-none">—</span>`;
  return labels.map((k) => {
    const m = LABEL_META[k];
    const n = byLabel[k];
    return Array.from({ length: Math.min(n, 4) })
      .map(() => `<span class="pii-dot" title="${m.short} × ${n}" style="color:${m.hex}"></span>`)
      .join("") + (n > 4 ? `<span style="font-size:10px;color:${m.hex};margin-left:2px">×${n}</span>` : "");
  }).join(" ");
}

function nameFor(address) {
  if (!address) return "";
  const local = address.split("@")[0];
  return local.split(/[.\-_]/).map((p) => p.charAt(0).toUpperCase() + p.slice(1)).join(" ");
}

function short(address) {
  return address.length > 38 ? address.slice(0, 36) + "…" : address;
}

function domainOf(address) {
  if (!address) return "";
  const at = address.lastIndexOf("@");
  return at >= 0 ? address.slice(at + 1) : "";
}

function escape(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

// ---------- Simulation engine ----------

function resetDisplay() {
  state.results = [];
  state.aggregates = emptyAggregates();
  renderKpis(emptyAggregates(), state.aggregates);
  renderLabelBars(state.aggregates);
  renderSplitChart(state.aggregates);
  renderEmailList();
  renderStreamSub();
  updateLiveIndicator();
}

function shuffled(arr) {
  const a = [...arr];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

function simPlay() {
  if (state.sim.mode === "running") return;
  if (state.sim.mode === "idle" || state.sim.mode === "done") {
    // Fresh start.
    resetDisplay();
    state.sim.queue = shuffled(state.allResults);
  }
  state.sim.mode = "running";
  updateSimButtons();
  updateLiveIndicator();
  renderStreamSub();
  scheduleNextEvent();
}

function simPause() {
  if (state.sim.mode !== "running") return;
  state.sim.mode = "paused";
  if (state.sim.timer) { clearTimeout(state.sim.timer); state.sim.timer = null; }
  updateSimButtons();
  updateLiveIndicator();
  renderStreamSub();
}

function simRestart() {
  if (state.sim.timer) { clearTimeout(state.sim.timer); state.sim.timer = null; }
  state.sim.mode = "idle";
  resetDisplay();
  updateSimButtons();
  // Kick off a fresh run.
  simPlay();
}

function scheduleNextEvent() {
  if (state.sim.mode !== "running") return;
  if (state.sim.queue.length === 0) {
    state.sim.mode = "done";
    updateSimButtons();
    updateLiveIndicator();
    renderStreamSub();
    toastDone();
    return;
  }
  const base = 300 + Math.random() * 900;     // 300–1200ms per tick
  const delay = base / state.sim.speed;
  state.sim.timer = setTimeout(() => {
    const r = state.sim.queue.shift();
    revealResult(r);
    scheduleNextEvent();
  }, delay);
}

function revealResult(r) {
  const prev = state.aggregates;
  const next = JSON.parse(JSON.stringify(prev));
  updateAggregate(next, r);
  state.aggregates = next;
  state.results.unshift(r);

  prependEmailRow(r);
  renderKpis(prev, next);
  renderLabelBars(next);
  renderSplitChart(next);
  renderStreamSub();
  updateLiveIndicator();

  if (r.email.direction === "outbound" && r.scan.is_sensitive && !r.classification.all_recipients_internal) {
    leakToast(r);
  }
}

function loadAllInstant() {
  if (state.sim.timer) { clearTimeout(state.sim.timer); state.sim.timer = null; }
  state.sim.mode = "done";
  state.sim.queue = [];
  state.results = [...state.allResults];
  const agg = emptyAggregates();
  for (const r of state.allResults) updateAggregate(agg, r);
  const prev = state.aggregates || emptyAggregates();
  state.aggregates = agg;
  renderEmailList();
  renderKpis(prev, agg);
  renderLabelBars(agg);
  renderSplitChart(agg);
  renderStreamSub();
  updateLiveIndicator();
  updateSimButtons();
}

function updateSimButtons() {
  const playBtn = $("#simPlay");
  const playIcon = playBtn.querySelector(".icon-play");
  const pauseIcon = playBtn.querySelector(".icon-pause");
  const label = $("#simPlayLabel");
  if (state.sim.mode === "running") {
    playIcon.hidden = true; pauseIcon.hidden = false;
    label.textContent = "Pause";
    playBtn.title = "Pause simulation";
  } else if (state.sim.mode === "done") {
    playIcon.hidden = false; pauseIcon.hidden = true;
    label.textContent = "Replay";
    playBtn.title = "Replay simulation";
  } else if (state.sim.mode === "paused") {
    playIcon.hidden = false; pauseIcon.hidden = true;
    label.textContent = "Resume";
    playBtn.title = "Resume simulation";
  } else {
    playIcon.hidden = false; pauseIcon.hidden = true;
    label.textContent = "Start";
    playBtn.title = "Start simulation";
  }
  const hasData = state.results.length > 0;
  $("#simRestart").disabled = !hasData && state.sim.mode !== "running" && state.sim.mode !== "paused";
}

// ---------- Toasts ----------

function leakToast(r) {
  const e = r.email;
  const host = $("#toastStack");
  const toast = document.createElement("div");
  toast.className = "toast toast-leak";
  const topLabel = Object.keys(r.scan.by_label)
    .sort((a, b) => LABEL_ORDER.indexOf(a) - LABEL_ORDER.indexOf(b))[0] || "secret";
  const labelName = LABEL_META[topLabel]?.short || "PII";
  toast.innerHTML = `
    <div class="toast-icon" style="color:${LABEL_META[topLabel]?.hex || "#ef4444"}">
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.3 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>
    </div>
    <div class="toast-body">
      <div class="toast-title">Outbound leak detected · ${labelName}</div>
      <div class="toast-sub">${escape(e.subject)}</div>
      <div class="toast-meta mono">${escape(e.sender)} → ${escape(e.recipients.map(short).join(", "))}</div>
    </div>
    <button class="toast-close" aria-label="Dismiss">
      <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18"/></svg>
    </button>
  `;
  toast.querySelector(".toast-close").addEventListener("click", () => dismissToast(toast));
  toast.addEventListener("click", (ev) => {
    if (ev.target.closest(".toast-close")) return;
    openDrawer(e.id);
    dismissToast(toast);
  });
  host.appendChild(toast);
  // Auto-dismiss
  setTimeout(() => dismissToast(toast), 5200);
}

function toastDone() {
  const host = $("#toastStack");
  const toast = document.createElement("div");
  toast.className = "toast toast-done";
  toast.innerHTML = `
    <div class="toast-icon" style="color:#6ee7b7">
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>
    </div>
    <div class="toast-body">
      <div class="toast-title">Simulation complete</div>
      <div class="toast-sub">${state.aggregates.total} processed · ${state.aggregates.leaks_out} outbound leak${state.aggregates.leaks_out === 1 ? "" : "s"}</div>
    </div>
  `;
  host.appendChild(toast);
  setTimeout(() => dismissToast(toast), 4200);
}

function dismissToast(el) {
  if (!el || !el.parentNode) return;
  el.classList.add("toast-exit");
  el.addEventListener("animationend", () => el.remove(), { once: true });
}

// ---------- Number tick animation ----------

function animateNumber(el, from, to, duration) {
  if (el.__rafCancel) cancelAnimationFrame(el.__rafCancel);
  if (el.__fallback) clearTimeout(el.__fallback);
  if (!Number.isFinite(from)) from = to;
  el.textContent = from;
  const t0 = performance.now();
  const ease = (t) => 1 - Math.pow(1 - t, 3);
  const tick = (now) => {
    const raw = (now - t0) / Math.max(1, duration);
    const t = Math.max(0, Math.min(1, raw));
    const v = Math.round(from + (to - from) * ease(t));
    el.textContent = v;
    if (t < 1) {
      el.__rafCancel = requestAnimationFrame(tick);
    } else {
      el.textContent = to;
      el.__rafCancel = null;
    }
  };
  el.__rafCancel = requestAnimationFrame(tick);
  // Belt-and-braces: guarantee the terminal value no matter what rAF does.
  el.__fallback = setTimeout(() => {
    if (el.__rafCancel) cancelAnimationFrame(el.__rafCancel);
    el.__rafCancel = null;
    el.textContent = to;
  }, duration + 80);
}

// ---------- Drawer ----------

function openDrawer(id) {
  // Try current results first; fall back to allResults so deep links work before simulation finishes.
  const r = state.results.find((x) => x.email.id === id) || state.allResults.find((x) => x.email.id === id);
  if (!r) return;
  const drawer = $("#drawer");
  const backdrop = $("#drawerBackdrop");
  drawer.setAttribute("aria-hidden", "false");
  backdrop.hidden = false;
  renderDrawer(r);
}

function closeDrawer() {
  $("#drawer").setAttribute("aria-hidden", "true");
  $("#drawerBackdrop").hidden = true;
}

function renderDrawer(r) {
  const e = r.email;
  const c = r.classification;
  const isLeak = e.direction === "outbound" && r.scan.is_sensitive && !c.all_recipients_internal;

  const badges = [];
  badges.push(`<span class="badge ${e.direction}">${e.direction}</span>`);
  if (c.fully_internal) badges.push(`<span class="badge internal">fully internal</span>`);
  else if (!c.any_recipient_internal && !c.sender_internal) badges.push(`<span class="badge external">external ↔ external</span>`);
  else badges.push(`<span class="badge external">crosses boundary</span>`);
  if (isLeak) badges.push(`<span class="badge leak">outbound leak risk</span>`);
  else if (r.scan.is_sensitive) badges.push(`<span class="badge sensitive">sensitive</span>`);
  else badges.push(`<span class="badge safe">clean</span>`);

  $("#drawerBadges").innerHTML = badges.join("");

  const empChips = r.employees_referenced.length
    ? r.employees_referenced.map((x) => `
        <span class="emp-chip">${escape(x.employee)}<span class="emp-chip-role">· ${escape(x.role)}</span></span>
      `).join("")
    : `<span class="pii-none">No owned employees referenced.</span>`;

  const extDomains = c.external_domains.length
    ? c.external_domains.map((d) => `<span class="emp-chip" style="background:rgba(167,139,250,0.1);border-color:rgba(167,139,250,0.25);color:#d1bcfa">${escape(d)}</span>`).join("")
    : `<span class="pii-none">none</span>`;

  const subjectHtml = highlightText(e.subject, r.scan.subject.detected_spans);
  const bodyHtml = highlightText(e.body, r.scan.body.detected_spans);

  $("#drawerBody").innerHTML = `
    <dl class="meta-grid">
      <dt>From</dt>
      <dd class="mono">${escape(e.sender)}${internalTag(e.sender)}</dd>
      <dt>To</dt>
      <dd class="mono">${e.recipients.map((x) => escape(x) + internalTag(x)).join("<br />")}</dd>
      <dt>Sent</dt>
      <dd class="mono">${escape(e.timestamp)}</dd>
      <dt>External domains</dt>
      <dd>${extDomains}</dd>
      <dt>Owned employees referenced</dt>
      <dd>${empChips}</dd>
    </dl>

    <div class="drawer-section-title">Subject</div>
    <div class="body-box">${subjectHtml}</div>

    <div class="toggle-row" style="justify-content:space-between;margin-top:18px">
      <div class="drawer-section-title" style="margin:0">Body</div>
      <div class="segmented" id="viewToggle" data-view="highlighted">
        <button data-mode="highlighted" class="active">Highlighted</button>
        <button data-mode="redacted">Redacted</button>
      </div>
    </div>

    <div class="body-box" id="bodyBox">${bodyHtml}</div>

    <div class="drawer-section-title">Detected spans (${r.scan.span_count})</div>
    <div class="label-bars">
      ${renderSpanSummary(r.scan.by_label)}
    </div>
  `;

  const toggle = $("#viewToggle");
  toggle.querySelectorAll("button").forEach((b) => {
    b.addEventListener("click", () => {
      toggle.querySelectorAll("button").forEach((x) => x.classList.remove("active"));
      b.classList.add("active");
      const mode = b.dataset.mode;
      const box = $("#bodyBox");
      if (mode === "redacted") {
        box.innerHTML = renderRedacted(e.body, r.scan.body.detected_spans);
      } else {
        box.innerHTML = highlightText(e.body, r.scan.body.detected_spans);
      }
    });
  });
}

function renderSpanSummary(byLabel) {
  const entries = LABEL_ORDER.filter((k) => byLabel[k]);
  if (!entries.length) return `<div class="pii-none">No PII detected.</div>`;
  const max = Math.max(...entries.map((k) => byLabel[k]));
  return entries.map((k) => {
    const n = byLabel[k];
    const m = LABEL_META[k];
    return `
      <div class="bar-row" style="color:${m.hex}">
        <div class="bar-label"><span class="bar-dot"></span>${m.short}</div>
        <div class="bar-track"><div class="bar-fill" style="width:${(n / max) * 100}%"></div></div>
        <div class="bar-count">${n}</div>
      </div>
    `;
  }).join("");
}

function internalTag(addr) {
  const d = domainOf(addr).toLowerCase();
  if (state.internalDomains.includes(d)) {
    return ` <span class="badge internal" style="font-size:9.5px;padding:1px 6px;margin-left:4px">internal</span>`;
  }
  return ` <span class="badge external" style="font-size:9.5px;padding:1px 6px;margin-left:4px">external</span>`;
}

function highlightText(text, spans) {
  if (!spans || spans.length === 0) return escape(text);
  const sorted = [...spans].sort((a, b) => a.start - b.start);
  const pruned = [];
  let lastEnd = -1;
  for (const s of sorted) {
    if (s.start >= lastEnd) {
      pruned.push(s);
      lastEnd = s.end;
    }
  }
  let out = "";
  let cursor = 0;
  for (const s of pruned) {
    out += escape(text.slice(cursor, s.start));
    const m = LABEL_META[s.label];
    out += `<span class="span-hl" data-label="${s.label}" style="color:${m?.hex || '#fff'}">${escape(text.slice(s.start, s.end))}<span class="hl-tag">${m?.short || s.label}</span></span>`;
    cursor = s.end;
  }
  out += escape(text.slice(cursor));
  return out;
}

function renderRedacted(text, spans) {
  if (!spans || spans.length === 0) return escape(text);
  const sorted = [...spans].sort((a, b) => a.start - b.start);
  const pruned = [];
  let lastEnd = -1;
  for (const s of sorted) {
    if (s.start >= lastEnd) {
      pruned.push(s);
      lastEnd = s.end;
    }
  }
  let out = "";
  let cursor = 0;
  for (const s of pruned) {
    out += escape(text.slice(cursor, s.start));
    const m = LABEL_META[s.label];
    out += `<span class="redacted-tok" style="color:${m?.hex || '#fff'}">${escape(s.placeholder || "[REDACTED]")}</span>`;
    cursor = s.end;
  }
  out += escape(text.slice(cursor));
  return out;
}

// ---------- Wire up controls ----------

$("#filters").addEventListener("click", (e) => {
  const btn = e.target.closest(".chip");
  if (!btn) return;
  state.filter = btn.dataset.filter;
  document.querySelectorAll(".chip").forEach((c) => c.classList.toggle("chip-active", c === btn));
  renderEmailList();
});

$("#simPlay").addEventListener("click", () => {
  if (state.sim.mode === "running") simPause();
  else simPlay();
});
$("#simRestart").addEventListener("click", simRestart);
$("#loadAllBtn").addEventListener("click", loadAllInstant);

$("#speedSeg").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-speed]");
  if (!btn) return;
  state.sim.speed = Number(btn.dataset.speed);
  document.querySelectorAll("#speedSeg button").forEach((b) => b.classList.toggle("active", b === btn));
});

$("#drawerClose").addEventListener("click", closeDrawer);
$("#drawerBackdrop").addEventListener("click", closeDrawer);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeDrawer();
  if (e.key === " " && !e.target.matches("input, textarea, button")) {
    e.preventDefault();
    if (state.sim.mode === "running") simPause();
    else simPlay();
  }
});

loadAll().catch((err) => {
  console.error(err);
  $("#kpis").innerHTML = `<div class="panel" style="grid-column:1/-1;color:#fca5a5">Failed to load: ${escape(err.message || err)}</div>`;
});
