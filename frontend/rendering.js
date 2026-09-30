export const LABEL_META = {
  private_person:  { short: "Person",   hex: "#a78bfa" },
  private_email:   { short: "Email",    hex: "#22d3ee" },
  private_phone:   { short: "Phone",    hex: "#38bdf8" },
  private_address: { short: "Address",  hex: "#f472b6" },
  private_url:     { short: "URL",      hex: "#fb7185" },
  private_date:    { short: "Date",     hex: "#f59e0b" },
  account_number:  { short: "Account",  hex: "#fbbf24" },
  secret:          { short: "Secret",   hex: "#ef4444" },
};

export function escape(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

export function highlightText(text, spans) {
  // API offsets count Unicode code points, not JavaScript UTF-16 code units.
  const chars = Array.from(text);
  let out = "";
  let cursor = 0;
  for (const s of [...(spans || [])].sort((a, b) => a.start - b.start)) {
    const meta = LABEL_META[s.label];
    out += escape(chars.slice(cursor, s.start).join(""));
    out += `<span class="span-hl" data-label="${escape(s.label)}" style="color:${meta?.hex || '#fff'}">${escape(chars.slice(s.start, s.end).join(""))}<span class="hl-tag">${escape(meta?.short || s.label)}</span></span>`;
    cursor = s.end;
  }
  return out + escape(chars.slice(cursor).join(""));
}

export function renderRedacted(redactedText) {
  // The backend owns redaction; only decorate its already-redacted output.
  return escape(redactedText).replace(/\[([A-Z_]+)\]/g, (placeholder, label) => {
    const meta = LABEL_META[label.toLowerCase()];
    return meta
      ? `<span class="redacted-tok" style="color:${meta.hex}">${placeholder}</span>`
      : placeholder;
  });
}
