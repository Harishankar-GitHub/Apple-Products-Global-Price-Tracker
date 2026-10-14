// Shareable links (?q=…), browser history and the Copy link button.
import { $ } from "./dom.js";

export const BASE_TITLE = document.title;
export function queryFromUrl() {
  try { return (new URLSearchParams(location.search).get("q") || "").trim().slice(0, 80); }
  catch (_) { return ""; }
}
export function writeUrl(query, replace) {
  try {
    const url = new URL(location.href);
    if (query) url.searchParams.set("q", query); else url.searchParams.delete("q");
    if (url.href === location.href) return;
    history[replace ? "replaceState" : "pushState"]({ q: query }, "", url);
  } catch (_) { /* e.g. sandboxed preview — the page still works */ }
}
export async function copyLink() {
  const btn  = $("copyLinkBtn");
  const link = location.href;
  let ok = false;
  try { await navigator.clipboard.writeText(link); ok = true; }
  catch (_) {
    try {                                     // older browsers / non-secure contexts
      const ta = document.createElement("textarea");
      ta.value = link; ta.setAttribute("readonly", "");
      ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.select();
      ok = document.execCommand("copy"); ta.remove();
    } catch (_) {}
  }
  btn.textContent = ok ? "✓ Link copied" : "Copy failed";
  setTimeout(() => { btn.textContent = "🔗 Copy link"; }, 1800);
}
