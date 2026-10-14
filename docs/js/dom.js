// Small DOM helpers: find an element, escape text for innerHTML, keep links to http(s).

export const $ = id => document.getElementById(id);

// Everything interpolated into innerHTML goes through esc().
export function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, ch =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}
export function safeUrl(u) {
  try {
    const url = new URL(u);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : "#";
  } catch (_) { return "#"; }
}
