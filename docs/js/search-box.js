// The search box: the ✕ button, product suggestions as you type, and recent searches.
import { PRODUCTS } from "./data.js";
import { $, esc } from "./dom.js";
import { MAX_RECENT, prefs, savePrefs } from "./prefs.js";

// ── Clear input ──────────────────────────────────────────────────────────
export function clearInput() {
  const input = $("productInput");
  input.value = "";
  input.focus();
  $("clearBtn").style.display = "none";
  closeSuggest();
}

// ── Recent searches ──────────────────────────────────────────────────────
export function rememberSearch(name) {
  const clean = String(name || "").trim();
  if (!clean) return;
  prefs.recent = [clean, ...prefs.recent.filter(s => s.toLowerCase() !== clean.toLowerCase())]
    .slice(0, MAX_RECENT);
  savePrefs();
  renderRecent();
}
export function clearRecent() {
  prefs.recent = [];
  savePrefs();
  renderRecent();
}
export function renderRecent() {
  const wrap = $("recentWrap");
  if (!prefs.recent.length) { wrap.style.display = "none"; wrap.innerHTML = ""; return; }
  wrap.style.display = "flex";
  wrap.innerHTML =
    `<span class="recent-label">Recent</span>` +
    prefs.recent.map(s =>
      `<button type="button" class="chip chip-recent" data-recent="${esc(s)}">${esc(s)}</button>`).join("") +
    `<button type="button" class="link-btn" id="clearRecentBtn">Clear</button>`;
}

// ── Product autocomplete ─────────────────────────────────────────────────
let suggestItems = [];
let suggestIndex = -1;

function matchProducts(text) {
  const words = text.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return [];
  const pool = [...new Set([...prefs.recent, ...PRODUCTS])];
  const hits = pool.filter(p => words.every(w => p.toLowerCase().includes(w)));
  const exact = text.trim().toLowerCase();
  // Nothing to suggest if the only match is what is already typed.
  if (hits.length === 1 && hits[0].toLowerCase() === exact) return [];
  const starts = p => (p.toLowerCase().startsWith(words[0]) ? 0 : 1);
  return hits.sort((a, b) => starts(a) - starts(b)).slice(0, 7);
}
export function openSuggest() {
  const input = $("productInput");
  const list  = $("suggestList");
  suggestItems = matchProducts(input.value);
  suggestIndex = -1;
  if (!suggestItems.length) { closeSuggest(); return; }
  list.innerHTML = suggestItems.map((p, i) =>
    `<li role="option" id="suggest-${i}" class="suggest-item" data-suggest="${esc(p)}"
         aria-selected="false">${esc(p)}</li>`).join("");
  list.hidden = false;
  input.setAttribute("aria-expanded", "true");
}
export function closeSuggest() {
  const list = $("suggestList");
  list.hidden = true;
  list.innerHTML = "";
  suggestItems = [];
  suggestIndex = -1;
  const input = $("productInput");
  input.setAttribute("aria-expanded", "false");
  input.removeAttribute("aria-activedescendant");
}
export function moveSuggest(step) {
  if (!suggestItems.length) return;
  suggestIndex = (suggestIndex + step + suggestItems.length) % suggestItems.length;
  $("suggestList").querySelectorAll(".suggest-item").forEach((li, i) => {
    const on = i === suggestIndex;
    li.classList.toggle("active", on);
    li.setAttribute("aria-selected", on ? "true" : "false");
  });
  $("productInput").setAttribute("aria-activedescendant", `suggest-${suggestIndex}`);
}

// For the keyboard handling in main.js.
export function suggestionsOpen() { return suggestItems.length > 0; }
export function highlightedSuggestion() { return suggestIndex >= 0 ? suggestItems[suggestIndex] || null : null; }
