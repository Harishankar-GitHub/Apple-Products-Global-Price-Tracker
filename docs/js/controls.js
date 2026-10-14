// The controls under the summary: home country, currency, regions, sorting and pins.
import { COUNTRY_INFO, COUNTRY_NAMES, CURRENCIES, REGIONS } from "./data.js";
import { $, esc } from "./dom.js";
import { prefs, savePrefs } from "./prefs.js";
import { renderAll, syncControls } from "./render.js";
import { renderRecent } from "./search-box.js";
import { state } from "./state.js";

function fillSelect(sel, options, value) {
  sel.innerHTML = options.map(o =>
    `<option value="${esc(o.value)}">${esc(o.label)}</option>`).join("");
  sel.value = value;
}
export function initControls() {
  fillSelect($("homeSelect"), COUNTRY_NAMES.map(n => ({ value: n, label: n })), prefs.home);
  fillSelect($("currencySelect"),
    [{ value: "", label: "Home currency" }, ...CURRENCIES.map(c => ({ value: c, label: c }))],
    prefs.currency || "");
  $("regionChips").innerHTML =
    [["all", "All regions"], ...REGIONS.map(r => [r, r])].map(([v, label]) =>
      `<button type="button" class="seg-btn" data-region="${esc(v)}"
         aria-pressed="${v === state.regionFilter}">${esc(label)}</button>`).join("");
  renderRecent();
  syncControls(null);
}

export function setSort(asc, desc) {
  const sel = $("sortSelect");
  sel.value = sel.value === asc ? desc : asc;
  renderAll();
}

export function togglePin(country) {
  if (!COUNTRY_INFO[country]) return;
  prefs.pinned = prefs.pinned.includes(country)
    ? prefs.pinned.filter(c => c !== country)
    : [...prefs.pinned, country];
  savePrefs();
  renderAll();
}
