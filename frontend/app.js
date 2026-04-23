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
  aggregates: null,
  results: [],
  filter: "all",
};

const $ = (sel) => document.querySelector(sel);

async function loadAll() {
  const [engine, config] = await Promise.all([
    fetch("/api/engine").then((r) => r.json()),
    fetch("/api/config").then((r) => r.json()),
  ]);
  state.engine = engine.engine;
  state.engineDetail = engine.detail;
  state.internalDomains = config.internal_domains;
  renderEngineBadge();
  renderLegend();
  renderFooter();
  await scanAll();
}

async function scanAll() {
  const btn = $("#rescanBtn");
  btn.disabled = true;
  btn.querySelector("span").textContent = "Scanning…";
  try {
    const data = await fetch("/api/scan-all").then((r) => r.json());
    state.aggregates = data.aggregates;
    state.results = data.results;
    renderKpis();
    renderLabelBars();
    renderSplitChart();
    renderEmailList();
    const params = new URLSearchParams(location.search);
    const autoId = params.get("email");
    if (autoId) {
      openDrawer(autoId);
      if (params.get("view") === "redacted") {
        setTimeout(() => {
          const btn = document.querySelector('#viewToggle button[data-mode="redacted"]');
          btn && btn.click();
        }, 50);
      }
    }
  } finally {
    btn.disabled = false;
    btn.querySelector("span").textContent = "Re-scan all";
  }
}

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

function renderKpis() {
  const a = state.aggregates;
  const cards = [
    { label: "Total emails",   value: a.total,               sub: `${a.inbound} in · ${a.outbound} out · ${a.internal} internal`, cls: "" },
    { label: "Sensitive",      value: a.sensitive,           sub: `${pct(a.sensitive, a.total)}% of inbox`,                         cls: "kpi-warn" },
    { label: "Outbound leaks", value: a.leaks_out,           sub: "sensitive → external recipient",                                 cls: "kpi-danger" },
    { label: "Inbound PII",    value: a.sensitive_inbound,   sub: "external → internal with PII",                                   cls: "kpi-accent" },
    { label: "Boundary crossings", value: a.crossing_boundary, sub: "internal ↔ external",                                          cls: "" },
    { label: "PII spans",      value: Object.values(a.by_label).reduce((s, n) => s + n, 0), sub: `across ${Object.keys(a.by_label).length} categories`, cls: "kpi-ok" },
  ];
  $("#kpis").innerHTML = cards
    .map((c) => `
      <div class="kpi ${c.cls}">
        <div class="label">${c.label}</div>
        <div class="value">${c.value}</div>
        <div class="sub">${c.sub}</div>
      </div>
    `)
    .join("");
}

function renderLabelBars() {
  const counts = state.aggregates.by_label;
  const max = Math.max(1, ...Object.values(counts));
  const rows = LABEL_ORDER.map((k) => {
    const n = counts[k] || 0;
    const pctW = (n / max) * 100;
    const m = LABEL_META[k];
    return `
      <div class="bar-row" style="color:${m.hex}">
        <div class="bar-label"><span class="bar-dot"></span>${m.short}</div>
        <div class="bar-track"><div class="bar-fill" style="width:${pctW}%"></div></div>
        <div class="bar-count">${n}</div>
      </div>
    `;
  }).join("");
  $("#labelBars").innerHTML = rows;
}

function renderSplitChart() {
  const a = state.aggregates;
  const rows = [
    {
      title: "Sensitive vs clean",
      left:  { label: "sensitive", n: a.sensitive,            className: "sens" },
      right: { label: "clean",     n: a.total - a.sensitive,  className: "safe" },
    },
    {
      title: "Outbound leaks vs safe outbound",
      left:  { label: "leaks",   n: a.leaks_out,              className: "leak" },
      right: { label: "safe",    n: a.outbound - a.leaks_out, className: "safe" },
    },
    {
      title: "Traffic by recipient",
      left:  { label: "internal-only", n: a.total - a.crossing_boundary, className: "internal-seg" },
      right: { label: "external",      n: a.crossing_boundary,           className: "external-seg" },
    },
  ];
  $("#splitChart").innerHTML = rows
    .map((r) => {
      const total = Math.max(1, r.left.n + r.right.n);
      const lw = (r.left.n / total) * 100;
      const rw = (r.right.n / total) * 100;
      return `
        <div class="split-row">
          <div class="split-row-header">
            <span>${r.title}</span>
            <span><span class="n">${r.left.n}</span> / ${r.left.n + r.right.n}</span>
          </div>
          <div class="split-bar">
            <div class="split-seg ${r.left.className}" style="flex:${lw}"></div>
            <div class="split-seg ${r.right.className}" style="flex:${rw}"></div>
          </div>
          <div class="split-row-header" style="font-size:11px">
            <span>${r.left.label}</span>
            <span>${r.right.label}</span>
          </div>
        </div>
      `;
    })
    .join("");
}

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
  $("#streamSub").textContent = `Showing ${results.length} of ${state.results.length} messages`;
  list.innerHTML = results.map((r) => emailRow(r)).join("");
  list.querySelectorAll(".email-row").forEach((el) => {
    el.addEventListener("click", () => openDrawer(el.dataset.id));
  });
}

function emailRow(r) {
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
  return `
    <div class="email-row" data-id="${e.id}">
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

function pct(n, total) {
  if (!total) return 0;
  return Math.round((n / total) * 100);
}

// ------ Drawer ------

function openDrawer(id) {
  const r = state.results.find((x) => x.email.id === id);
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

$("#drawerClose").addEventListener("click", closeDrawer);
$("#drawerBackdrop").addEventListener("click", closeDrawer);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeDrawer();
});

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
  // Sort by start, drop overlapping.
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

// Filter buttons
$("#filters").addEventListener("click", (e) => {
  const btn = e.target.closest(".chip");
  if (!btn) return;
  state.filter = btn.dataset.filter;
  document.querySelectorAll(".chip").forEach((c) => c.classList.toggle("chip-active", c === btn));
  renderEmailList();
});

$("#rescanBtn").addEventListener("click", scanAll);

loadAll().catch((err) => {
  console.error(err);
  $("#kpis").innerHTML = `<div class="panel" style="grid-column:1/-1;color:#fca5a5">Failed to load: ${escape(err.message || err)}</div>`;
});
