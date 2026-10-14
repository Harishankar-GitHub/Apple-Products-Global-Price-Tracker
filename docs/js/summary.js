// The summary bar above the results, and the note when a different product was priced.
import { $ } from "./dom.js";
import { fmtMoney } from "./format.js";
import { prefs } from "./prefs.js";
import { state } from "./state.js";

// "Showing prices for X — the closest match found for "Y"." (hidden when name is null)
export function showMatchNote(name, typed) {
  const note = $("matchNote");
  if (!name) { note.hidden = true; note.replaceChildren(); return; }
  const strong = document.createElement("strong");
  strong.textContent = name;               // textContent throughout: both values are untrusted text
  note.replaceChildren("Showing prices for ", strong, ` — the closest match found for "${typed}".`);
  note.hidden = false;
}

// ── Summary (items 4 + 6) ─────────────────────────────────────────────────
function animateStat(id, newText) {
  const el = $(id);
  if (!el || el.textContent === newText) return;
  el.textContent = newText;
  el.classList.remove("flip");
  void el.offsetWidth;
  el.classList.add("flip");
}

export function updateSummary(view) {
  if (!view.listed.length) {
    if (state.activeSource === null) animateStat("summaryFound", "0");   // finished, nothing priced
    return;
  }
  // A price with no exchange rate is shown as listed, in its own currency.
  const line = i => i.value === null
    ? `${i.r.flag} ${i.r.country} — ${i.r.localPriceFormatted} · no exchange rate`
    : `${i.r.flag} ${i.r.country} — ${fmtMoney(i.value, view.cur)}`;

  animateStat("summaryFound",    String(view.listed.length));
  animateStat("summaryCheapest", view.cheapest ? line(view.cheapest) : "—");
  animateStat("summaryMostExp",  view.priciest ? line(view.priciest) : "—");
  animateStat("summaryHome", view.home ? line(view.home) : `${prefs.home} — no price`);

  const notes = [];
  if (!view.priced.length) {
    if (state.activeSource === null)
      notes.push("Exchange rates are unavailable right now, so prices can't be compared or ranked. " +
                 "Each store's own price is shown.");
  } else {
    if (view.cur !== view.wantedCur)
      notes.push(`No exchange rate for ${view.wantedCur} yet — showing USD.`);
    if (view.unconverted.length) notes.push(unrankedNote(view.unconverted));
  }
  $("summaryNote").textContent = notes.join(" ");
}

// "No exchange rate for India, so it is not ranked." (several: "India and Brazil, so they are…")
function unrankedNote(list) {
  const names = list.map(i => i.r.country);
  const who = names.length === 1 ? names[0]
    : names.length <= 3 ? `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`
    : `${names.length} countries (${names.slice(0, 3).join(", ")}…)`;
  return `No exchange rate for ${who}, so ${names.length === 1 ? "it is" : "they are"} not ranked.`;
}
