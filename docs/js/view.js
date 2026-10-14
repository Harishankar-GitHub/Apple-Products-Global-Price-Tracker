// The results as shown: currency, ranks, the cheapest, differences, and the rows the filters let through.
import { info } from "./data.js";
import { $ } from "./dom.js";
import { fmtMoney, fmtPct, isNum } from "./format.js";
import { prefs } from "./prefs.js";
import { state } from "./state.js";

// ── Currency ─────────────────────────────────────────────────────────────
export function displayCurrency() {
  return prefs.currency || (info(prefs.home) ? info(prefs.home).cur : "USD");
}
// Rate for a currency (units per 1 USD). Prefers the API's table; falls back
// to the rate implied by any row already received in that currency.
export function rateFor(cur) {
  if (cur === "USD") return 1;
  if (state.serverRates && isNum(state.serverRates[cur]) && state.serverRates[cur] > 0) return state.serverRates[cur];
  const row = state.allResults.find(r => r.available && r.currency === cur &&
                                   isNum(r.usdPrice) && r.usdPrice > 0 && isNum(r.localPrice));
  return row ? row.localPrice / row.usdPrice : null;
}
// The currency we can actually show: the chosen one if we have a rate, else USD.
export function activeCurrency() {
  const cur = displayCurrency();
  return rateFor(cur) ? cur : "USD";
}

// ── Derived view of the results ──────────────────────────────────────────
// Ranks, cheapest/most expensive and the differences always come from the
// full result set, so they do not change with sorting or filtering.
// Every difference is measured against the cheapest price.
export function buildView() {
  const cur  = activeCurrency();
  const rate = rateFor(cur) || 1;
  const items = state.allResults.map(r => {
    // USD price as listed. Without a (positive) conversion a price cannot be
    // compared, so it is shown as listed but never ranked — never as $0.00.
    const usd = r.available && isNum(r.usdPrice) && r.usdPrice > 0 ? r.usdPrice : null;
    return { r, c: info(r.country), usd, value: usd === null ? null : usd * rate,
             pinned: prefs.pinned.includes(r.country), isHome: r.country === prefs.home };
  });
  const priced = items.filter(i => i.value !== null).sort((a, b) => a.value - b.value);
  priced.forEach((i, idx) => { i.rank = idx + 1; });
  const listed      = items.filter(i => i.r.available);       // every country with a price
  const unconverted = listed.filter(i => i.value === null);   // …of which these have no exchange rate

  const cheapest = priced[0] || null;
  const priciest = priced[priced.length - 1] || null;
  const home     = listed.find(i => i.isHome) || null;

  items.forEach(i => {
    i.isCheapest = !!cheapest && i.value !== null && i.value === cheapest.value;
    if (cheapest && i.value !== null) {
      i.diff    = i.value - cheapest.value;
      i.diffPct = cheapest.value ? (i.diff / cheapest.value) * 100 : 0;
    } else {
      i.diff = i.diffPct = null;
    }
  });
  return { items, priced, listed, unconverted, cheapest, priciest, home, cur, wantedCur: displayCurrency() };
}

export function visibleItems(view) {
  const filter      = ($("filterInput")?.value || "").trim().toLowerCase();
  const sort        = $("sortSelect")?.value ?? "usd-asc";
  const showUnavail = $("showUnavail")?.checked ?? false;

  const shown = view.items.filter(i => {
    if (!showUnavail && !i.r.available) return false;
    if (state.regionFilter !== "all" && (!i.c || i.c.region !== state.regionFilter)) return false;
    if (filter && !i.r.country.toLowerCase().includes(filter)) return false;
    return true;
  });

  const byPrice = (a, b) => {
    if (a.value === null && b.value === null) return a.r.country.localeCompare(b.r.country);
    if (a.value === null) return 1;
    if (b.value === null) return -1;
    return a.value - b.value;
  };
  const cmp = {
    "usd-asc":      byPrice,
    "usd-desc":     (a, b) => (a.value === null || b.value === null) ? byPrice(a, b) : b.value - a.value,
    "country-asc":  (a, b) => a.r.country.localeCompare(b.r.country),
    "country-desc": (a, b) => b.r.country.localeCompare(a.r.country),
  }[sort] || byPrice;

  const group = i => (i.r.available ? (i.pinned ? 0 : 1) : 2);  // pinned, priced, unavailable
  return shown.sort((a, b) => group(a) - group(b) || cmp(a, b));
}

// "€120 more than the cheapest (+13%)". The cheapest row carries its badge instead.
export function diffLabel(i, view) {
  if (i.diff === null || i.isCheapest) return null;
  const cls = i.diffPct <= 10 ? "cheap" : i.diffPct <= 25 ? "mid" : "pricey";
  return { cls, text: `${fmtMoney(i.diff, view.cur)} more than the cheapest (+${fmtPct(i.diffPct)})` };
}
